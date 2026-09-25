"""Local card database built from Scryfall's Default Cards bulk file.

One row per Oracle ID (i.e. per card, not per printing), stored in SQLite.
Bulk data is downloaded once and refreshed daily, so no per-card live API
calls are ever needed. Price is the cheapest USD across real printings, so
staples whose default printing has no USD price (Sol Ring, Command Tower) are
never N/A.

Price rules, in order of preference:
  1. cheapest non-foil USD among non-promo, non-digital printings
  2. cheapest non-foil USD among promo printings
  3. cheapest foil/etched USD
The chosen printing is recorded in ``price_source`` and ``price_printing``.

Usage:
    db = card_db.open_db()          # downloads/builds on first use, refreshes daily
    db.get("Sol Ring")              # -> dict with usd, color_identity, ...
"""

import difflib
import gzip
import json
import sqlite3
import time
import urllib.request
from pathlib import Path

API = "https://api.scryfall.com"
HEADERS = {"User-Agent": "commander-deck-builder/0.1", "Accept": "application/json"}
DATA_DIR = Path(__file__).parent / "data" / "cache"
DB_NAME = "cards.sqlite"
BULK_NAME = "default-cards.jsonl.gz"
MAX_AGE_HOURS = 24
CHUNK = 1024 * 1024
WUBRG = "WUBRG"

# Layouts that are not real cards (no place in a Commander deck).
EXCLUDED_LAYOUTS = {
    "token",
    "double_faced_token",
    "emblem",
    "art_series",
    "planar",
    "scheme",
    "vanguard",
    "augment",
    "host",
}
EXCLUDED_SET_TYPES = {"memorabilia", "token"}

SCHEMA = """
CREATE TABLE cards (
    oracle_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    name_lower TEXT NOT NULL,
    front_name_lower TEXT NOT NULL,
    type_line TEXT NOT NULL,
    oracle_text TEXT NOT NULL,
    color_identity TEXT NOT NULL,   -- WUBRG order, '' for colorless
    cmc REAL NOT NULL,
    edhrec_rank INTEGER,
    legal_commander INTEGER NOT NULL,
    usd REAL,
    price_source TEXT,              -- non_promo | promo | foil
    price_printing TEXT             -- e.g. "cmm #1"
);
CREATE INDEX idx_cards_name ON cards(name_lower);
CREATE INDEX idx_cards_front ON cards(front_name_lower);
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
"""


class BulkDataError(Exception):
    """Bulk data could not be fetched or parsed."""


# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------


def fetch_bulk_metadata():
    """Return Scryfall's ``default_cards`` bulk metadata."""
    req = urllib.request.Request(f"{API}/bulk-data/default-cards", headers=HEADERS)
    with urllib.request.urlopen(req) as resp:
        return json.load(resp)


def bulk_download_url(metadata):
    """Bulk file URL. Scryfall now publishes ``jsonl_download_uri``; old key is a fallback."""
    url = metadata.get("jsonl_download_uri") or metadata.get("download_uri")
    if not url:
        raise BulkDataError(
            f"Bulk metadata has no download URL. Keys: {sorted(metadata.keys())}"
        )
    return url


def download_bulk(url, dest):
    """Stream the bulk file to ``dest`` without loading it into memory."""
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    req = urllib.request.Request(url, headers={"User-Agent": HEADERS["User-Agent"]})
    with urllib.request.urlopen(req) as resp, open(tmp, "wb") as out:
        while chunk := resp.read(CHUNK):
            out.write(chunk)
    tmp.replace(dest)


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------


def _oracle_id(card):
    oid = card.get("oracle_id")
    if oid:
        return oid
    faces = card.get("card_faces") or []
    return faces[0].get("oracle_id") if faces else None


def _oracle_text(card):
    if card.get("oracle_text"):
        return card["oracle_text"]
    return "\n".join(f.get("oracle_text", "") for f in card.get("card_faces") or [])


def _type_line(card):
    if card.get("type_line"):
        return card["type_line"]
    faces = card.get("card_faces") or []
    return " // ".join(f.get("type_line", "") for f in faces)


def _color_identity(card):
    colors = set(card.get("color_identity") or [])
    return "".join(c for c in WUBRG if c in colors)


def _price_candidates(card):
    """Yield (usd, source) for every USD price this printing offers."""
    prices = card.get("prices") or {}
    is_promo = bool(card.get("promo"))
    if prices.get("usd"):
        yield float(prices["usd"]), "promo" if is_promo else "non_promo"
    for key in ("usd_foil", "usd_etched"):
        if prices.get(key):
            yield float(prices[key]), "foil"


_SOURCE_PRIORITY = {"non_promo": 0, "promo": 1, "foil": 2}


def _better_price(new, current):
    """True if ``new`` (usd, source) should replace ``current``."""
    if current is None:
        return True
    new_key = (_SOURCE_PRIORITY[new[1]], new[0])
    cur_key = (_SOURCE_PRIORITY[current[1]], current[0])
    return new_key < cur_key


def _is_real_printing(card):
    if card.get("layout") in EXCLUDED_LAYOUTS:
        return False
    if card.get("set_type") in EXCLUDED_SET_TYPES:
        return False
    return not card.get("digital", False)


def aggregate_cards(lines):
    """Collapse printings (JSONL lines) to one dict per Oracle ID."""
    cards = {}
    for line in lines:
        line = line.strip()
        if not line:
            continue
        card = json.loads(line)
        oid = _oracle_id(card)
        if not oid or not _is_real_printing(card):
            continue

        row = cards.get(oid)
        if row is None:
            name = card["name"]
            row = cards[oid] = {
                "oracle_id": oid,
                "name": name,
                "name_lower": name.lower(),
                "front_name_lower": name.split(" // ")[0].lower(),
                "type_line": _type_line(card),
                "oracle_text": _oracle_text(card),
                "color_identity": _color_identity(card),
                "cmc": float(card.get("cmc") or 0),
                "edhrec_rank": card.get("edhrec_rank"),
                "legal_commander": int(
                    (card.get("legalities") or {}).get("commander") in ("legal", "restricted")
                ),
                "usd": None,
                "price_source": None,
                "price_printing": None,
            }

        # Rank and legality are card-level; any printing carrying them will do.
        if row["edhrec_rank"] is None and card.get("edhrec_rank") is not None:
            row["edhrec_rank"] = card["edhrec_rank"]

        current = (row["usd"], row["price_source"]) if row["usd"] is not None else None
        for candidate in _price_candidates(card):
            if _better_price(candidate, current):
                current = candidate
                row["usd"], row["price_source"] = candidate
                row["price_printing"] = f"{card.get('set', '?')} #{card.get('collector_number', '?')}"
    return cards


def build_db(bulk_path, db_path, updated_at=""):
    """Stream a bulk .jsonl.gz into a fresh SQLite database (replacing any old one)."""
    db_path = Path(db_path)
    tmp_path = db_path.with_suffix(".building")
    tmp_path.unlink(missing_ok=True)
    try:
        with gzip.open(bulk_path, "rt", encoding="utf-8") as lines:
            cards = aggregate_cards(lines)
    except (OSError, EOFError, json.JSONDecodeError) as exc:
        raise BulkDataError(f"Could not read bulk file {bulk_path}: {exc}") from exc
    if not cards:
        raise BulkDataError("Bulk file produced 0 cards (Scryfall format may have changed).")

    conn = sqlite3.connect(tmp_path)
    try:
        conn.executescript(SCHEMA)
        columns = [
            "oracle_id", "name", "name_lower", "front_name_lower", "type_line",
            "oracle_text", "color_identity", "cmc", "edhrec_rank", "legal_commander",
            "usd", "price_source", "price_printing",
        ]  # fmt: skip
        conn.executemany(
            f"INSERT INTO cards ({', '.join(columns)}) VALUES ({', '.join('?' * len(columns))})",
            [tuple(row[c] for c in columns) for row in cards.values()],
        )
        meta = {
            "updated_at": updated_at,
            "built_at": str(time.time()),
            "card_count": str(len(cards)),
        }
        conn.executemany("INSERT INTO meta VALUES (?, ?)", meta.items())
        conn.commit()
    finally:
        conn.close()
    tmp_path.replace(db_path)


# ---------------------------------------------------------------------------
# Query
# ---------------------------------------------------------------------------


def identity_fits(card_identity, allowed_identity):
    """True if every color in ``card_identity`` is in ``allowed_identity``."""
    return set(card_identity) <= set(allowed_identity)


class CardDB:
    """Read-only access to the local card table."""

    def __init__(self, db_path):
        self.path = Path(db_path)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row

    def close(self):
        self.conn.close()

    def meta(self):
        return dict(self.conn.execute("SELECT key, value FROM meta").fetchall())

    def count(self):
        return self.conn.execute("SELECT COUNT(*) FROM cards").fetchone()[0]

    def get(self, name):
        """Exact card by name (case-insensitive; front face of a DFC also works)."""
        key = name.lower()
        row = self.conn.execute(
            "SELECT * FROM cards WHERE name_lower = ? OR front_name_lower = ? "
            "ORDER BY (name_lower = ?) DESC LIMIT 1",
            (key, key, key),
        ).fetchone()
        return dict(row) if row else None

    def get_many(self, names):
        """``{requested_name: card_dict}`` for the names found; unknown names are omitted."""
        found = {}
        for name in dict.fromkeys(names):
            card = self.get(name)
            if card:
                found[name] = card
        return found

    def find_name(self, query, cutoff=0.6):
        """Best-effort card-name match for a sloppy query. Returns the exact name or None."""
        exact = self.get(query)
        if exact:
            return exact["name"]
        names = [r[0] for r in self.conn.execute("SELECT name FROM cards")]
        lowered = {n.lower(): n for n in names}
        # Substring hit on a unique card beats fuzzy matching ("muldrotha" -> full name).
        contains = [n for low, n in lowered.items() if query.lower() in low]
        if len(contains) == 1:
            return contains[0]
        close = difflib.get_close_matches(query.lower(), lowered, n=1, cutoff=cutoff)
        return lowered[close[0]] if close else None

    def candidates(self, color_identity, *, max_price=None, commander_legal=True, limit=None):
        """Cards inside ``color_identity`` (e.g. "BGU"), most popular first."""
        sql = "SELECT * FROM cards WHERE 1=1"
        params = []
        if commander_legal:
            sql += " AND legal_commander = 1"
        if max_price is not None:
            sql += " AND usd IS NOT NULL AND usd <= ?"
            params.append(max_price)
        sql += " ORDER BY edhrec_rank IS NULL, edhrec_rank"
        rows = []
        for row in self.conn.execute(sql, params):
            if identity_fits(row["color_identity"], color_identity):
                rows.append(dict(row))
                if limit and len(rows) >= limit:
                    break
        return rows


# ---------------------------------------------------------------------------
# Freshness
# ---------------------------------------------------------------------------


def _db_age_hours(db_path):
    return (time.time() - Path(db_path).stat().st_mtime) / 3600


def ensure_db(data_dir=DATA_DIR, max_age_hours=MAX_AGE_HOURS, refresh=False, log=print):
    """Return the path to an up-to-date database, downloading/building only if needed.

    - Younger than ``max_age_hours``: used as is (no network).
    - Older: one metadata request; if Scryfall's ``updated_at`` matches the
      database, it is just touched. Otherwise the bulk file is re-downloaded.
    """
    data_dir = Path(data_dir)
    db_path = data_dir / DB_NAME
    bulk_path = data_dir / BULK_NAME

    if db_path.exists() and not refresh and _db_age_hours(db_path) < max_age_hours:
        return db_path

    try:
        metadata = fetch_bulk_metadata()
    except OSError as exc:
        if db_path.exists():
            log(f"Warning: could not check Scryfall ({exc}); using existing card data.")
            return db_path
        raise BulkDataError(f"Could not reach Scryfall and no local card data: {exc}") from exc

    updated_at = metadata.get("updated_at", "")
    if db_path.exists() and not refresh:
        db = CardDB(db_path)
        try:
            same = db.meta().get("updated_at") == updated_at
        finally:
            db.close()
        if same:
            db_path.touch()
            return db_path

    log(f"Downloading Scryfall bulk data (~{metadata.get('compressed_size', 0) // 1_000_000} MB)...")
    download_bulk(bulk_download_url(metadata), bulk_path)
    log("Building local card database...")
    build_db(bulk_path, db_path, updated_at=updated_at)
    return db_path


def open_db(**kwargs):
    """``ensure_db`` then open it."""
    return CardDB(ensure_db(**kwargs))
