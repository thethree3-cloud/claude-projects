"""Card jobs from Scryfall Tagger: ramp, removal, board wipe, card draw, tutor.

Scryfall's community "oracle tags" (``otag:``) say what a card does, which is
more accurate than guessing from rules text. This fetches every
Commander-legal card for each tag through Scryfall's search API (about 86
pages, ~20 s with Scryfall's requested 100 ms gap), saves
``data/cache/scryfall_tags.json``, and the card database picks the tags up on
its next build (``card_db.ensure_db`` passes them in; ``python
scryfall_tags.py`` rebuilds it right away). Refreshed weekly by the daily job.

CLI:
    python scryfall_tags.py           # fetch tags and rebuild the card database
"""

import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

API = "https://api.scryfall.com/cards/search"
HEADERS = {"User-Agent": "commander-deck-builder/0.1", "Accept": "application/json"}
TAGS_PATH = Path(__file__).parent / "data" / "cache" / "scryfall_tags.json"
# Scryfall tag -> our job name.
TAG_ROLES = {"board-wipe": "wipe", "removal": "removal", "counterspell": "removal", "ramp": "ramp", "draw": "draw",
             "tutor": "tutor",
             # Bracket flags (not jobs): left out of the pool for target brackets 1-3.
             "mass-land-denial": "mld", "extra-turn": "extra_turn"}
MAX_AGE_DAYS = 7
GAP_S = 0.2
RETRIES = 5


class TagError(Exception):
    """Scryfall search unreachable or answered unexpectedly."""


def _get(url, sleep=time.sleep):
    """GET one search page. Scryfall asks for a 50-100 ms gap; on 429 (too many
    requests) it wants a real pause, so honor Retry-After or back off 10 s, 20 s, 40 s..."""
    for attempt in range(RETRIES + 1):
        sleep(GAP_S)
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=HEADERS), timeout=60) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return {"data": [], "has_more": False}  # Scryfall's "no cards matched"
            if (exc.code != 429 and exc.code < 500) or attempt == RETRIES:
                raise TagError(f"Scryfall returned HTTP {exc.code}.") from exc
            retry_after = exc.headers.get("Retry-After") if exc.headers else None
            sleep(float(retry_after) if retry_after and retry_after.isdigit() else 10 * 2 ** attempt)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            if attempt == RETRIES:
                raise TagError(f"Could not reach Scryfall: {exc}") from exc
            sleep(5 * (attempt + 1))


def fetch_tag(tag, get=None):
    """Oracle ids of every Commander-legal card with Scryfall tag ``tag``."""
    get = get or _get
    url = API + "?" + urllib.parse.urlencode({"q": f"otag:{tag} legal:commander", "unique": "cards"})
    ids = []
    while url:
        page = get(url)
        ids += [c["oracle_id"] for c in page.get("data", []) if c.get("oracle_id")]
        url = page.get("next_page") if page.get("has_more") else None
    return ids


def refresh(path=TAGS_PATH, get=None, log=print, only=None):
    """Fetch tags; save ``{"fetched", "roles": {oracle_id: [job, ...]}}``. ``only`` (a list of
    Scryfall tags) fetches just those and merges them into the saved file."""
    roles = {}
    if only:
        old = json.loads(Path(path).read_text())["roles"] if Path(path).exists() else {}
        wanted = {TAG_ROLES[t] for t in only}
        roles = {oid: [r for r in rs if r not in wanted] for oid, rs in old.items()}
    for tag, role in TAG_ROLES.items():
        if only and tag not in only:
            continue
        ids = fetch_tag(tag, get)
        log(f"  otag:{tag}: {len(ids):,} cards")
        for oid in ids:
            roles.setdefault(oid, []).append(role)
    if not roles:
        raise TagError("Scryfall returned no tagged cards (format changed?).")
    roles = {oid: rs for oid, rs in roles.items() if rs}
    data = {"fetched": time.strftime("%Y-%m-%d"), "roles": roles}
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(data))
    return data


def load(path=TAGS_PATH):
    """``{oracle_id: "ramp,draw"}`` from the saved file, or None if there is none."""
    path = Path(path)
    if not path.exists():
        return None
    try:
        roles = json.loads(path.read_text())["roles"]
    except (json.JSONDecodeError, KeyError):
        return None
    return {oid: ",".join(r) for oid, r in roles.items()}


def is_stale(path=TAGS_PATH, max_age_days=MAX_AGE_DAYS):
    path = Path(path)
    return not path.exists() or time.time() - path.stat().st_mtime > max_age_days * 86400


def main(argv=None):
    parser = argparse.ArgumentParser(description="Fetch Scryfall Tagger card jobs and rebuild the card database.")
    parser.add_argument("--only", nargs="+", choices=sorted(TAG_ROLES), help="fetch just these tags and merge")
    args = parser.parse_args(argv)
    import card_db
    try:
        data = refresh(log=lambda m: print(m, file=sys.stderr), only=args.only)
    except TagError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    print(f"Saved jobs for {len(data['roles']):,} cards; rebuilding the card database...", file=sys.stderr)
    card_db.ensure_db(refresh=False, log=lambda m: print(m, file=sys.stderr), rebuild=True)
    print("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
