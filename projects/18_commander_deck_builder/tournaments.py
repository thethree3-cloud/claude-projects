"""Import cEDH tournament decklists from EDHTop16 (e.g. MagicCon events).

EDHTop16 (edhtop16.com) collects cEDH results and decklists (from TopDeck.gg).
Its GraphQL API only accepts its own pre-set queries, so this reads the public
pages instead: each page embeds its data as JSON, which is decoded directly.
Requests are spaced ``MIN_INTERVAL_S`` apart, retried politely, and cached:
decklists forever (results are final), event pages for a day.

For an event it saves every decklist (player, standing, record, commander,
cards) to ``data/tournaments/<event>.json`` and works out:
  - commanders played and how they finished
  - the most-played cards across all decks and across the top cut
  - each list as a Moxfield/Archidekt import text, checked by the validator

CLI:
    python tournaments.py import https://edhtop16.com/tournament/tagc-x-bad-naus-magiccon-atlanta-cedh-open
    python tournaments.py list
    python tournaments.py stats tagc-x-bad-naus-magiccon-atlanta-cedh-open --top 16
"""

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import card_db

BASE = "https://edhtop16.com"
HEADERS = {"User-Agent": "commander-deck-builder/0.1 (personal research)", "Accept": "text/html"}
DATA_DIR = Path(__file__).parent / "data" / "tournaments"
CACHE_DIR = Path(__file__).parent / "data" / "cache" / "edhtop16"
MIN_INTERVAL_S = 1.0
RETRIES = 2
EVENT_PAGE_MAX_AGE = 86400
BASICS = {"Plains", "Island", "Swamp", "Mountain", "Forest", "Wastes"}

_last = [0.0]


class TournamentError(Exception):
    """EDHTop16 unreachable, page not found, or its format changed."""


def slug_from(url_or_slug):
    """``https://edhtop16.com/tournament/<slug>[/...]`` or a bare slug -> slug."""
    m = re.search(r"/tournament/([^/?#]+)", url_or_slug)
    slug = m.group(1) if m else url_or_slug.strip().strip("/")
    if not re.fullmatch(r"[A-Za-z0-9_-]+", slug):
        raise TournamentError(f"Not an EDHTop16 tournament link or name: {url_or_slug!r}")
    return slug


def _fetch(url):
    for attempt in range(RETRIES + 1):
        wait = _last[0] + MIN_INTERVAL_S - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        _last[0] = time.monotonic()
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=HEADERS), timeout=60) as resp:
                return resp.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                raise TournamentError(f"EDHTop16 has no page at {url}.") from exc
            if (exc.code != 429 and exc.code < 500) or attempt == RETRIES:
                raise TournamentError(f"EDHTop16 returned HTTP {exc.code} for {url}.") from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            if attempt == RETRIES:
                raise TournamentError(f"Could not reach EDHTop16: {exc}") from exc
        time.sleep(2 * (attempt + 1))


def _cached(url, path, max_age=None, fetch=None):
    path = Path(path)
    if path.exists() and (max_age is None or time.time() - path.stat().st_mtime < max_age):
        return path.read_text()
    html = (fetch or _fetch)(url)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html)
    return html


def _embedded(html, key, first_field=None):
    """Decode the JSON object stored under ``"key":`` (optionally the one whose first
    field is ``first_field``), whatever the spacing. None if it isn't there."""
    pattern = rf'"{re.escape(key)}"\s*:\s*(\{{)' + (rf'\s*"{re.escape(first_field)}"' if first_field else "")
    for m in re.finditer(pattern, html):
        try:
            value, _ = json.JSONDecoder().raw_decode(html, m.start(1))
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    return None


# ---------------------------------------------------------------------------
# Parse
# ---------------------------------------------------------------------------


def parse_event(html, slug):
    """Event facts + the decklist ids linked from its page."""
    t = _embedded(html, "tournament", "TID")
    if not t:
        raise TournamentError("Unexpected EDHTop16 event page (the site may have changed).")
    ids = list(dict.fromkeys(re.findall(rf"/tournament/{re.escape(slug)}/decklist/([A-Za-z0-9]+)", html)))
    return {"tid": t.get("TID", slug), "name": t.get("name", slug), "size": t.get("size"),
            "date": (t.get("tournamentDate") or "")[:10], "bracket_url": t.get("bracketUrl"),
            "url": f"{BASE}/tournament/{slug}", "decklist_ids": ids}


def parse_decklist(html):
    """One entry: player, standing, record, commander(s), cards (name, count, type)."""
    entry = None
    for m in re.finditer(r'"tournamentEntry"\s*:\s*(\{)', html):
        try:
            value, _ = json.JSONDecoder().raw_decode(html, m.start(1))
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict) and "decklistItems" in value:
            entry = value
            break
    if entry is None:
        raise TournamentError("Unexpected EDHTop16 decklist page (the site may have changed).")
    commander = entry.get("commander") or {}
    commanders = [c["name"] for c in commander.get("cards") or [] if c.get("name")] or \
        [n.strip() for n in (commander.get("name") or "").split(" / ") if n.strip()]
    cards = [{"name": it["card"]["name"], "count": it.get("count") or 1, "type": it["card"].get("type") or ""}
             for it in entry["decklistItems"] if it.get("card", {}).get("name")]
    return {
        "id": (entry.get("decklistUrl") or "").rsplit("/", 1)[-1],
        "player": (entry.get("player") or {}).get("name"),
        "standing": entry.get("standing"), "wins": entry.get("wins"), "losses": entry.get("losses"),
        "draws": entry.get("draws"), "price_usd": entry.get("priceUsd"),
        "commander": commander.get("name") or " / ".join(commanders), "commanders": commanders,
        "cards": cards, "topdeck_url": entry.get("decklist"),
        "edhtop16_url": BASE + (entry.get("decklistUrl") or ""),
    }


# ---------------------------------------------------------------------------
# Import + store
# ---------------------------------------------------------------------------


def import_event(url_or_slug, data_dir=DATA_DIR, cache_dir=CACHE_DIR, fetch=None, log=print):
    """Fetch an event and all its decklists; save and return the event dict."""
    slug = slug_from(url_or_slug)
    cache_dir = Path(cache_dir) / slug
    html = _cached(f"{BASE}/tournament/{slug}", cache_dir / "_event.html", EVENT_PAGE_MAX_AGE, fetch)
    event = parse_event(html, slug)
    log(f"{event['name']} ({event['date']}, {event['size']} players): {len(event['decklist_ids'])} decklists")
    entries, failed = [], []
    for n, deck_id in enumerate(event["decklist_ids"], 1):
        url = f"{BASE}/tournament/{slug}/decklist/{deck_id}"
        try:
            entries.append(parse_decklist(_cached(url, cache_dir / f"{deck_id}.html", None, fetch)))
        except TournamentError as exc:
            failed.append(deck_id)
            log(f"  {deck_id}: {exc}")
        if n % 10 == 0:
            log(f"  {n}/{len(event['decklist_ids'])} decklists")
    entries.sort(key=lambda e: (e["standing"] is None, e["standing"] or 0))
    event = {k: v for k, v in event.items() if k != "decklist_ids"} | {
        "entries": entries, "failed": failed, "imported_at": time.strftime("%Y-%m-%d %H:%M")}
    Path(data_dir).mkdir(parents=True, exist_ok=True)
    (Path(data_dir) / f"{slug}.json").write_text(json.dumps(event, indent=1))
    return event


def saved_events(data_dir=DATA_DIR):
    """Saved events, newest first: ``[{tid, name, date, size, decks}]``."""
    out = []
    for path in Path(data_dir).glob("*.json") if Path(data_dir).exists() else []:
        try:
            e = json.loads(path.read_text())
        except json.JSONDecodeError:
            continue
        out.append({"tid": e["tid"], "name": e["name"], "date": e["date"], "size": e["size"],
                    "decks": len(e["entries"])})
    return sorted(out, key=lambda e: e["date"], reverse=True)


def load_event(slug, data_dir=DATA_DIR):
    path = Path(data_dir) / f"{slug_from(slug)}.json"
    if not path.exists():
        raise TournamentError(f"No saved event {slug!r}; import it first.")
    return json.loads(path.read_text())


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------


def commander_table(event):
    """Commanders played: decks, best and average standing, record, players."""
    by = {}
    for e in event["entries"]:
        row = by.setdefault(e["commander"], {"commander": e["commander"], "decks": 0, "standings": [],
                                             "wins": 0, "losses": 0, "draws": 0, "players": []})
        row["decks"] += 1
        if e["standing"] is not None:
            row["standings"].append(e["standing"])
        for k in ("wins", "losses", "draws"):
            row[k] += e.get(k) or 0
        row["players"].append(e["player"])
    out = []
    for row in by.values():
        s = row.pop("standings")
        out.append(row | {"best": min(s) if s else None, "average": round(sum(s) / len(s), 1) if s else None})
    return sorted(out, key=lambda r: (r["best"] is None, r["best"] or 0, -r["decks"]))


def card_table(event, db=None, top=16):
    """Most-played cards (commanders and basic lands left out).

    Each: decks playing it, share of all decks, share of decks in the top
    ``top`` standings, type, and today's price from the card database."""
    entries = event["entries"]
    top_ids = {e["id"] for e in entries if e["standing"] is not None and e["standing"] <= top}
    counts = {}
    for e in entries:
        skip = set(e["commanders"])
        for c in e["cards"]:
            if c["name"] in skip or c["name"] in BASICS:
                continue
            row = counts.setdefault(c["name"], {"name": c["name"], "type": c["type"], "decks": 0, "top_decks": 0})
            row["decks"] += 1
            row["top_decks"] += e["id"] in top_ids
    info = db.get_many(list(counts)) if db else {}
    n_all, n_top = len(entries), len(top_ids)
    out = []
    for name, row in counts.items():
        card = info.get(name)
        out.append(row | {"share": row["decks"] / n_all if n_all else 0.0,
                          "top_share": row["top_decks"] / n_top if n_top else 0.0, "top_size": n_top,
                          "usd": card["usd"] if card else None,
                          "edhrec_rank": card["edhrec_rank"] if card else None})
    return sorted(out, key=lambda r: (-r["top_decks"], -r["decks"], r["name"]))


def deck_text(entry):
    """Moxfield / Archidekt import text, commander(s) first."""
    skip = set(entry["commanders"])
    lines = [f"1 {c}" for c in entry["commanders"]]
    lines += [f"{c['count']} {c['name']}" for c in sorted(entry["cards"], key=lambda c: c["name"])
              if c["name"] not in skip]
    return "\n".join(lines)


def check_deck(entry, db):
    """Run the validator on a tournament list (no budget)."""
    from validate_deck import validate_text
    members = entry["commanders"]
    return validate_text(deck_text(entry), db, commander_name=members[0] if members else None,
                         partner_name=members[1] if len(members) > 1 else None)


AUTO_MIN_SIZE = 64  # players
AUTO_DAYS = 30
AUTO_MAX_PER_DAY = 2  # each event is ~1 request per decklist


def recent_events(min_size=AUTO_MIN_SIZE, days=AUTO_DAYS, fetch=None, today=None, cache_dir=CACHE_DIR):
    """Big recent events from EDHTop16's tournament list: ``[{tid, name, size, date}]``, newest first."""
    import datetime as dt
    html = _cached(f"{BASE}/tournaments?sortBy=DATE&minSize={min_size}",
                   Path(cache_dir) / f"_list_{min_size}.html", EVENT_PAGE_MAX_AGE, fetch)
    today = dt.date.fromisoformat(today) if today else dt.date.today()
    out = {}
    for m in re.finditer(r'"TID":"([^"]+)","name":"((?:[^"\\]|\\.)*)","size":(\d+),"tournamentDate":"([^"]+)"', html):
        tid, name, size, date = m.group(1), json.loads(f'"{m.group(2)}"'), int(m.group(3)), m.group(4)[:10]
        if re.search(r"\btest\b", name, re.I):
            continue  # organizers' test events
        if size >= min_size and date and (today - dt.date.fromisoformat(date)).days <= days:
            out.setdefault(tid, {"tid": tid, "name": name, "size": size, "date": date})
    return sorted(out.values(), key=lambda e: e["date"], reverse=True)


def auto_import(max_events=AUTO_MAX_PER_DAY, data_dir=DATA_DIR, fetch=None, today=None, log=print, **kwargs):
    """Import up to ``max_events`` big recent events not saved yet. Returns their names."""
    saved = {e["tid"] for e in saved_events(data_dir)}
    done = []
    for ev in recent_events(fetch=fetch, today=today, **kwargs):
        if len(done) >= max_events:
            break
        if ev["tid"] in saved:
            continue
        try:
            event = import_event(ev["tid"], data_dir=data_dir, fetch=fetch, log=log)
            done.append(event["name"])
        except TournamentError as exc:
            log(f"  {ev['name']}: {exc}")
    return done


def card_play(db=None, days=60, top=16, data_dir=DATA_DIR, today=None):
    """``{card name: (top_decks, top_size, event name)}`` from saved events in the last
    ``days`` days, keeping each card's best showing (for the watch list)."""
    import datetime as dt
    today = dt.date.fromisoformat(today) if today else dt.date.today()
    best = {}
    for ev in saved_events(data_dir):
        if not ev["date"] or (today - dt.date.fromisoformat(ev["date"])).days > days:
            continue
        event = load_event(ev["tid"], data_dir)
        n_top = sum(1 for e in event["entries"] if e["standing"] is not None and e["standing"] <= top)
        for row in card_table(event, None, top):
            if row["top_decks"] and (row["name"] not in best or row["top_share"] > best[row["name"]][0] / best[row["name"]][1]):
                best[row["name"]] = (row["top_decks"], n_top, event["name"])
    return best


def main(argv=None):
    parser = argparse.ArgumentParser(description="Import cEDH tournament decklists from EDHTop16.")
    sub = parser.add_subparsers(dest="command", required=True)
    p_imp = sub.add_parser("import", help="fetch an event and its decklists")
    p_imp.add_argument("event", help="EDHTop16 tournament link or its name in the link")
    sub.add_parser("list", help="saved events")
    p_auto = sub.add_parser("auto", help=f"import big recent events ({AUTO_MIN_SIZE}+ players, last {AUTO_DAYS} days)")
    p_auto.add_argument("--max", type=int, default=AUTO_MAX_PER_DAY)
    p_stats = sub.add_parser("stats", help="commanders and most-played cards")
    p_stats.add_argument("event")
    p_stats.add_argument("--top", type=int, default=16)
    p_stats.add_argument("--limit", type=int, default=25)
    args = parser.parse_args(argv)
    try:
        if args.command == "import":
            event = import_event(args.event, log=lambda m: print(m, file=sys.stderr))
            print(f"Saved {len(event['entries'])} decklists from {event['name']}"
                  + (f" ({len(event['failed'])} could not be read)" if event["failed"] else "") + ".")
        elif args.command == "auto":
            names = auto_import(args.max, log=lambda m: print(m, file=sys.stderr))
            print(f"Imported {len(names)} event(s)" + (": " + "; ".join(names) if names else " (none new)."))
        elif args.command == "list":
            for e in saved_events():
                print(f"{e['date']}  {e['name']}  ({e['decks']} decklists, {e['size']} players)  [{e['tid']}]")
        elif args.command == "stats":
            event = load_event(args.event)
            db = card_db.open_db(log=lambda m: print(m, file=sys.stderr))
            try:
                print(f"# {event['name']} ({event['date']}, {event['size']} players, {len(event['entries'])} lists)\n")
                for c in commander_table(event)[:15]:
                    print(f"{c['best']:>3}  {c['commander']}  ({c['decks']} deck{'s' if c['decks'] > 1 else ''}, "
                          f"{c['wins']}-{c['losses']}-{c['draws']})")
                table = card_table(event, db, args.top)
                n_top = table[0]["top_size"] if table else 0
                print(f"\nMost played by the {n_top} top-{args.top} decks with a list:")
                for r in table[: args.limit]:
                    price = f"${r['usd']:.2f}" if r["usd"] is not None else "n/a"
                    print(f"  {r['top_decks']:>2}/{n_top} top, {r['decks']:>2}/{len(event['entries'])} all  "
                          f"{r['name']} ({price}, EDHREC rank {r['edhrec_rank']})")
            finally:
                db.close()
    except TournamentError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
