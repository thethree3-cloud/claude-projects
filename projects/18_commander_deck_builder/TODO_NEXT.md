# Project 18 — status and what's left (updated 2026-11-18)

## Where things stand

All 7 slices are built, tested (offline `unittest`, no network) and pushed on
`feat/project-18-commander-deck-builder`. The README has the details and the
eval results; git history has the story.

| Area | Status |
|---|---|
| Card data (`card_db.py`) | Scryfall bulk -> SQLite, cheapest regular printing, images, Game Changers, daily refresh |
| EDHREC (`edhrec_client.py`) | commander + pair pages (redirects), throttle + retry, 7-day cache, commander ranking, real-page fixtures |
| Commanders | fuzzy match among cards that can lead, ties by decks led; partners, Partner with, Partner variants, Backgrounds, Doctors |
| Baseline builder (`build_deck.py`) | roles from rules text, budget + fair-share cap, upgrade pass, owned cards, optional per-card cap, staples fallback for thin/missing EDHREC data |
| Validator (`validate_deck.py`) | every format rule incl. pairs, budget, per-card cap, bracket Game Changers |
| Claude builder (`llm_deck.py`) | picks by id from the checked pool only; validator errors fed back (3 tries) |
| Evals | Slice 6 metrics (30 cases x 3 models); blind pairwise judge: Claude 26/30, baseline 0, 4 splits |
| Interfaces | CLIs, Streamlit app (3D flip, combos tab), MCP server (5 tools), blind review page |
| Combos (`combos.py`) | Commander Spellbook: combos in the deck + one card away |
| Card page | click a card name: every printing (picture, set, look, prices, Scryfall link) |
| Watch list (`watchlist.py`) | EDHREC rising cards, daily price snapshots -> price risers, your watched cards |

Quick resume:

```bash
cd projects/18_commander_deck_builder
/home/t9/venv/bin/python -m unittest discover -p "test_*.py"
/home/t9/venv/bin/streamlit run streamlit_app.py
```

## Waiting on Alan

- [ ] **Blind review:** `streamlit run review_decks.py`, pick a deck for each
      of the 6 cases. The page then shows agreement with the judge; add the
      result to the README "Blind pairwise judge" section.
- [ ] **Check the 3D flip by eye** (build an Esika deck, click a two-faced
      card). It renders and is wired to clicks, but headless Chromium here is
      missing system libraries (`libnss3`, `libasound2`; `sudo apt` needed),
      so the animation itself wasn't seen.
- [ ] **Hosted demo:** deploy on Streamlit Community Cloud (steps in README
      "Hosted demo"). Needs your Streamlit account; keep the Claude key off a
      public app.
- [ ] **Merge the PR** to `main`.
- [ ] Optional, outward-facing: upstream PR of the bulk-data fix to
      `j4th/mtg-mcp-server` (`mtg-bulk-fix.patch`).

## Watch list: saved for 2026-11-20 (ideas #4-9)

Built 2026-11-19: #1 daily EDHREC popularity snapshots + "popular, still
cheap" spec score, #2 supply / reprint risk (printings, last printed,
Reserved List, scheduled reprints), #3 new-commander radar.

- [ ] **#4 Combo spikes:** flag older cards whose combo partner is a new or
      upcoming card (Scryfall future-dated printings + Commander Spellbook).
- [ ] **#5 Better price signals:** Cardmarket EUR vs USD divergence (Scryfall
      has `eur`), foil vs normal, price range across printings (store min /
      max per card so a cheap reprint doesn't hide a rising original).
- [ ] **#6 Alerts:** daily digest (email like gov_bids, or desktop) of top
      signals and watched-card moves; target-price alerts per watched card.
- [ ] **#7 Binder value + buy log:** collection value over time, risers you
      own (sell signals), buys with date/price/qty and P&L after fees
      (~13% TCGplayer + shipping) and buylist spread.
- [ ] **#8 Backtest the signals:** after 4-6 weeks of history, check whether
      a high spec score came before price rises; tune the supply / price
      weights (they're a first guess today).
- [ ] **#9 Claude explains why:** one grounded line per flagged card (e.g.
      "rising because The Borg Queen jumped and it's her top synergy card"),
      facts from the data only.

## Could do later (not needed for v1)

- [x] Daily price snapshot: user crontab runs `watchlist.py snapshot` hourly
      and at WSL start (2026-11-18). Log in `data/watchlist_cron.log`.
- [ ] Moxfield as a trend source, only if Moxfield grants API access.

- [ ] Builder uses combos (e.g. reserve slots for a one-card-away combo when
      the budget allows). v1 only shows them.
- [ ] EDHREC budget-tier pages (budget / expensive variants of a commander page).
- [ ] Tutors as their own role.
- [ ] A non-Claude judge, if the human review disagrees with the Claude judge.
- [ ] Haiku once ran past 32k output tokens: lower `MAX_TOKENS` or effort for
      Haiku if it ever becomes the model.
- [ ] Migrate `mcp_server.py` when the venv moves to mcp 2.x (`mcp.server.fastmcp`
      was renamed); pinned to 1.30.0 for now.

## Decisions (closed 2026-11-18 unless noted)

- Model for the Claude builder: **Opus 5.5** (Slice 6 eval, 2026-10-19).
- Data source: **EDHREC only**, hardened (retries, fixtures, staples
  fallback). No Moxfield/Archidekt fallback.
- Budget: total cap, plus an **optional per-card cap** (`--max-card-price`).
- Prices: **cheapest regular printing**; promo/foil only when nothing else is priced.
- Bracket: Game Changers limits for brackets 1-3 in the validator (`--bracket`).
- Combos: **shown in v1** (Commander Spellbook), not used by the builder yet.

## Known limits

- EDHREC data is an aggregate and unofficial: parsed defensively, cached,
  covered by fixtures.
- Prices are point-in-time (Scryfall's daily bulk).
- The judge is a Claude model; the human review is the check on it.
- Commander ranking covers EDHREC's top ~2,000 commanders of the past 2
  years; others fall back to card popularity.
