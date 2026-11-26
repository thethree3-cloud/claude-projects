"""Export the card database and cached EDHREC pages for the Card Scanner artifact.

The artifact can't call Scryfall or EDHREC (its page may only load its own
files), so the facts it needs ship beside it as compact JSON:

    cards.json      one array per card: name, color identity, type, mana value,
                    USD price, priciest regular printing, EDHREC rank, flags,
                    role letters from Scryfall Tagger (see ROLE_LETTERS), and the set code
                    and rarity letter of the printing that price comes from
    oracle.json     {name: rules text}, fetched only when "Ask Claude why" is used
    commanders.json the cached EDHREC commander pages: inclusion % and synergy
                    for every card EDHREC lists with that commander
    printings/x.json every printing of each card (set, number, finishes, prices), one file per first letter
    sets.json       set code -> set name
    top_commanders.json  for popular cards and the cards you own: the 5 commanders whose
                    EDHREC decks play each card most ({card: [[commander, decks, potential], ...]})
    set_icons.json  Scryfall set symbols as data: URIs ({"icons": {key: uri}, "sets": {code: key}}),
                    downloaded once into data/cache/set_icons/ (only new sets are fetched later)
    trends.json     weekly price points (last ~90 days) and the Card Kingdom buylist
                    offer per card, from data/watchlist.sqlite (MTGJSON history)
    meta.json       when the prices were last updated, counts

No API calls: it reads data/cache/cards.sqlite and data/cache/edhrec_*.json.
`updater.py` runs this as its last step ("scanner export"); after that, the
artifact needs republishing (ask Claude) to pick the new files up.

    python export_scanner_data.py                    # -> data/scanner_artifact/
    python export_scanner_data.py --out some/folder
"""

import argparse
import base64
import json
import sqlite3
import time
import urllib.request
from pathlib import Path

import edhrec_client

HERE = Path(__file__).parent
DB = HERE / "data" / "cache" / "cards.sqlite"
DEFAULT_OUT = HERE / "data" / "scanner_artifact"
WATCHLIST = HERE / "data" / "watchlist.sqlite"
ICON_CACHE = HERE / "data" / "cache" / "set_icons"
SCRYFALL_SETS = "https://api.scryfall.com/sets"
HEADERS = {"User-Agent": "commander-deck-builder/0.1", "Accept": "application/json"}
TOP_RANKED_FOR_COMMANDERS = 2000   # the most-played cards on EDHREC
COMMANDER_FETCH_BUDGET = 300        # new EDHREC card pages per run (0.5 s apart): the cache fills over a few runs
WANTED = DEFAULT_OUT / "wanted.txt"  # one card name per line: cards from your pile and decks, fetched first
TREND_STEP_DAYS = 7

# Flags packed into one number per card.
GAME_CHANGER, LEGAL, CAN_COMMAND, RESERVED = 1, 2, 4, 8
# Scryfall Tagger roles (card_db "tags") -> one letter each, for the deck shape and bracket checks.
ROLE_LETTERS = {"ramp": "r", "draw": "d", "removal": "x", "wipe": "w", "tutor": "t", "mld": "m", "extra_turn": "e"}


def short_type(type_line):
    """'Legendary Creature — Phyrexian Angel // ...' -> 'Legendary Creature'."""
    front = type_line.split(" // ")[0]
    return front.split(" — ")[0].strip()


def can_be_commander(type_line, oracle_text):
    front = type_line.split(" // ")[0]
    return ("Legendary" in front and "Creature" in front) or "can be your commander" in (oracle_text or "")


def export_cards(conn):
    cards, oracle = [], {}
    # (oracle id, set, number) -> rarity letter, to give each card's price printing its rarity.
    rarity = {(o, st, n): (r or "?")[:1] for o, st, n, r in
              conn.execute("SELECT oracle_id, set_code, collector_number, rarity FROM printings")}
    rows = conn.execute(
        "SELECT name, type_line, oracle_text, color_identity, cmc, edhrec_rank, legal_commander, "
        "game_changer, reserved, usd, usd_max, tags, price_printing, oracle_id FROM cards ORDER BY name")
    for r in rows:
        flags = ((GAME_CHANGER if r["game_changer"] else 0) | (LEGAL if r["legal_commander"] else 0)
                 | (CAN_COMMAND if r["legal_commander"] and can_be_commander(r["type_line"], r["oracle_text"]) else 0)
                 | (RESERVED if r["reserved"] else 0))
        roles = "".join(ROLE_LETTERS[t] for t in (r["tags"] or "").split(",") if t in ROLE_LETTERS)
        set_code, _, number = (r["price_printing"] or "").partition(" #")
        cards.append([r["name"], r["color_identity"], short_type(r["type_line"]), r["cmc"],
                      r["usd"], r["usd_max"] if r["usd_max"] != r["usd"] else None, r["edhrec_rank"], flags, roles,
                      set_code or None, rarity.get((r["oracle_id"], set_code, number))])
        oracle[r["name"]] = f"{r['type_line']}\n{r['oracle_text']}".strip()
    return cards, oracle


def export_commanders(cache_dir=edhrec_client.CACHE_DIR):
    out = {}
    for path in sorted(cache_dir.glob("edhrec_*.json")):
        if path.name.startswith("edhrec_avg_"):
            continue  # average-deck lists, not commander pages
        try:
            page = edhrec_client.parse_commander_page(json.loads(path.read_text(encoding="utf-8")))
        except (edhrec_client.EdhrecError, json.JSONDecodeError):
            continue
        c = page["commander"]
        if not c.get("name") or not page["cards"]:
            continue
        out[c["name"]] = {
            "decks": c.get("num_decks") or 0,
            # name -> [inclusion %, synergy %], rounded to whole percents to keep the file small
            "cards": {k["name"]: [round(k["inclusion"] * 100), round((k["synergy"] or 0) * 100)]
                      for k in page["cards"]},
        }
    return out


def bucket(name):
    """Which printings file a card lives in: its first letter, '_' for anything else."""
    import unicodedata
    ch = unicodedata.normalize("NFKD", name)[:1].lower()
    return ch if "a" <= ch <= "z" else "_"


def export_printings(conn):
    """{bucket: {card name: [printing, ...]}} plus {set code: set name}.

    A printing: [set, collector number, released YYYY-MM-DD, rarity letter,
    treatment, finishes, promo 0/1, usd, usd_foil, usd_etched]. Newest first.
    The Scryfall page is https://scryfall.com/card/<set>/<number>.
    """
    buckets, sets = {}, {}
    rows = conn.execute(
        "SELECT k.name, p.set_code, p.set_name, p.collector_number, p.released_at, p.rarity, p.treatment, "
        "p.finishes, p.promo, p.usd, p.usd_foil, p.usd_etched FROM printings p JOIN cards k USING (oracle_id) "
        "ORDER BY k.name, p.released_at DESC, p.set_code, p.collector_number")
    for r in rows:
        sets.setdefault(r["set_code"], r["set_name"])
        buckets.setdefault(bucket(r["name"]), {}).setdefault(r["name"], []).append([
            r["set_code"], r["collector_number"], r["released_at"], (r["rarity"] or "?")[:1],
            r["treatment"] or "", r["finishes"] or "", r["promo"], r["usd"], r["usd_foil"], r["usd_etched"]])
    return buckets, sets


def export_trends(conn, watchlist=WATCHLIST, step=TREND_STEP_DAYS):
    """{"days": [YYYYMMDD, ...], "cards": {name: [[cents per day | null], buylist cents | null]}}.

    One point every `step` days counting back from the newest day, oldest first,
    so every card shares the same x axis. Prices are the cheapest regular
    TCGplayer printing (see price_history.py). Missing file -> None.
    """
    if not Path(watchlist).exists():
        return None
    from datetime import date, timedelta
    wl = sqlite3.connect(watchlist)
    all_days = [r[0] for r in wl.execute("SELECT DISTINCT day FROM snapshots ORDER BY day")]
    if not all_days:
        return None
    as_date = lambda d: date(d // 10000, d // 100 % 100, d % 100)
    newest, oldest = as_date(all_days[-1]), as_date(all_days[0])
    have = set(all_days)
    picked, d = [], newest
    while d >= oldest:
        # Nearest stored day at or before each step (a missed daily run shouldn't leave a hole).
        k = int(d.strftime("%Y%m%d"))
        back = d
        while k not in have and back > oldest:
            back -= timedelta(days=1)
            k = int(back.strftime("%Y%m%d"))
        if k in have and k not in picked:
            picked.append(k)
        d -= timedelta(days=step)
    picked.sort()
    index = {day: i for i, day in enumerate(picked)}
    names = dict(conn.execute("SELECT oracle_id, name FROM cards"))
    ids = {i: names.get(o) for i, o in wl.execute("SELECT id, oracle_id FROM card_ids")}
    out = {}
    q = f"SELECT day, card, cents, buy_cents FROM snapshots WHERE day IN ({','.join('?' * len(picked))})"
    for day, card, cents, _ in wl.execute(q, picked):
        name = ids.get(card)
        if not name:
            continue
        row = out.setdefault(name, [[None] * len(picked), None])
        row[0][index[day]] = cents
    # Buylist offers arrive a day behind prices: take the newest day that has any.
    buy_day = wl.execute("SELECT MAX(day) FROM snapshots WHERE buy_cents IS NOT NULL").fetchone()[0]
    if buy_day:
        for card, buy in wl.execute("SELECT card, buy_cents FROM snapshots WHERE day = ? AND buy_cents IS NOT NULL", (buy_day,)):
            name = ids.get(card)
            if name in out:
                out[name][1] = buy
    # Drop cards with fewer than two points: no trend to show.
    out = {n: r for n, r in out.items() if sum(v is not None for v in r[0]) >= 2}
    return {"days": picked, "buy_day": buy_day, "cards": out}


def _get(url, timeout=30):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def export_set_icons(cache_dir=ICON_CACHE, fetch=_get, log=print, max_age_days=7):
    """Set symbols as data: URIs. The set list is refreshed weekly; each icon file is
    downloaded once (Scryfall asks for ~10 requests a second at most). Network trouble
    keeps whatever is cached. Returns {"icons": {...}, "sets": {...}} or None."""
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    list_path = cache_dir / "_sets.json"
    sets = None
    if not list_path.exists() or time.time() - list_path.stat().st_mtime > max_age_days * 86400:
        try:
            sets = json.loads(fetch(SCRYFALL_SETS))["data"]
            list_path.write_text(json.dumps(sets), encoding="utf-8")
        except Exception as exc:  # offline: fall back to the cached list
            log(f"set list not refreshed: {exc}")
    if sets is None and list_path.exists():
        sets = json.loads(list_path.read_text(encoding="utf-8"))
    if not sets:
        return None
    by_code, icons = {}, {}
    for st in sets:
        uri = (st.get("icon_svg_uri") or "").split("?")[0]
        key = uri.rsplit("/", 1)[-1].removesuffix(".svg")
        if not key or not key.replace("-", "").replace("_", "").isalnum():
            continue
        path = cache_dir / f"{key}.svg"
        if not path.exists():
            try:
                body = fetch(uri)
                if b"<svg" not in body[:2000]:
                    raise ValueError("not an SVG")
                path.write_bytes(body)
                time.sleep(0.12)
            except Exception as exc:
                log(f"icon {key} not downloaded: {exc}")
                continue
        if key not in icons:
            icons[key] = "data:image/svg+xml;base64," + base64.b64encode(path.read_bytes()).decode()
        by_code[st["code"]] = key
    return {"icons": icons, "sets": by_code}


def export_top_commanders(conn, wanted=(), budget=COMMANDER_FETCH_BUDGET, top_ranked=TOP_RANKED_FOR_COMMANDERS,
                          cache_dir=None, fetch=None, log=print):
    """{card: [[commander, decks, potential], ...]} for the wanted cards, then the most-played ones.
    Cached pages are always used; at most `budget` new pages are fetched per run."""
    cache_dir = cache_dir or edhrec_client.CARD_CACHE_DIR
    ranked = [r[0] for r in conn.execute(
        "SELECT name FROM cards WHERE edhrec_rank IS NOT NULL AND type_line NOT LIKE 'Basic Land%' "
        "ORDER BY edhrec_rank LIMIT ?", (top_ranked,))]
    names = list(dict.fromkeys([w for w in wanted if w] + ranked))
    out, fetched, waiting = {}, 0, 0
    for name in names:
        top, did = edhrec_client.card_commanders(name, cache_dir=cache_dir, fetch=fetch, allow_fetch=fetched < budget)
        fetched += did
        if top is None:
            waiting += 1
        elif top:
            out[name] = [[c["name"], c["decks"], c["potential"]] for c in top]
    log(f"top commanders: {len(out)} cards ({fetched} pages fetched this run, {waiting} still to fetch)")
    return out


def write_lines(path, records):
    """A JSON array with one record per line (easy to diff, still one JSON.parse)."""
    with path.open("w", encoding="utf-8") as f:
        f.write("[\n")
        f.write(",\n".join(json.dumps(r, ensure_ascii=False, separators=(",", ":")) for r in records))
        f.write("\n]\n")


def export_all(out=DEFAULT_OUT, log=print):
    """Write every file the artifact reads into `out`. Returns a one-line summary."""
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    args = argparse.Namespace(out=out)

    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    cards, oracle = export_cards(conn)
    meta = dict(conn.execute("SELECT key, value FROM meta").fetchall())
    commanders = export_commanders()

    write_lines(args.out / "cards.json", cards)
    (args.out / "oracle.json").write_text(json.dumps(oracle, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    (args.out / "commanders.json").write_text(json.dumps(commanders, ensure_ascii=False, separators=(",", ":")),
                                             encoding="utf-8")
    (args.out / "meta.json").write_text(json.dumps({
        "prices_updated": meta.get("updated_at"), "cards": len(cards), "commanders_with_edhrec": len(commanders),
        "fields": ["name", "color_identity", "type", "mana_value", "usd", "usd_max", "edhrec_rank", "flags", "roles",
                   "price_set", "price_rarity"],
        "roles": ROLE_LETTERS,
        "flags": {"game_changer": GAME_CHANGER, "legal": LEGAL, "can_be_commander": CAN_COMMAND, "reserved": RESERVED},
    }, indent=1), encoding="utf-8")
    buckets, sets = export_printings(conn)
    pdir = args.out / "printings"
    pdir.mkdir(exist_ok=True)
    for old in pdir.glob("*.json"):
        old.unlink()
    for b, cards_in in buckets.items():
        (pdir / f"{b}.json").write_text(json.dumps(cards_in, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    trends = export_trends(conn)
    if trends:
        (args.out / "trends.json").write_text(json.dumps(trends, separators=(",", ":")), encoding="utf-8")
        log(f"trends: {len(trends['cards'])} cards x {len(trends['days'])} weekly points")
    wanted = WANTED.read_text(encoding="utf-8").splitlines() if WANTED.exists() else []
    top_cmd = export_top_commanders(conn, wanted=wanted, log=log)
    (args.out / "top_commanders.json").write_text(json.dumps(top_cmd, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    icons = export_set_icons(log=log)
    if icons:
        (args.out / "set_icons.json").write_text(json.dumps(icons, separators=(",", ":")), encoding="utf-8")
        log(f"set icons: {len(icons['icons'])} symbols for {len(icons['sets'])} sets")
    (args.out / "sets.json").write_text(json.dumps(sets, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    log(f"printings/      {sum(f.stat().st_size for f in pdir.glob('*.json')) / 1e6:6.2f} MB in {len(buckets)} files")
    for f in sorted(args.out.glob("*.json")):
        log(f"{f.name:16} {f.stat().st_size / 1e6:6.2f} MB")
    summary = f"{len(cards):,} cards, {len(commanders)} commanders, prices {(meta.get('updated_at') or '?')[:10]}"
    log(f"{summary} -> {args.out}")
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args(argv)
    export_all(args.out)


if __name__ == "__main__":
    main()
