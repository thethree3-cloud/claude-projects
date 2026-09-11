# Big Money Movie

A daily movie/TV title word-guess game: masked title, genre/era
categories ("70s Cop Movies," "60s Disney Movies"), tiered hints with
time penalties, a leaderboard ranked by fastest solve. Named after a
local-TV afternoon movie show: the station played a movie and callers
phoned in for a prize if they were the right caller — this game rewards
being the fastest solver instead. Full design spec lives in project
memory, not this repo.

**Build status**: category pool curation (slice 1), the core guess loop
(slice 2), elapsed-time scoring + the leaderboard query (slice 3), the
hint system (slice 4), and the FastAPI HTTP layer (slice 5) are done. No
client yet — see "What's deliberately not here yet" below.

## Run the API

```bash
pip install -r ../../requirements.txt   # adds fastapi, uvicorn, httpx
python db.py                            # one-time: creates data/big_money_movie.sqlite
uvicorn api:app --reload
```

By itself the schema is empty — see `curate.py` (slice 1) to generate a
grounded category pool, then load a `categories`/`category_pool`/`puzzles`
row set (an automated seed step from `curate.py`'s JSON isn't built yet,
see below). Once seeded:

```bash
curl http://127.0.0.1:8000/category/today
curl -X POST http://127.0.0.1:8000/attempt/start -H 'Content-Type: application/json' \
     -d '{"puzzle_id": 1, "player_id": "alan"}'
curl -X POST http://127.0.0.1:8000/attempt/1/guess -H 'Content-Type: application/json' \
     -d '{"guess_text": "Dirty Harry"}'
curl -X POST http://127.0.0.1:8000/attempt/1/hint -H 'Content-Type: application/json' \
     -d '{"tier": 3}'
curl http://127.0.0.1:8000/leaderboard/1
```

## Design principle carried through every slice

Every fact a player or a category pool relies on is either **verified
against real data** or **computed server-side** — nothing here trusts
free-form input at face value:

- Claude's proposed titles are checked against a local IMDb index before
  they enter a pool (curation, offline).
- A guess is checked with plain string comparison against the stored
  answer, not judged by an LLM (gameplay, live) — the same discipline
  that keeps the LLM out of the timed loop entirely.
- Every timestamp (`started_at`, `finished_at`) and the resulting
  `final_elapsed_ms` come from the server clock, computed the instant a
  correct guess lands — never from anything a client reports.

## Slice 1 — Category pool curation

Turns a theme like "70s Cop Movies" into a trustworthy list of real
titles, offline, ahead of any gameplay:

1. **Claude proposes** candidate titles for a theme + era.
2. **A local IMDb index verifies** each one — title and year checked
   against real data before a candidate is trusted. Claude's output is a
   claim to check, not a fact to accept (same pattern as Project 01's
   handbook grounding, Project 11's SQL generation).
3. **A human reviews the output once** before a grounded list becomes a
   shipped category pool — this script verifies *facts*, it doesn't judge
   whether a title truly *feels* like "a 70s cop movie."

### Setup

```bash
pip install -r ../../requirements.txt   # anthropic, python-dotenv — already
                                         # satisfied if you've set up the
                                         # repo root venv
python imdb_index.py --build            # one-time: downloads IMDb's free
                                         # non-commercial title.basics
                                         # dataset (~227MB) and builds a
                                         # local SQLite grounding index
```

Requires `ANTHROPIC_API_KEY` in the repo-root `.env` (already shared with
every other project here).

### Usage

```bash
python curate.py --theme "Cop Movies" --era-start 1970 --era-end 1979
```

Writes `data/pools/cop-movies.json`:

```json
{
  "theme": "Cop Movies",
  "era_start": 1970,
  "era_end": 1979,
  "grounded": [
    {
      "proposed_title": "Dirty Harry",
      "proposed_year": 1971,
      "grounded": true,
      "imdb_id": "tt0066999",
      "canonical_title": "Dirty Harry",
      "year": 1971,
      "title_type": "movie",
      "genres": ["Action", "Crime", "Thriller"],
      "word_count": 2
    }
  ],
  "rejected": [
    { "proposed_title": "...", "grounded": false, "rejection_reason": "..." }
  ]
}
```

Review `rejected` entries by hand — each one is either a Claude
hallucination (title doesn't exist / wrong decade) or a real gap in the
local index worth knowing about.

### Known limitations, found via live testing

Verified live against two real themes ("70s Cop Movies," "60s Disney
Movies"):

- **A real bug, fixed**: `normalize_title` now canonicalizes "&" to
  "and" — IMDb has the 1975 TV series as "Starsky and Hutch," Claude
  proposed "Starsky & Hutch," and without the fix that class of title
  never matched. See `test_ampersand_canonicalizes_to_and`.
- **A real gap, deliberately left as a documented limitation, not
  patched**: IMDb doesn't consistently use digits vs. spelled-out
  numbers. The 1961 animated film's canonical title is "One Hundred and
  One Dalmatians" — "101 Dalmatians" in IMDb is the 1996 remake. A
  numeral-to-words normalizer was considered and rejected: title
  numbering has no consistent convention ("Se7en" vs. "Seven," "2001: A
  Space Odyssey" always digits), so a heuristic here risks *introducing*
  wrong groundings, worse than a correctly-flagged miss. Left for the
  human review step.

## Slice 2 — Core guess loop

Given a puzzle's answer, decides whether a guess is correct and manages
the masked-title display and attempt state. Reuses `imdb_index.normalize_title`
for guess comparison — so a guess is checked with the exact same
normalization the curation script already uses (a player typing "Starsky
& Hutch" is accepted against an answer stored as "Starsky and Hutch," the
same equivalence `curate.py` relies on).

```bash
python db.py     # one-time: creates data/big_money_movie.sqlite with the
                  # runtime schema (categories, category_pool, puzzles,
                  # attempts, guesses)
```

```python
from db import get_connection, init_schema
from attempts import start_attempt, submit_guess

conn = get_connection()
init_schema(conn)   # safe to call repeatedly, CREATE TABLE IF NOT EXISTS

attempt_id = start_attempt(conn, puzzle_id=1, player_id="alan")
submit_guess(conn, attempt_id, "The Godfather")   # {'correct': False, 'masked_title': '_____ _____', ...}
submit_guess(conn, attempt_id, "dirty harry!")    # {'correct': True,  'masked_title': 'Dirty Harry', ...}
```

- `guess_loop.py` — pure functions only, no DB: `mask_title()`,
  `check_guess()`, `now_iso()` (the one place server timestamps are
  generated).
- `attempts.py` — DB-touching orchestration: `start_attempt()` enforces
  one attempt per player per puzzle; `submit_guess()` records every guess,
  sets `finished_at` server-side the moment a correct guess lands, and
  rejects further guesses once an attempt is finished.
- `db.py` — SQLite schema (`categories`, `category_pool`, `puzzles`,
  `attempts`, `guesses`) and connection helper.

Verified live end-to-end against the real grounded "Cop Movies" pool from
slice 1: a wrong guess returns the masked title, a correct guess
(including a case/punctuation-different phrasing) returns the full title
and stamps `finished_at`.

## Slice 3 — Elapsed-time scoring + leaderboard

`submit_guess()` now computes `final_elapsed_ms` the instant a correct
guess lands — `elapsed_ms(started_at, finished_at) + total_penalty_ms`
(the penalty term is 0 until hints exist, but the formula is already
correct for when they do; adding hints later is additive, not a rework).
`leaderboard.py` ranks finished attempts for one puzzle, fastest first.

```python
from leaderboard import get_leaderboard

get_leaderboard(conn, puzzle_id=1, limit=10)
# [{'rank': 1, 'player_id': 'speedy', 'final_elapsed_ms': 3389, 'guess_count': 1, 'finished_at': '...'}, ...]
```

Tie-breaking (an open question in the original spec, resolved here):
`final_elapsed_ms` ascending, then `guess_count` ascending (fewer guesses
wins a tie), then `finished_at` ascending as a final deterministic
tiebreak. Attempts with no `finished_at` never appear — nothing to rank
until someone actually solves it.

Verified live: three players raced the same real "Dirty Harry" puzzle
through the actual `start_attempt`/`submit_guess` calls (not seeded rows),
with `started_at` backdated by a different number of seconds each to
simulate real solve speed. The leaderboard came back correctly ordered
fastest-to-slowest with millisecond-accurate `final_elapsed_ms`.

## Slice 4 — Hint system

Three tiers, each usable once per attempt, each adding a fixed time
penalty to `total_penalty_ms` (already folded into `final_elapsed_ms` by
slice 3, so this was additive, not a rework):

| Tier | Reveals | Penalty |
|---|---|---|
| 1 — Vowel | every occurrence of one vowel present in the title | +15s |
| 2 — Consonant | every occurrence of one consonant present in the title | +30s |
| 3 — Word | every letter of one whole word — or, for a single-word title (nothing else to reveal), the first half of its letters instead | +60s |

**Selection is always system-picked and guaranteed present** — v1's
locked-in design: no wasted hints, no exploit where a player always asks
for the rarest letter for outsized value per second spent. A v2
user-picks-the-letter mode (miss still costs the hint, Wheel-of-Fortune
style) stays deferred, not built.

```python
from hints import apply_hint

apply_hint(conn, attempt_id, tier=1)
# {'tier': 1, 'penalty_ms': 15000, 'total_penalty_ms': 15000, 'masked_title': '___ ______ _o______o_'}
```

The masked title returned by a hint (and by a subsequent wrong guess) is
built by `attempts.get_masked_title()`, which reads back *every* hint
already used on the attempt — reveals accumulate and never regress
between calls. Tier 3's single-word fallback needs no extra schema
column: `hint3_word_index` stays `NULL`, and `word_count == 1` at render
time is itself the signal to apply the deterministic partial reveal
(`guess_loop.partial_reveal_positions()` — same title always reveals the
same letters, no stored position needed).

Verified live on two real titles from the grounded "Cop Movies" pool:
all three tiers in sequence on "The French Connection" (reveals
accumulated correctly across tiers, `total_penalty_ms` summed to
105,000ms, folded correctly into `final_elapsed_ms` on the finishing
guess), and the single-word fallback on "Chinatown" (`"China____"`).

## Slice 5 — FastAPI HTTP layer

A thin protocol wrapper over everything above — `api.py`'s only job is
HTTP request → function call → HTTP response, same "logic already built
and tested, this is purely the wrapper" pattern as Project 11's MCP
`server.py`.

```
GET  /                          health check
GET  /category/today            → { puzzle_id, date, theme, era, pool_size } (never the pool or the answer)
POST /attempt/start              { puzzle_id, player_id } → { attempt_id }
POST /attempt/{id}/guess         { guess_text } → { correct, guess_count, masked_title }
POST /attempt/{id}/hint          { tier: 1|2|3 } → { tier, penalty_ms, total_penalty_ms, masked_title }
GET  /leaderboard/{puzzle_id}   → ranked list (optional ?limit=)
```

`AttemptError`/`HintError` (the latter a subclass of the former, so one
`except` clause in each endpoint covers both) become an HTTP 400; a
missing puzzle on `/category/today` is a 404. New: `puzzles.py`'s
`get_todays_puzzle()` looks up the puzzle scheduled for today's date and
returns only `theme`/`era`/`pool_size` — never the pool contents or the
answer, so a player can't just read the answer off this endpoint.

### A real bug, caught twice by actually running it

1. **SQLite thread affinity.** The first live test run failed with
   `SQLite objects created in a thread can only be used in that same
   thread`. FastAPI runs sync `def` endpoints (and their sync
   dependencies) in a threadpool, and a single request's dependency-open
   and endpoint-body calls aren't guaranteed to land on the same worker
   thread — sqlite3's default thread affinity doesn't tolerate that, even
   though each request already gets its own dedicated connection, never
   shared across requests. Fixed in `db.get_connection()`:
   `sqlite3.connect(db_path, check_same_thread=False)`.
2. **Local vs. UTC "today."** `puzzles.today_iso()` originally used
   `date.today()` — local server timezone — while every other timestamp
   in the app (`guess_loop.now_iso()`) is explicit UTC. Caught by
   actually checking the dev machine's clock while testing live: local
   date was `2026-09-10` while UTC was already `2026-09-11 05:42`, a
   15-hour skew. That's not a cosmetic bug — it means which puzzle counts
   as "today's" would silently depend on the server's deployment
   timezone (relevant given Project 15's planned Azure deployment) or
   flip at the wrong wall-clock hour. Fixed to
   `datetime.now(timezone.utc).date().isoformat()`.

Verified live for real, not just via `TestClient`: ran `uvicorn api:app`
as an actual background process, seeded the on-disk SQLite DB with a real
grounded puzzle ("Dirty Harry," UTC-dated), and played a full game over
real `curl` HTTP calls — `/category/today` → start → wrong guess → Tier-3
hint → correct guess → `/leaderboard/1`, plus the duplicate-attempt 400 —
all matched the `TestClient` test suite's expectations exactly.

## Files

| File | Role |
|---|---|
| `imdb_index.py` | Downloads IMDb's free dataset, builds a local SQLite grounding index, matches a candidate title/year against it (year tolerance for remakes/re-releases). No Claude calls. |
| `generate_pool.py` | `generate_category_pool(theme, era_start, era_end)` — the propose-then-ground pipeline. `propose_candidates()` (Claude call) and `ground_candidates()` (pure verification) are separated so each is independently testable. |
| `curate.py` | CLI driver for slice 1 — runs the pipeline for one theme, writes the reviewable JSON output. |
| `guess_loop.py` | Pure functions for slices 2-4: `mask_title()`, `mask_title_with_reveals()`, `partial_reveal_positions()`, `check_guess()`, `now_iso()`, `elapsed_ms()`. |
| `attempts.py` | DB-touching attempt/guess orchestration — starting attempts, recording guesses, scoring `final_elapsed_ms`, and `get_masked_title()` (the reveal-state-aware masked display used by both a guess response and a hint response). |
| `hints.py` | `apply_hint(conn, attempt_id, tier)` — the three-tier hint system. |
| `db.py` | SQLite schema + connection helper (`check_same_thread=False`, see slice 5's bug writeup) for the runtime gameplay store. |
| `leaderboard.py` | `get_leaderboard(conn, puzzle_id, limit)` — ranks finished attempts for one puzzle. |
| `puzzles.py` | `get_todays_puzzle(conn)` — looks up today's puzzle (UTC date) and its category metadata, without exposing the pool or the answer. |
| `api.py` | FastAPI app — the HTTP layer described in slice 5. |
| `test_*.py` | Unit tests, one file per module above. All pure/mocked — no live API call, no live download, no network at all. Claude is stood in for with a fake client (mirrors `test_run_report.py`'s pattern in Project 11); DB tests run against an in-memory SQLite instance seeded with a few rows; hint letter/word selection is patched (`unittest.mock.patch("hints.random.choice", ...)`) for deterministic assertions where the exact pick matters; `test_api.py` uses FastAPI's `TestClient` with a dependency override so every request in a test shares one seeded connection. |

## What's deliberately not here yet

- **Director / lead-actor enrichment** — IMDb's `title.basics` doesn't
  carry cast/crew; that needs `title.principals.tsv.gz` + `name.basics.tsv.gz`
  (a much bigger join) or the TMDB API. Left as `None` for now rather than
  adding scope before the core curation loop is proven out.
- **Automatic "does this title really fit the theme" checking** — IMDb
  genre tags are informational for the human reviewer; there's no attempt
  to map a free-text theme like "cop movies" onto IMDb's fixed genre
  vocabulary.
- **A seed step from `curate.py`'s JSON output into `category_pool`** —
  right now that table is populated by hand/script per demo; a real
  "promote a reviewed pool into the runtime DB" command isn't built.
- **v2 user-picks-the-letter hints** (Wheel-of-Fortune style, miss still
  costs the hint) — deliberately deferred; v1 ships system-picks-only.
- **Rate-limiting guess/hint submissions** — the spec's anti-cheat plan
  calls for it (e.g. 1/sec) to block scripted brute-forcing. `api.py`
  doesn't do this yet.
- **No auth, no player accounts** — `player_id` is just a caller-supplied
  string. Fine for a portfolio demo/seeded playtest, not for a public
  deployment.
- The Kotlin/Compose Android client — the only remaining build slice per
  the original plan.
