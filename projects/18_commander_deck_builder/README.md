# Commander Deck Builder Agent (Project 18)

**Status: spec drafted 2026-09-24. Built 2026-09-25: Slice 1 (bulk-data card database), staples fetcher, commander lookup (no LLM yet).**

Give it a commander and a budget; get back a legal, priced, 100-card
Commander deck built from real popularity data. The LLM makes the judgment
calls (synergy, curve, what to cut); plain code owns every fact (card
names, color identity, legality, price) and validates the final list.

## Why standalone (findings from evaluating existing tools)

Researched 2026-09-24 (GitHub search, then a live test of
[j4th/mtg-mcp-server](https://github.com/j4th/mtg-mcp-server), MIT):

- No finished "commander deck by color + price + popularity" agent exists.
  Closest: `flegars/mtg-deckbuilder` (Electron + Claude), and
  `j4th/mtg-mcp-server` (69 tools, Scryfall/EDHREC/Spellbook/Moxfield).
- j4th's server ran but was partly broken: Scryfall changed its bulk-data
  format (`download_uri` -> `jsonl_download_uri`, gzipped JSONL). A local
  patch fixed it (saved as `mtg-bulk-fix.patch`; offline tests pass).
- Its `budget_upgrade` makes one live Scryfall call per EDHREC card (100+)
  and hung against Scryfall's rate limit. Its EDHREC inclusion % parses as 0.
- Oracle Cards bulk uses one representative printing per card, which can
  have no USD price (Sol Ring -> `frc` printing, `usd: null`).

**Design consequence:** own a small data layer, load prices from Scryfall
bulk data once, never make per-card live calls. Borrow patterns (not
runtime dependencies) from j4th's services.

## Research output: universal staples

`fetch_staples.py` pulls the most popular cards that fit any deck: colorless
cards, mono-color cards for each of W/U/B/R/G, the ten two-color pairs, and
the ten three-color identities, and the five four-color identities, ranked by EDHREC
popularity and priced at the cheapest printing. Outputs:

- [`staples/STAPLES.md`](staples/STAPLES.md) — readable tables by price tier
- `staples/staples.json` — top 350 per group, the seed for the candidate pool

Findings (2026-09-24): the colorless list is almost all lands and artifacts;
the core kit (Sol Ring, Command Tower, Arcane Signet, Exotic Orchard, Path of
Ancestry, Fellwar Stone, Mind Stone) costs under $4 total. Every color has 6+
staples under $2 in its top 150, but each top-10 mixes $0.30 cards with $50+
cards, so popularity alone blows budgets. The ten two-color pairs are also
covered (exact identity: a pair deck combines its pair list, its two mono
lists, and colorless). Pair lists are dominated by mana fixing: every pair has
5+ duals, signets, or talismans under $2, plus a few gold removal spells
(Terminate $0.33, Putrefy $0.31, Assassin's Trophy $1.26, Anguished Unmaking
$1.59). The ten three-color identities (shards and wedges) are covered too,
but they are small (58-115 cards each, vs 350 elsewhere) and roughly half
legendary creatures, which rank as commanders rather than staples. The
readable tables exclude legendary creatures (the JSON keeps them). What
remains is mana fixing (tri-lands, Charms, banners, Landscapes, all under $1)
and gold removal/wincons like Crackling Doom $0.37 and Cruel Ultimatum $0.50.
The five four-color identities hold only 2-12 cards each (commanders plus
the Nephilim), so four- and five-color decks rely entirely on the smaller
lists above. Scope note: these are global
EDHREC ranks, not per-commander inclusion rates.

### Per-commander data check (EDHREC)

Verified 2026-09-25 that `json.edhrec.com/pages/commanders/<slug>.json` works
(HTTP 200, ~110 KB for Muldrotha, 25,251 decks). Cards are grouped by role
(Creatures, Instants, Sorceries, Mana Artifacts, Utility Lands, High Synergy,
Top Cards, Game Changers, ...). Each card has `num_decks`, `potential_decks`,
and `synergy`, so **inclusion % = num_decks / potential_decks** (Eternal
Witness: 13,200 / 25,251 = 52%). This is the field j4th's server mis-parsed
as 0%. Slice 2 should compute inclusion this way.

## Commander lookup (built 2026-09-25)

Commander name in, ranked cards from other people's decks out. No LLM: this is
the deterministic baseline the agent has to beat.

```
python commander_lookup.py "Muldrotha, the Gravetide"
python commander_lookup.py "muldrotha" --max-price 1 --role "Mana Artifact"
python commander_lookup.py "Atraxa, Praetors' Voice" --sort synergy --limit 25 --json
```

Options: `--max-price` (per card, USD), `--min-inclusion` (0-1), `--role`,
`--sort inclusion|synergy`, `--limit`, `--include-basics`, `--refresh`, `--json`.

How it works: the name is fuzzy-matched against the local card database ->
EDHREC's commander JSON gives inclusion %, synergy, and role for each card
across ~25k real decks -> each card is joined to its price and type from the
local database -> filter and rank. Files: `card_db.py`, `edhrec_client.py`,
`commander_lookup.py`, with offline tests (`python -m unittest discover`)
including a trimmed real EDHREC page as a format-drift fixture.

Live-verified for Muldrotha (25,251 decks): top cards are Command Tower 87%,
Sol Ring 85%, Arcane Signet 70%, Spore Frog 59% (+53% synergy). A lookup takes
~0.1 s (cached EDHREC page) or ~0.5 s (new commander, one EDHREC request).
Before Slice 1 it took ~30 s cold because prices came from live Scryfall calls.

Known limits: inclusion is EDHREC's aggregate, not individual decklists; no
total-deck budget or slot logic yet (Slices 3-5).

## Slice 1: card database (built 2026-09-25)

`card_db.py` downloads Scryfall's **Default Cards** bulk file (every printing,
~79 MB gzipped JSONL, via the `jsonl_download_uri` key), streams it, and
collapses it to **one row per Oracle ID** in SQLite (`data/cache/cards.sqlite`,
gitignored): name, type line, oracle text, color identity (WUBRG order), cmc,
EDHREC rank, Commander legality, and USD price.

Price rules (so Sol Ring is never N/A): cheapest non-foil USD among non-promo,
non-digital printings; else cheapest promo; else cheapest foil/etched. The
chosen printing is kept (`price_source`, `price_printing`, e.g. "fic #358").
Tokens, art cards, memorabilia, and digital-only printings are skipped.

Freshness: a database younger than 24 h is used with zero network calls; older
triggers one metadata request and a re-download only if Scryfall's
`updated_at` changed. Offline with an existing database falls back to it.

Live-verified: 33,764 cards, 15 MB database, full download + build in 13 s,
candidate query ("cards in BGU under $1, most popular first") in 0.03 s.
Sol Ring $1.42, Command Tower $0.24, Arcane Signet $0.42, Eternal Witness $1.47.
API: `get`, `get_many`, `find_name` (exact, substring, fuzzy), `candidates`
(color identity + price cap + legality, by popularity). The candidates query is
the input to Slice 3.

## Design rules

1. **The LLM never supplies a fact.** Names, color identity, legality,
   price, and popularity all come from tool results. The LLM chooses among
   candidates it was handed; it cannot introduce a card that isn't in the
   candidate pool.
2. **Validation is code, not the model.** A deterministic validator has the
   last word. A deck that fails validation is retried or reported, never
   shown as done. (Same grounding lesson as Projects 11 and 14.)
3. **No per-card live API calls.** Bulk files loaded once, cached on disk,
   refreshed daily. Live calls are limited to EDHREC's one JSON per
   commander, throttled and cached.
4. **Price means one number.** Cheapest USD across all printings (excluding
   promos/foils-only unless opted in), so Sol Ring is never N/A.

## Data sources

| Need | Source | Access |
|---|---|---|
| Card facts, color identity, legality | Scryfall **Default Cards** bulk (all printings) | `/bulk-data/default-cards` -> `jsonl_download_uri` (gzipped JSONL); collapse to one row per Oracle ID |
| Price | Same file, `prices.usd` | Min USD across non-promo printings; keep `price_source` (which printing) |
| Popularity (global) | Scryfall `edhrec_rank` | In the same bulk file |
| Popularity (per commander) | EDHREC JSON | `json.edhrec.com/pages/commanders/<slug>.json` — unofficial; parse defensively, cache 7 days |
| Combos (stretch) | Commander Spellbook API | Filter by color identity |

## Pipeline

```
input: commander, total budget, [bracket, themes, must-include, exclude]
  1. resolve commander        -> Card (color identity, legal as commander)
  2. build candidate pool     -> EDHREC list ∩ color identity ∩ legal ∩ priced
  3. price + rank             -> cheapest printing, popularity, synergy
  4. slot plan                -> lands/ramp/draw/removal/wipes/win-cons targets
  5. LLM select               -> picks from pool per slot, explains each pick
  6. validate                 -> hard rules + budget; failures fed back to 5
  7. output                   -> decklist (Moxfield/Archidekt import text),
                                 per-card price, total, swaps under/over budget
```

Step 5 is the only LLM step. Steps 1-4 and 6-7 are plain, unit-tested code.

## Validator (the portfolio centerpiece)

Hard failures (block the deck):
- exactly 100 cards including the commander
- singleton (except basic lands and "any number" cards)
- every card inside the commander's color identity
- every card legal in Commander (not banned / not silver-border)
- every card exists in the candidate data (catches hallucinated names)
- total price <= budget

Soft warnings: land count outside 34-38, ramp/draw/removal below target,
mana curve too top-heavy, Game Changers count vs requested bracket.

## Evals

Score generated decks against ground truth instead of eyeballing:
- **Validity rate:** % of runs that pass the validator first try (target
  100% after retry).
- **Popularity overlap:** Jaccard overlap with EDHREC's average deck for
  the same commander.
- **Budget accuracy:** |total - budget| and never over.
- **Fixed test set:** ~10 commanders across mono/2/3/4-color and budget
  tiers ($50 / $150 / $500), run on every prompt change.

## Interface

- **v1:** CLI (`build.py --commander "Muldrotha, the Gravetide" --budget 150`)
  writing a decklist file plus a markdown report.
- **v2:** Streamlit page (commander autocomplete, budget slider, deck table
  with prices, download button).
- **v3 (optional):** expose as an MCP tool, matching Project 06's pattern.

## Slices

1. **Data layer** *(built: `card_db.py`, 26 tests)* — Default Cards bulk
   download/cache/parse, Oracle-ID collapse, min-USD pricing.
2. **EDHREC client** *(prototype built: `edhrec_client.py`)* — fetch + parse per-commander JSON (fix inclusion %
   properly), disk cache, throttle; tests against saved fixtures.
3. **Candidate pool + slot plan** — filtering, ranking, slot targets; pure
   code, no LLM yet. A "greedy top-N by popularity within budget" baseline
   that already produces a valid deck.
4. **Validator** — all hard/soft rules, with tests for each failure mode.
5. **LLM selection** — Claude picks per slot with reasons; validator loop
   with retry; strict tool-only card access.
6. **Evals** — test set, metrics, results table in the README.
7. **CLI + report**, then Streamlit UI.

Slice 3's baseline matters: it proves the data layer and gives the LLM
version something to beat in the evals.

## Open decisions

- Model choice for step 5 (Sonnet vs Haiku; cost per deck is an eval axis).
- Whether to include Commander Spellbook combos in v1 or hold for later.
- Bracket support (Game Changers list) — v1 or later.
- Budget semantics: total deck cap (default) vs also a per-card cap.
- Foil/promo printings: excluded from price by default — confirm.
- Is EDHREC's unofficial JSON acceptable long-term, or is a fallback
  (Moxfield/Archidekt public decklists for the commander) needed?

## Risks

- **EDHREC JSON is unofficial** and can change without notice: parse
  defensively, cache aggressively, keep saved fixtures so tests never hit
  the network.
- **Scryfall rate limits:** bulk-only design avoids them; identify with a
  User-Agent; never poll.
- **Bulk file size:** Default Cards is large (hundreds of MB uncompressed);
  parse streaming, store a slim per-Oracle-ID table (SQLite or Parquet).
- **Prices are point-in-time:** stamp every deck with the price date.

## Setup

Not yet built. Will use the shared venv at `/home/t9/venv/`; no API keys
needed except `ANTHROPIC_API_KEY` for step 5.
