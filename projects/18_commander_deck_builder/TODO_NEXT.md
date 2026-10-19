# Project 18 — what's left (written 2026-09-25, for 2026-09-26)

## Where things stand

Built, tested (55 offline tests), and pushed on branch
`feat/project-18-commander-deck-builder` (clean, 7 commits off `main`):

- **Slice 1 — `card_db.py`:** Scryfall Default Cards bulk -> SQLite, one row per
  card, cheapest-printing USD, 24 h refresh. `CardDB.candidates(identity,
  max_price=, limit=)` is the input for Slice 3.
- **`edhrec_client.py` + `commander_lookup.py`:** commander name -> ranked cards
  (inclusion %, synergy, role, price) in ~0.1-0.5 s. This is a prototype of
  Slice 2, not the finished slice (see below).
- **`fetch_staples.py`:** universal staples for colorless, mono, pair, triple
  and four-color identities (`staples/STAPLES.md`, `staples/staples.json`).
  Reads `CardDB` (no API calls, 0.3 s).

No LLM anywhere yet, and no deck is ever assembled yet.

Quick resume:

```bash
cd projects/18_commander_deck_builder
/home/t9/venv/bin/python -m unittest discover -p "test_*.py"     # should be 55 OK
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

**Built 2026-10-18 as `build_deck.py` (with owned mode from the start):**
`build_deck.py COMMANDER --budget N [--owned [--binder X]] [--out file]`.
Candidate pool = EDHREC list ∩ CardDB (legal, in identity, priced or owned);
one role per card from rules text (land / wipe / removal incl. removal auras
/ ramp / draw / synergy); order nonbasic lands -> wipes (exactly 2) ->
removal 8 -> ramp 10 -> draw 10 -> best remaining; basics free, split by
spell colors. Budget: reserve $0.25 per open slot + fair-share cap (one card
<= 4x money left per open slot) - without the cap, Kestia $100 spent $52 on
lands first. Owned mode: owned cards $0 and first within each role; owned
cards EDHREC doesn't list only fill gaps (warned). `check_deck` = quick
checks (100 cards, singleton, identity, budget); the full validator is
Slice 4. 107 tests.
Kestia $100 --owned: $87.51 spent, 3 owned cards used (Eidolon, Courser,
Archetype); $0 --owned: the 26 legal binder cards + 73 basics, with
warnings (honest: a draft binder isn't a deck).
**Upgrade pass added 2026-10-18** (on by default, `--no-upgrade` skips):
after the build, swap a chosen card for a more popular same-role card while
the leftover covers the difference; biggest inclusion gain first, repeated.
Role and land counts never change; owned EDHREC-listed cards are never
swapped out. Kestia --owned: $50 -> $49.38 spent (was $47.64), $100 ->
$99.84 (was $87.51, swaps in Hall of Heliod's Generosity + Temple Garden);
$250 still leaves ~$70 because the most-played cards are already in.
112 tests.
Still open from the list below: card images, staples fallback for thin
EDHREC pages, tutors as a role.

- [ ] **Card images (small `card_db.py` change, do first):** add `image_url` (Scryfall
      `normal`) and `image_url_back` (double-faced cards, from `card_faces`) columns,
      taken from the same printing that supplied the price so the picture matches
      the price shown. Rebuild takes ~13 s. See "Card images" below.
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

- [x] `validate_deck.py` with a test per failure mode (2026-10-18). Reads
      plain decklist text (Moxfield/Archidekt: "1 Sol Ring", "1x ... (CMM) 1",
      section headers, stops at Sideboard), so it checks any deck, not just
      the builder's. Errors: unknown card (with "did you mean"), commander
      eligibility (legendary creature, Grist-style "creature in addition to
      its other types", "can be your commander"), 100 cards, singleton (basics
      / "any number of" / "up to N" from rules text), color identity incl.
      basics, banned, budget (commander included, owned + basics free),
      Game Changers vs `--bracket`. Warnings: lands outside 34-38, ramp < 8,
      draw < 8, removal < 5, average mana value > 4, unpriced cards. Exit 0/1.
      `build_deck.py` now runs it on every deck before showing it.
- [x] Run against baseline decks: 10 commanders (mono to 5-color, Grist,
      Esika, colorless Karn) x $50/$150/$500 = **30/30 pass**. Getting there
      the validator found real bugs:
      - builder didn't count the commander's price (Kestia $100 was really
        $102.18) -> budget now includes the commander unless owned
      - validator rejected Grist (too-strict commander rule)
      - validator's own "any number of cards named" pattern was wrong
      - builder kept money back for land slots that became free basics, and
        a flat $0.25/slot reserve was both too high (cheap pools bought
        nothing) and too low -> reserve is now the real cheapest cost to fill
        the open spell slots; empty slots are filled before upgrades; when a
        budget can't fill every slot, a cheapest-first pass buys as many as
        it can (Esika $50: commander is $16.45, 55 cards cheapest-first).
- [ ] Partner commanders / backgrounds (validator and builder are single-commander).
- [ ] Fuzzy name match picked "Amnesia" for "esika" (`CardDB.find_name`):
      prefer legendary cards / word-start matches when resolving commanders.

## Slice 5 — LLM selection

- [x] Claude picks from the candidate pool only (2026-10-18, `llm_deck.py`):
      the pool (same as the baseline's: legal, in identity, priced or owned)
      goes in as an id table (role, inclusion, price/owned, rules text); the
      structured answer can only name ids, so cards can't be invented.
      One-line reason per pick + a strategy. Code adds basics and prices it.
- [x] Validator loop: unknown/repeated ids + every validator error go back
      to Claude (its answer passed back unchanged, card table cached), at
      most 3 attempts; on failure nothing is shown or written as a deck.
- [x] First real run - Kestia $100 --owned, `claude-opus-5-5` effort
      medium: **valid on attempt 1, ~35 s, ~$0.18**. vs baseline: $97.45 vs
      $99.28, avg EDHREC inclusion 38% vs 40%, 60 of ~78 nonbasic cards
      shared; Claude picked 2 owned cards EDHREC doesn't list for Kestia
      (Karametra's Favor, Stratus Walk - aura cantrips that fit Kestia) which
      the baseline only uses as filler. One run proves the loop, not that it
      "beats" the baseline - that's Slice 6.
- [ ] Decide model (Opus 5.5 default now; `--model` takes
      claude-sonnet-5-5 / claude-haiku-5-5; cost per deck is an eval axis).

## Slice 6 — evals

- [ ] Fixed test set of ~10 commanders (mono / 2 / 3 / 4-color) x budgets
      ($50 / $150 / $500).
- [ ] Metrics: validity rate first try, Jaccard overlap with EDHREC's average
      deck, budget accuracy (never over), cost per deck.
- [ ] Results table in the README (baseline vs LLM).

## Slice 7 — interface

- [ ] CLI `build.py --commander ... --budget ...` + markdown report.
- [ ] Streamlit page (commander autocomplete, budget slider, deck table,
      download button, **card image grid with prices** via `st.image`). Use the `developing-with-streamlit` skill.
- [ ] Optional: expose as an MCP tool (Project 06 pattern).

## Binder scan — build from cards you own (added 2026-10-18)

Idea from Alan's notes (`Downloads/magic/magic_1a.txt`, `magic_2.txt`):
photo of a binder page -> card names -> grade each card for a commander and
bracket. Folded into Project 18 so the deck builder can use an **owned-card
pool** instead of only cards to buy. The notes' code was not reused: broken
Scryfall URLs, retired model, hand-typed Game Changers list that was wrong
(had Sol Ring, Craterhoof, Sylvan Library, banned Mana Crypt; missed Natural
Order, Survival, Underworld Breach...).

- [x] **Game Changers from Scryfall:** `card_db.py` stores Scryfall's
      `game_changer` flag (53 cards on 2026-10-18); `CardDB.game_changers()`.
      Schema version 2 — an old database rebuilds from the cached bulk file.
- [x] **`scan_binder.py`** (2026-10-18): photo -> upright + downscaled to
      2576 px -> `claude-opus-5-5` (effort low, structured output via
      `output_config.format`, server-side refusal fallback) -> names in slot
      order -> each checked with `CardDB` (exact / corrected / unknown, never
      guessed). `--truth` scores against an answer key.
      **Result: 45/45 (100%)** on Alan's 5 real pages (Born of the Gods; angled
      shot, foils, glare, a dated prerelease promo), ~20 s for all 5.
      Answer key: `fixtures/binder_truth.json`. Photos stay in
      `Downloads/magic` (not committed - public repo).
- [ ] Harder test photos: other sets/old frames, sleeved cards with heavy
      glare, double-faced cards, non-English. Try `claude-haiku-5-5` /
      `claude-sonnet-5-5` with `--model` for cost per page.
- [x] **Owned collection** (2026-10-18): `collection.py`, own SQLite file
      `data/collection.sqlite` (gitignored; the card DB is rebuilt daily so
      it can't live there). One row per pocket (binder, page, slot); saving a
      page replaces it, so re-scans never double-count; unknown cards are
      skipped and listed. `scan_binder.py --binder NAME [--page N]` saves
      each image as consecutive pages. CLI: `list`, `find`, `binders`,
      `set-qty`, `remove-page`. Alan's 5 pages saved as "Born of the Gods"
      pages 1-5 (45 cards).
- [ ] Quantity is 1 per pocket from a scan (a photo can't see copies stacked
      behind the front card) - set real counts with `set-qty`, or add a
      "count per pocket" prompt later if it gets tedious.
- [x] **Grade a pool for a commander** (2026-10-18): `grade_pool.py`. Tier
      from data only: Not legal (color identity incl. activation costs, or
      banned) / Core (>=40% EDHREC inclusion) / Strong (>=15%) / Playable (on
      EDHREC's lists) / Filler (legal, not listed). Game Changers flagged vs
      `--bracket`; summary gives lowest bracket the pool allows (0 / <=3 /
      more). Claude (`claude-opus-5-5`, low effort, one call, structured
      output) writes one reason per legal card; reasons for cards not sent
      are ignored; `--no-llm` skips it. `--binder` limits to one binder.
      **First real run - Kestia, the Cultivator (picked by checking 14
      commanders against EDHREC; best fit for the BNG binder):** 26 of 45
      legal, 1 Core (Eidolon of Countless Battles 53%), 2 Strong (Courser,
      Archetype of Courage), 23 Filler, 19 Not legal; caught Akroan Phalanx
      (R activation) and Graverobber Spider (B activation). Reasons checked by
      hand: accurate, honest about weak cards. ~16 s.
- [ ] Grader eval: hand-label a few pools' reasons (correct / wrong rules
      claim) to track the reason accuracy, not just eyeballing.
- [ ] Later: Slice 3 builder takes `--owned` to prefer owned cards and only
      spend the budget on the gaps.
- Parked (separate product, not this portfolio project): life counter,
  Android app, paid release. **Check before ever charging:** the WotC Fan
  Content Policy requires fan content to be free, and Scryfall's API terms
  restrict paywalling their data.

## Card images (question from 2026-09-25: yes, it can show them)

- Every printing in Scryfall's bulk file already carries `image_uris` (small
  146x204, normal 488x680, large, png, art_crop) on Scryfall's own image
  servers. Free, no API key, no extra calls.
- `card_db.py` does not store them yet -> add the columns (Slice 3 task above).
- Double-faced cards keep images on `card_faces`; store front + back URLs.
- **Flip control (Alan, 2026-09-25):** two-faced cards get a flip button that swaps
  front/back, like Moxfield/Scryfall. v1: per-card `st.session_state` flag +
  `st.button`, swapping `image_url` / `image_url_back`. Later: animated 3D flip
  as a small custom HTML/CSS component (`st.components.v2`). Only cards with a
  real second face get the button (transform, modal_dfc, reversible_card);
  split, adventure, and old flip cards are a single image, so no button.
- Caveat: the printing that supplied the price can be an unusual art version
  (showcase / full-art / Secret Lair). Acceptable; alternative is the default
  printing's image, at the cost of the picture not matching the price.
- Show them in the Streamlit deck grid (Slice 7) and as image links in the
  markdown report. The LLM step never needs images.
- **Scryfall image rules:** use their image links or unaltered copies, don't
  crop or cover the artwork, and credit Scryfall. Keep the existing
  User-Agent; don't hammer the image host (cache or let the browser load them).
- Test: fixture with a DFC and a single-face card; assert the right URL per face.

## Open decisions (from the README, still unanswered)

- Model for the selection step (Sonnet vs Haiku).
- Commander Spellbook combos in v1, or later?
- Bracket support in v1, or later? (Game Changers data is now in `card_db.py`;
  only the deck-level bracket rules are left to decide.)
- Budget meaning: total-deck cap only (current plan), or also a per-card cap?
- Foil/promo printings excluded from price by default — confirm.

## Housekeeping (done 2026-09-25)

- [x] **Branch fixed:** the old `docs/project-18-...-spec` branch carried 23
      unrelated commits (Big Money Movie, Zero configurators, Warrior). Replaced
      by `feat/project-18-commander-deck-builder`: only the 7 Project 18
      commits, based on `main`, identical content, 55 tests pass. Old branch
      deleted locally and on origin.
- [x] `feat/big-money-movie-backend` pushed (Warrior `4955755` is now on origin).
- [x] `fetch_staples.py` converted to read `CardDB` instead of live Scryfall.

**Heads-up:** the working tree is now on the Project 18 branch, which is based
on `main`, so the Zero tool folders (`case_configurator`, `deep_draw_boxes`,
`warrior_rackmount`) and other movie-branch files are not checked out here.
They are safe on `feat/big-money-movie-backend` — `git switch` to it to work
on them.

## Still open

- [ ] **Open a PR** `feat/project-18-commander-deck-builder` -> `main` (now
      safe: it holds only Project 18 changes). Not done — your call.
- [ ] **Uncommitted changes unrelated to Project 18** (yours, left alone):
      `.gitignore` (adds `.vscode/`, `.venv/`), `projects/10_resume_job_matcher/score.py`
      (docstring on score bands), `projects/python_fundamentals/01_variables/variables_practice.py`
      (`Age` -> `age`), `projects/01_guidebook_agent/chunk.py` + `test_chunk.py`
      (Project 01 walkthrough in progress), `projects/benefits_pdf_practice/`
      (may hold private benefits data, so check before committing). Decide what
      to commit, and on which branch.
- [ ] Optional: upstream PR of the bulk-data fix to `j4th/mtg-mcp-server`
      (`mtg-bulk-fix.patch`). Outward-facing; needs your OK first.
- [ ] Optional: per-commander "average deck" comparison uses the same EDHREC
      data — sketch it while building the evals.

## Known limits to keep in mind

- EDHREC data is an **aggregate**, not individual decklists, and its JSON is
  unofficial (parse defensively, cache, keep fixtures).
- Rankings are popularity-driven, so cEDH-leaning cards rank high; budget
  logic must not just take the top of the list.
- Prices are point-in-time (stamp decks with the price date).
