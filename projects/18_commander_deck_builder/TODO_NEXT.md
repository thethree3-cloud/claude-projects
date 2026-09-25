# Project 18 — what's left (written 2026-09-25, for 2026-09-26)

## Where things stand

Built, tested (50 offline tests), and pushed on branch
`docs/project-18-commander-deck-builder-spec` (latest `9cbd2d9`):

- **Slice 1 — `card_db.py`:** Scryfall Default Cards bulk -> SQLite, one row per
  card, cheapest-printing USD, 24 h refresh. `CardDB.candidates(identity,
  max_price=, limit=)` is the input for Slice 3.
- **`edhrec_client.py` + `commander_lookup.py`:** commander name -> ranked cards
  (inclusion %, synergy, role, price) in ~0.1-0.5 s. This is a prototype of
  Slice 2, not the finished slice (see below).
- **`fetch_staples.py`:** universal staples for colorless, mono, pair, triple
  and four-color identities (`staples/STAPLES.md`, `staples/staples.json`).

No LLM anywhere yet, and no deck is ever assembled yet.

Quick resume:

```bash
cd projects/18_commander_deck_builder
/home/t9/venv/bin/python -m unittest discover -p "test_*.py"     # should be 50 OK
/home/t9/venv/bin/python commander_lookup.py "Muldrotha" --limit 10
```

## Slice 2 — finish the EDHREC client (small)

The prototype works but is missing:

- [ ] Handle **partner commanders** / pairs (EDHREC slug is `a-b`) and
      **backgrounds**; right now only single-commander pages resolve.
- [ ] Optional **budget-tier** pages (EDHREC has budget / expensive variants
      of each commander page — check the URL pattern).
- [ ] Throttle + retry on EDHREC HTTP errors (only 403/404 handled today).
- [ ] Save 1-2 more real-page fixtures (a partner pair, a mono-color
      commander) so format drift is caught.
- [ ] Decide: is EDHREC's unofficial JSON acceptable long-term, or add a
      fallback (Moxfield / Archidekt public decklists)? (Open decision.)

## Slice 3 — candidate pool + slot plan + no-LLM baseline (the big one)

Goal: `build_baseline.py --commander X --budget N` writes a valid 100-card
deck using only plain code. This is the bar the LLM version must beat.

- [ ] **Candidate pool:** EDHREC list ∩ `CardDB` (color identity, Commander
      legal, priced, not the commander itself).
- [ ] **Role classification by function**, not card type (EDHREC roles are
      Creature/Instant/etc.). Heuristics on `oracle_text`: ramp ("add {",
      "search your library for a basic land"), draw ("draw a card"), removal
      ("destroy target", "exile target"), wipes ("destroy all"), tutors, etc.
- [ ] **Slot plan targets:** ~36-38 lands, ~10 ramp, ~10 draw, ~8 removal,
      2-4 wipes, rest synergy/wincons. Configurable.
- [ ] **Budget allocation:** total-deck cap (default). Decide how to spend it
      (e.g. reserve for lands/fixing first, then greedy by inclusion per slot,
      then upgrade with leftover).
- [ ] **Mana base:** basics count by color-pip ratio; nonbasic lands from the
      pool by popularity within budget.
- [ ] **Output:** Moxfield/Archidekt import text + per-card prices + total.
- [ ] Use `staples/staples.json` as a fallback pool when a commander's EDHREC
      page is thin (new / rarely played commanders).
- [ ] Tests with a fixture commander page + small card DB.

## Slice 4 — validator (portfolio centerpiece)

Hard failures: exactly 100 cards incl. commander; singleton (except basics /
"any number" cards); inside commander color identity; Commander-legal; every
card exists in the DB (catches hallucinated names); total price <= budget.
Soft warnings: land count outside 34-38, low ramp/draw/removal, top-heavy
curve, Game Changers count vs requested bracket.

- [ ] `validate_deck.py` with a test per failure mode.
- [ ] Run it against the Slice 3 baseline decks first — should be 100% pass.

## Slice 5 — LLM selection

- [ ] Claude picks per slot from the candidate pool only (tool-only card
      access), with a one-line reason per pick.
- [ ] Validator loop: failures fed back, bounded retries; never present an
      invalid deck as done.
- [ ] Decide model (Sonnet vs Haiku; cost per deck is an eval axis).

## Slice 6 — evals

- [ ] Fixed test set of ~10 commanders (mono / 2 / 3 / 4-color) x budgets
      ($50 / $150 / $500).
- [ ] Metrics: validity rate first try, Jaccard overlap with EDHREC's average
      deck, budget accuracy (never over), cost per deck.
- [ ] Results table in the README (baseline vs LLM).

## Slice 7 — interface

- [ ] CLI `build.py --commander ... --budget ...` + markdown report.
- [ ] Streamlit page (commander autocomplete, budget slider, deck table,
      download button). Use the `developing-with-streamlit` skill.
- [ ] Optional: expose as an MCP tool (Project 06 pattern).

## Open decisions (from the README, still unanswered)

- Model for the selection step (Sonnet vs Haiku).
- Commander Spellbook combos in v1, or later?
- Bracket support (Game Changers list) in v1, or later?
- Budget meaning: total-deck cap only (current plan), or also a per-card cap?
- Foil/promo printings excluded from price by default — confirm.

## Housekeeping / loose ends

- [ ] **Branch name:** `docs/project-18-commander-deck-builder-spec` now holds
      working code. Rename, or just open a PR to `main` from it. Note it also
      carries the unpushed-until-today Warrior commit `4955755`, so a PR
      would include that too.
- [ ] `feat/big-money-movie-backend` is still 1 commit ahead of origin (the
      Warrior commit) — it was pushed via this branch, not that one.
- [ ] **Uncommitted changes unrelated to Project 18** are still sitting in the
      working tree: `.gitignore`, `projects/10_resume_job_matcher/score.py`,
      `projects/python_fundamentals/01_variables/variables_practice.py`,
      `projects/01_guidebook_agent/chunk.py` + `test_chunk.py`,
      `projects/benefits_pdf_practice/`. Decide what to commit or drop.
- [ ] Optional: upstream PR of the bulk-data fix to `j4th/mtg-mcp-server`
      (`mtg-bulk-fix.patch`). Outward-facing; needs your OK first.
- [ ] Optional: per-commander "average deck" comparison uses the same EDHREC
      data — sketch it while building the evals.
- [ ] Refresh `staples/` occasionally (`python fetch_staples.py`, ~200
      Scryfall requests) — prices drift daily. Could now read from `CardDB`
      instead of live calls; worth converting when convenient.

## Known limits to keep in mind

- EDHREC data is an **aggregate**, not individual decklists, and its JSON is
  unofficial (parse defensively, cache, keep fixtures).
- Rankings are popularity-driven, so cEDH-leaning cards rank high; budget
  logic must not just take the top of the list.
- Prices are point-in-time (stamp decks with the price date).
