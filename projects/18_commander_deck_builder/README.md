# Commander Deck Builder Agent (Project 18)

**Status: spec drafted 2026-09-24. Not started.**

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
cards plus mono-color cards for each of W/U/B/R/G, ranked by EDHREC
popularity and priced at the cheapest printing. Outputs:

- [`staples/STAPLES.md`](staples/STAPLES.md) — readable tables by price tier
- `staples/staples.json` — top 350 per group, the seed for the candidate pool

Findings (2026-09-24): the colorless list is almost all lands and artifacts;
the core kit (Sol Ring, Command Tower, Arcane Signet, Exotic Orchard, Path of
Ancestry, Fellwar Stone, Mind Stone) costs under $4 total. Every color has 6+
staples under $2 in its top 150, but each top-10 mixes $0.30 cards with $50+
cards, so popularity alone blows budgets. Not yet covered: two- and
three-color identities. Scope note: these are global EDHREC ranks, not
per-commander inclusion rates.

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

1. **Data layer** — Default Cards bulk download/cache/parse, Oracle-ID
   collapse, min-USD pricing; tests with a small fixture file.
2. **EDHREC client** — fetch + parse per-commander JSON (fix inclusion %
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
