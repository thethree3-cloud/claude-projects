# Commander Deck Builder Agent (Project 18)

**Status (2026-11-18): all 7 slices built and tested.** Code-only and Claude
builders, a full format validator, partner commanders, evals plus a blind
pairwise judge, a Streamlit app, an MCP server and Commander Spellbook
combos. What's left: [`TODO_NEXT.md`](TODO_NEXT.md).

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

`fetch_staples.py` reads the local card database (no API calls, runs in under a
second) for the most popular cards that fit any deck: colorless cards,
mono-color cards for each of W/U/B/R/G, the ten two-color pairs, the ten
three-color identities, and the five four-color identities, ranked by EDHREC
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

Known limit: inclusion is EDHREC's aggregate, not individual decklists.
(Budget, slots and deck building came later; see Slices.)

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

Since schema 4 (2026-11-18) it also keeps a `printings` table: every real
printing (101,184) with set, number, date, rarity, artist, look, normal /
foil / etched prices, images and Scryfall link, for the card page
(`CardDB.printings(name)`). The database is now ~54 MB; rebuilding from the
cached bulk file takes ~9 s and happens automatically on a schema change.

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
| Popularity (as commander) | EDHREC commander ranking | `pages/commanders/year.json` + paged `more` links, top ~2,000, cached 7 days |
| Combos | Commander Spellbook API | `POST backend.commanderspellbook.com/find-my-combos`, cached per decklist |

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
- every card inside the commander's color identity (both commanders' colors for a pair)
- two commanders must legally pair: Partner, "Partner with [name]", the
  Partner variants (Friends forever, Character select, Survivors, Father &
  son), Choose a Background + a Background, Doctor's companion + a Time Lord
  Doctor
- every card legal in Commander (not banned / not silver-border)
- every card exists in the candidate data (catches hallucinated names)
- total price <= budget; optional per-card limit (`--max-card-price`; the
  commander and owned cards don't count)
- Game Changers within the limit for `--bracket` 1-3

Soft warnings: land count outside 34-38, ramp/draw/removal below target,
mana curve too top-heavy, unpriced cards.

## Evals (Slice 6, run 2026-10-19)

`eval_decks.py` scores Claude-built decks (`llm_deck.py`) against the no-LLM
baseline (`build_deck.py`) on a fixed set: 10 commanders (mono to five-color,
a planeswalker commander, a double-faced card, colorless) x $50 / $150 /
$500 = **30 cases, one run per model**. All metrics are free code checks:

| Variant | Cases | Valid 1st try (95% CI) | Valid | Budget used | Avg-deck overlap | Inclusion | Roles OK | $/deck | s/deck |
|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| baseline (no LLM) | 30 | 100% (89%-100%) | 100% | 89% | 59% | 38% | 93% | $0.000 | 0.0 |
| claude-opus-5-5 | 30 | 93% (79%-98%) | 100% | 96% | 52% | 37% | 63% | $0.198 | 39.2 |
| claude-sonnet-5-5 | 30 | 73% (56%-86%) | 100% | 65% | 39% | 34% | 30% | $0.085 | 19.8 |
| claude-haiku-5-5 | 30 (+1 err) | 83% (66%-93%) | 100% | 62% | 32% | 32% | 73% | $0.008 | 43.5 |

- **Valid 1st try:** passes the validator with no feedback. **Valid:** within
  3 tries; every model reached 100% - no invalid deck was ever produced.
- **Budget used:** cost to buy / budget (going over is a validator failure).
- **Avg-deck overlap:** Jaccard overlap of nonbasic cards with EDHREC's
  average deck. **Inclusion:** mean EDHREC inclusion of the deck's cards.
- **Roles OK:** lands 34-38, ramp >= 8, draw >= 8, removal >= 5.

What the numbers say:
- **The safety loop works.** 90 Claude decks, 0 invalid ones shown. First-try
  failures were over-budget sums (Opus 2 of 2 failed cases, Sonnet 7 of 8,
  Haiku 2 of 5) or bad ids (Haiku 3 invented + 1 repeated, Sonnet 1
  invented, e.g. `c96x`) - exactly what the id-only pick list and validator
  exist to catch.
- **Claude does not beat the baseline on these metrics.** Overlap and
  inclusion reward copying EDHREC popularity, which is what the baseline does
  by design, so they favor it; Opus comes closest (52% vs 59% overlap,
  37% vs 38% inclusion) and spends the budget best (96%).
- **Model choice: Opus.** It is the only model that uses the budget and
  matches real decks; Sonnet and Haiku leave ~35-40% of the money unspent
  and drift from real decklists. Haiku is 25x cheaper per deck than Opus,
  so it would be the pick only if cost per deck mattered more than quality.
- **"Roles OK" is a rule of thumb, not a quality score.** Most of Opus's
  misses are "fewer than 8 draw cards", including all three Krenko decks
  (fast goblin decks run little draw - every model missed there).
- Whether Claude's decks *play* better is measured separately by a blind
  judge (next section).

Run cost: **$8.75 measured** for all 90 Claude decks (Opus $5.95, Sonnet
$2.55, Haiku $0.25), pilot included; ~12 minutes with 4 cases in parallel.
One Haiku case hit the 32k output limit, was logged as an error and re-run
(its usage isn't in the total; error rows now keep the usage of failed
attempts, and the summary adds it). Raw rows: `evals/runs/<variant>/results.jsonl`;
table: `evals/RESULTS.md` (`python eval_decks.py --summary`).

### Blind pairwise judge (run 2026-11-18)

The metrics above reward copying EDHREC, so they can't say which deck plays
better. `judge_decks.py` asks a **different model (Sonnet 5.5; Opus 5.5 built
the decks)** to compare the Opus deck and the baseline deck for each of the
30 cases. Both decks are rebuilt from the saved trace, so they come from the
same candidate table and the same prices. The judge sees "Deck A" / "Deck
B" grouped by card type with short rules text and counted facts (lands,
average mana value): no builder name, strategy, reasons, prices or role
labels. It scores five criteria (1-10) and picks a winner. **Each case is
judged twice with the order swapped; a deck wins only if it wins both.**

| Outcome | Cases | Share (95% CI) |
|---|--:|--:|
| Claude (Opus 5.5) deck wins | 26 | 87% (70%-95%) |
| Baseline (no LLM) deck wins | 0 | 0% (0%-11%) |
| Split (orders disagree) | 4 | 13% |

| Mean score (1-10) | synergy | mana | interaction | card_flow | win_path |
|---|--:|--:|--:|--:|--:|
| Claude deck | 7.9 | 7.6 | 7.8 | 7.3 | 7.7 |
| Baseline deck | 7.5 | 7.2 | 6.5 | 6.9 | 6.8 |

- **By budget:** Claude wins 7/10 at $50, 9/10 at $150, 10/10 at $500.
  The $500 wins are partly money: the baseline's cap often leaves it far
  under budget there (Kestia $184 vs Claude $461). At $50 both spend
  nearly all of it, and Claude still wins 7 with 3 splits and 0 losses.
- **Where it wins:** interaction (+1.3) and a clear win path (+0.9). The
  baseline picks by popularity per role; Claude picks removal and finishers
  that fit the commander.
- **All 4 splits are position flips** (each order picked the deck shown
  first or the other way round, never the baseline in both). The first-shown
  deck won 57% of decided calls, a mild position bias the swap cancels.
- **Caveats:** one judge, and it's also a Claude model (possible
  same-family preference); an LLM judge is not play-testing. Its reasons
  sometimes misread a deck (it called Edgar's R/W lands off-color), which
  is why the pilot's land miscount led to adding counted facts to the
  prompt. **Human check:** `review_decks.py` shows 6 of these cases blind
  (2 per budget, including 2 splits) for a person to pick; it reveals the
  builders and the judge's verdict only after all 6. Result: pending.

Cost: **$1.52** for 60 judge calls (~10k input tokens each), 55 s with 4 in
parallel; pilot $0.10. Raw rows: `evals/judge/claude-sonnet-5-5/results.jsonl`;
table: `evals/JUDGE.md` (`python judge_decks.py --summary`).

## Two commanders (partners, Backgrounds, Doctors) - added 2026-11-18

Every tool takes `--partner NAME` (fuzzy, matched only among cards that can
legally pair with the first commander), and the Streamlit page shows a
"Second commander" picker when the chosen commander can pair.

- **Rules** (`card_db.pairing` / `pair_problem`): the five pair types above,
  read from the rules text and type line; `CardDB.partner_names(card)` lists
  legal partners (e.g. Thrasios: 57, Halsin: 30 Backgrounds, Nikara: only
  Yannik). A Background alone is refused.
- **Deck:** 98 cards + 2 commanders, color identity = both commanders',
  cost = both (owned ones free). The validator reads a pair from the first
  two lines when they legally pair, or from `--commander` / `--partner`.
- **EDHREC:** the pair's own page (`a-b`, alphabetical; the other order
  answers `{"redirect": ...}`, which is followed). If it has fewer than 50
  decks or doesn't exist, each commander's own page is mixed in (pair-page
  numbers win). Backgrounds have no page of their own.
- Checked on real data: Thrasios + Tymna $150, Halsin + Raised by Giants
  $75, Nikara + Yannik $50, Ryan Sinclair + The Fourth Doctor $60, Elmar +
  Wernog $80 all build and pass the validator; single-commander decks are
  unchanged (Kestia $100 still $98.39).

## Robustness and fallbacks (2026-11-18)

- **EDHREC requests** are spaced 0.5 s apart and retried on 429 / 5xx /
  network errors (1 s, 2 s, 4 s, or the server's `Retry-After`); missing
  pages fail at once. Trimmed real pages (Thrasios + Tymna, Krenko) are
  test fixtures, so a format change shows up in the tests.
- **Thin or missing EDHREC data:** under 150 EDHREC cards, the pool gets the
  most-played cards in the commander's colors (ranked below every real
  EDHREC card, with a warning). A brand-new commander with no page at all
  still gets a valid deck (checked: Ragnarok, Divine Deliverance $60).
- **Commander names** match by how many decks a card *leads* (EDHREC's
  2-year ranking): "krenko" is Mob Boss (45,216 decks), not Tin Street
  Kingpin (1,802). A leading "The" is skipped, so "gitrog" is The Gitrog
  Monster. Without the network it falls back to card popularity.
- **Per-card cap:** `--max-card-price 3` drops cards you'd buy above $3
  (Kestia $150 -> a valid $54 deck).

## Combos (Commander Spellbook)

`combos.py` sends a decklist (card names only) to Commander Spellbook and
lists **combos already in the deck** and **combos one card away** inside the
deck's colors, with that card's price. Cached per decklist. The builder
doesn't add combos itself (v1 shows them). Example: the $150 Krenko baseline
has 7 (e.g. Krenko + Skirk Prospector + Goblin Warchief); one card away:
Zealous Conscripts ($0.29) with Kiki-Jiki.

```
python combos.py deck.txt              # --partner if line 2 is a second commander
python build_deck.py krenko --budget 150 --combos
```

## Interface

- **CLI:** `build_deck.py` (no LLM) and `llm_deck.py` (Claude), with
  `--partner`, `--max-card-price`, `--owned`, write a Moxfield/Archidekt
  import list (`--out`) plus a markdown report; `validate_deck.py` checks any
  decklist; `combos.py` finds combos; `grade_pool.py` grades your collection
  for a commander; `commander_lookup.py` shows EDHREC's cards.
- **Streamlit app:** `streamlit run streamlit_app.py`. Commander search
  (ordered by decks led), second-commander picker when the commander can
  pair, budget, optional per-card limit, "use my collection" with a binder
  filter, code-only or Claude (shown only when an API key is set). Shows
  cost, lands, average mana value, owned cards used and the validator
  verdict, Claude's strategy and per-card reasons, warnings, a download
  button, a sortable list, a **Combos** tab (fetched on click), and a card
  image grid by role where **two-faced cards turn over with a 3D flip**
  (`flip_card.py`, a Streamlit components-v2 element; the flip runs in the
  browser with no rerun). An invalid Claude deck is never shown. Logic lives
  in `deck_service.py` (unit-tested).
- **Card page** (added 2026-11-18): click any card name in the deck to open
  its page: picture (flips if two-faced), rules text, color identity,
  legality, Game Changer flag, and **every printing** with its picture,
  set, number, year, rarity, look (borderless / showcase / extended art...),
  normal / foil / etched prices, artist and a Scryfall link. Sort by newest,
  oldest or cheapest; hide promos; show only priced. The printing the deck
  builder prices from is marked. Same tab, so the deck and sidebar settings
  stay (`persist_state`); the List tab's "All printings" link opens it in a
  new tab. Pages: `streamlit_app.py` (entry, `st.navigation`) ->
  `app_pages/builder.py`, `app_pages/card.py` (`?name=Sol Ring`).
- **MCP server:** `mcp_server.py` (FastMCP over stdio, Project 06's
  pattern) with `find_commander`, `commander_cards`, `build_commander_deck`
  (code-only builder, validated), `validate_commander_deck` and
  `find_combos`. The deck tool doesn't call Claude: the MCP client already
  is an LLM, so a second paid call would be hidden cost. Smoke-tested with a
  real stdio client. Register it with:

  ```bash
  claude mcp add commander-deck-builder -- /home/t9/venv/bin/python /home/t9/claude-projects/projects/18_commander_deck_builder/mcp_server.py
  ```
- **Blind review page:** `streamlit run review_decks.py` (see the judge section).

## Watch list (added 2026-11-18)

A **Watch list** page (top menu of the app; also `python watchlist.py`):

- **Rising on EDHREC:** EDHREC's top 1,000 cards for the past week next to
  its past-2-years list, most rising first by EDHREC's trend score, with the
  week's inclusion, the 2-year inclusion, the change in percentage points
  and "new" for cards not in the 2-year list. Filters: fits these colors,
  max price, hide lands, new only. (First look, 2026-11-18: the new Star
  Trek set's Borg cards lead; One, Borg Evolved 7.8% of decks this week vs
  5.3% over 2 years.) Cached 6 hours; ~10 s the first time.
- **Price risers:** a daily snapshot of every card's price (cheapest regular
  printing, $0.25 and up) from the Scryfall file we already download, kept
  120 days in `data/watchlist.sqlite` (~0.14 MB a day). Compared over 7 or
  30 days. History starts the first day it runs (Scryfall has no past
  prices), so risers appear from the second day; running
  `python watchlist.py snapshot` daily (e.g. cron) avoids gaps.
- **My watch list:** add cards from the form, the **Watch** star on any card
  page, or by selecting rows in either list. Shows price now, change since
  added / 7 / 30 days, this week's EDHREC trend, a note, and a price chart.
  Watched cards' history is never pruned.
- **Moxfield isn't a source:** it blocks outside requests (Cloudflare 403)
  and its API needs approval from Moxfield, so it isn't used.

## Hosted demo (Streamlit Community Cloud)

Ready to deploy; the deploy itself needs a Streamlit account:

1. share.streamlit.io -> Create app -> this GitHub repo, branch `main` (or
   this branch), main file `projects/18_commander_deck_builder/streamlit_app.py`,
   Python 3.12. `requirements.txt` next to the app lists what it needs.
2. Leave the Anthropic key out of a public app: without it the app hides
   the Claude builder and runs the code-only builder for free. To demo
   Claude, make the app private (invite viewers) and add
   `ANTHROPIC_API_KEY = "..."` under Settings -> Secrets.
3. First load takes ~20 s (downloads Scryfall's ~80 MB bulk file, builds the
   card database, fetches the commander ranking); later loads are fast.
   "Use my collection" stays off there (your scanned collection is local
   and gitignored).

Checked locally from a fresh copy with no `data/` folder and no key: first
load 20 s, Claude hidden, Krenko $100 with a $3 card cap built and passed.

## Slices

1. **Data layer** *(done)* — `card_db.py`: Default Cards bulk, Oracle-ID
   collapse, cheapest-printing USD, images, Game Changers.
2. **EDHREC client** *(done)* — `edhrec_client.py`: inclusion = num/potential,
   pair pages, throttle + retry, cache, fixtures, commander ranking.
3. **Candidate pool + slot plan + baseline** *(done)* — `build_deck.py`.
4. **Validator** *(done)* — `validate_deck.py`, a test per failure mode.
5. **LLM selection** *(done)* — `llm_deck.py`, ids only, validator loop.
6. **Evals** *(done)* — `eval_decks.py` metrics + `judge_decks.py` blind judge.
7. **Interfaces** *(done)* — CLIs, Streamlit app, MCP server.

## Decisions

- Claude builder model: **Opus 5.5** (Slice 6 eval).
- Data: **EDHREC only**, hardened (retries, fixtures, staples fallback).
- Budget: total cap plus an **optional per-card cap**.
- Price: **cheapest regular printing**; promo/foil only when nothing else is priced.
- Bracket: Game Changers limits for brackets 1-3 in the validator.
- Combos: **shown** (Commander Spellbook), not used by the builder yet.

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

Uses the shared venv at `/home/t9/venv/` (`requirements.txt` lists the
app's packages; `mcp_server.py` also needs `mcp==1.30.0`). The first run
downloads Scryfall bulk data (~80 MB) into `data/cache/` and refreshes it
daily. Only the Claude features (binder scanning, grader reasons, Claude
decks, evals, judge) need `ANTHROPIC_API_KEY` in the repo-root `.env`.

```bash
cd projects/18_commander_deck_builder
/home/t9/venv/bin/python -m unittest discover -p "test_*.py"
/home/t9/venv/bin/streamlit run streamlit_app.py
```
