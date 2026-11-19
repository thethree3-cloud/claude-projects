"""Local card database built from Scryfall's Default Cards bulk file.

One row per Oracle ID (i.e. per card, not per printing), stored in SQLite.
Bulk data is downloaded once and refreshed daily, so no per-card live API
calls are ever needed. Price is the cheapest USD across real printings, so
staples whose default printing has no USD price (Sol Ring, Command Tower) are
never N/A.

Game Changers come from Scryfall's own ``game_changer`` flag (the official
WotC list used by the Commander brackets), so no hand-maintained list.

Price rules, in order of preference:
  1. cheapest non-foil USD among non-promo, non-digital printings
  2. cheapest non-foil USD among promo printings
  3. cheapest foil/etched USD
The chosen printing is recorded in ``price_source`` and ``price_printing``,
and its Scryfall image links (``image_url``, plus ``image_url_back`` for
two-faced cards) are stored too, so the picture matches the price shown.

Usage:
    db = card_db.open_db()          # downloads/builds on first use, refreshes daily
    db.get("Sol Ring")              # -> dict with usd, color_identity, ...
"""

import difflib
import gzip
import json
import re
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
SCHEMA_VERSION = "4"  # bump when the cards table changes; ensure_db rebuilds locally

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
    game_changer INTEGER NOT NULL,  -- on the official WotC Game Changers list
    usd REAL,
    price_source TEXT,              -- non_promo | promo | foil
    price_printing TEXT,            -- e.g. "cmm #1"
    image_url TEXT,                 -- Scryfall "normal" image of that printing
    image_url_back TEXT             -- back face, two-faced cards only
);
CREATE INDEX idx_cards_name ON cards(name_lower);
CREATE INDEX idx_cards_front ON cards(front_name_lower);
CREATE TABLE printings (            -- every real printing, for the card page
    oracle_id TEXT NOT NULL,
    set_code TEXT NOT NULL,
    set_name TEXT,
    collector_number TEXT,
    released_at TEXT,               -- YYYY-MM-DD
    rarity TEXT,
    artist TEXT,
    finishes TEXT,                  -- e.g. "nonfoil,foil"
    treatment TEXT,                 -- e.g. "borderless, showcase" ('' for a plain printing)
    promo INTEGER NOT NULL,
    usd REAL,
    usd_foil REAL,
    usd_etched REAL,
    image_url TEXT,
    image_url_back TEXT,
    scryfall_url TEXT
);
CREATE INDEX idx_printings_oracle ON printings(oracle_id);
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
"""

PRINTING_COLUMNS = [
    "oracle_id", "set_code", "set_name", "collector_number", "released_at", "rarity", "artist",
    "finishes", "treatment", "promo", "usd", "usd_foil", "usd_etched", "image_url", "image_url_back",
    "scryfall_url",
]  # fmt: skip


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


def _images(card):
    """(front, back) Scryfall "normal" image links. Back only for two-faced cards
    (transform, modal_dfc, reversible); split / adventure / flip cards are one image."""
    if card.get("image_uris"):
        return card["image_uris"].get("normal"), None
    faces = [f.get("image_uris") or {} for f in card.get("card_faces") or []]
    if faces and faces[0].get("normal"):
        return faces[0]["normal"], faces[1].get("normal") if len(faces) > 1 else None
    return None, None


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


def _price(value):
    return float(value) if value else None


def _treatment(card):
    """Short label for how a printing looks: "borderless, showcase", "full art"..."""
    parts = []
    if card.get("border_color") == "borderless":
        parts.append("borderless")
    for effect in card.get("frame_effects") or []:
        if effect in ("showcase", "extendedart", "etched", "inverted", "shatteredglass"):
            parts.append("extended art" if effect == "extendedart" else effect)
    if card.get("full_art") and "borderless" not in parts:
        parts.append("full art")
    if card.get("textless"):
        parts.append("textless")
    return ", ".join(dict.fromkeys(parts))


def printing_row(card, oid):
    """One ``printings`` row for a Scryfall printing."""
    prices = card.get("prices") or {}
    front, back = _images(card)
    return {
        "oracle_id": oid,
        "set_code": card.get("set", "?"),
        "set_name": card.get("set_name"),
        "collector_number": card.get("collector_number"),
        "released_at": card.get("released_at"),
        "rarity": card.get("rarity"),
        "artist": card.get("artist") or ((card.get("card_faces") or [{}])[0].get("artist")),
        "finishes": ",".join(card.get("finishes") or []),
        "treatment": _treatment(card),
        "promo": int(bool(card.get("promo"))),
        "usd": _price(prices.get("usd")),
        "usd_foil": _price(prices.get("usd_foil")),
        "usd_etched": _price(prices.get("usd_etched")),
        "image_url": front,
        "image_url_back": back,
        "scryfall_url": (card.get("scryfall_uri") or "").split("?")[0] or None,
    }


def _is_real_printing(card):
    if card.get("layout") in EXCLUDED_LAYOUTS:
        return False
    if card.get("set_type") in EXCLUDED_SET_TYPES:
        return False
    return not card.get("digital", False)


def aggregate_cards(lines, printings=None):
    """Collapse printings (JSONL lines) to one dict per Oracle ID.

    If ``printings`` is a list, a ``printing_row`` for every real printing is
    appended to it (for the card page)."""
    cards = {}
    for line in lines:
        line = line.strip()
        if not line:
            continue
        card = json.loads(line)
        oid = _oracle_id(card)
        if not oid or not _is_real_printing(card):
            continue
        if printings is not None:
            printings.append(printing_row(card, oid))

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
                "game_changer": int(bool(card.get("game_changer"))),
                "usd": None,
                "price_source": None,
                "price_printing": None,
                "image_url": None,
                "image_url_back": None,
            }

        # Rank and legality are card-level; any printing carrying them will do.
        if row["edhrec_rank"] is None and card.get("edhrec_rank") is not None:
            row["edhrec_rank"] = card["edhrec_rank"]
        if card.get("game_changer"):
            row["game_changer"] = 1

        if row["image_url"] is None:
            row["image_url"], row["image_url_back"] = _images(card)  # until a priced printing wins
        current = (row["usd"], row["price_source"]) if row["usd"] is not None else None
        for candidate in _price_candidates(card):
            if _better_price(candidate, current):
                current = candidate
                row["usd"], row["price_source"] = candidate
                row["price_printing"] = f"{card.get('set', '?')} #{card.get('collector_number', '?')}"
                front, back = _images(card)
                if front:
                    row["image_url"], row["image_url_back"] = front, back
    return cards


def build_db(bulk_path, db_path, updated_at=""):
    """Stream a bulk .jsonl.gz into a fresh SQLite database (replacing any old one)."""
    db_path = Path(db_path)
    tmp_path = db_path.with_suffix(".building")
    tmp_path.unlink(missing_ok=True)
    try:
        printings = []
        with gzip.open(bulk_path, "rt", encoding="utf-8") as lines:
            cards = aggregate_cards(lines, printings)
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
            "game_changer", "usd", "price_source", "price_printing", "image_url", "image_url_back",
        ]  # fmt: skip
        conn.executemany(
            f"INSERT INTO cards ({', '.join(columns)}) VALUES ({', '.join('?' * len(columns))})",
            [tuple(row[c] for c in columns) for row in cards.values()],
        )
        conn.executemany(
            f"INSERT INTO printings ({', '.join(PRINTING_COLUMNS)}) VALUES ({', '.join('?' * len(PRINTING_COLUMNS))})",
            [tuple(p[c] for c in PRINTING_COLUMNS) for p in printings],
        )
        meta = {
            "updated_at": updated_at,
            "built_at": str(time.time()),
            "card_count": str(len(cards)),
            "schema_version": SCHEMA_VERSION,
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


def can_be_commander(card):
    """Legendary creature, a legendary card that is a creature off the battlefield
    (Grist, the Hunger Tide), or one whose text says it can be your commander."""
    front = card["type_line"].split(" // ")[0]
    text = card["oracle_text"]
    if "can be your commander" in text:
        return True
    return "Legendary" in front and ("Creature" in front or "creature in addition to its other types" in text)


# ---------------------------------------------------------------------------
# Two commanders (partners, backgrounds, Doctor's companion)
# ---------------------------------------------------------------------------

_PARTNER_WITH = re.compile(r"^Partner with (.+?)\s*(?:\(|$)")
_PARTNER_VARIANT = re.compile(r"^Partner\s*[—-]\s*(.+?)\s*(?:\(|$)")
_PARTNER_PLAIN = re.compile(r"^Partner\s*(?:\(|$)")


def pairing(card):
    """How a card can share the command zone, as a set of tags:
    ``("partner",)``, ``("with", name)``, ``("variant", "friends forever")``,
    ``("wants_background",)``, ``("background",)``, ``("companion",)``, ``("doctor",)``.
    """
    tags = set()
    for line in card["oracle_text"].split("\n"):
        line = line.strip()
        if m := _PARTNER_WITH.match(line):
            tags.add(("with", m.group(1)))
        elif m := _PARTNER_VARIANT.match(line):
            tags.add(("variant", m.group(1).lower()))
        elif _PARTNER_PLAIN.match(line):
            tags.add(("partner",))
        elif line.startswith("Choose a Background"):
            tags.add(("wants_background",))
        elif re.match(r"Doctor.s companion", line):
            tags.add(("companion",))
    front = card["type_line"].split(" // ")[0]
    kinds, _, subtypes = front.partition("—")
    if "Legendary" in kinds and "Enchantment" in kinds and "Background" in subtypes.split():
        tags.add(("background",))
    if "Legendary" in kinds and "Creature" in kinds and subtypes.split() == ["Time", "Lord", "Doctor"]:
        tags.add(("doctor",))
    return tags


def _names(card):
    return {card["name"], card["name"].split(" // ")[0]}


def pair_problem(a, b):
    """Why ``a`` and ``b`` can't be your two commanders, or None if they can."""
    if a["name"] == b["name"]:
        return "the same card can't be both commanders"
    for card in (a, b):
        if not card["legal_commander"]:
            return f"{card['name']} is banned in Commander"
    ta, tb = pairing(a), pairing(b)
    if ta & tb & {("partner",)}:
        return None
    if any(("with", n) in ta for n in _names(b)) and any(("with", n) in tb for n in _names(a)):
        return None
    if {t for t in ta if t[0] == "variant"} & {t for t in tb if t[0] == "variant"}:
        return None
    for x, y, tx, ty in ((a, b, ta, tb), (b, a, tb, ta)):
        if ("wants_background",) in tx and ("background",) in ty and can_be_commander(x):
            return None
        if ("companion",) in tx and ("doctor",) in ty and can_be_commander(x):
            return None
    return f"{a['name']} and {b['name']} can't be commanders together (no matching partner or background ability)"


def can_lead(card):
    """Can this card be one of the commanders (alone, or as half of a pair)?"""
    return card["legal_commander"] and (can_be_commander(card) or ("background",) in pairing(card))


def commander_members(commander):
    """The real card rows behind a commander (two for a pair)."""
    return commander.get("members") or [commander]


def combine_commanders(cards):
    """One commander dict for one or two cards. A pair gets ``members``, the
    combined color identity, a "A + B" display name and both rules texts."""
    if len(cards) == 1:
        return cards[0]
    identity = "".join(c for c in "WUBRG" if any(c in card["color_identity"] for card in cards))
    prices = [card["usd"] for card in cards]
    return {
        **cards[0],
        "name": " + ".join(card["name"] for card in cards),
        "color_identity": identity,
        "oracle_text": "\n\n".join(f"{card['name']}: {card['oracle_text']}" for card in cards),
        "usd": None if None in prices else round(sum(prices), 2),
        "legal_commander": int(all(card["legal_commander"] for card in cards)),
        "members": list(cards),
    }


def _norm(text):
    # Punctuation counts as a space: "ur dragon" finds "The Ur-Dragon".
    return " ".join(re.sub(r"[,'\-]", " ", text.lower()).split())


def best_match(query, names, cutoff=0.6):
    """Best name in ``names`` (ordered most-played first) for a sloppy query, or None.

    Order: exact name -> name starts with the query (a leading "The" is
    skipped) -> a word in the name
    starts with it -> substring -> typo (full or short name). Ties go to the
    earlier name in ``names``.
    """
    q = _norm(query)
    if not q:
        return None
    lowered = {n.lower(): n for n in names}
    if query.lower().strip() in lowered:
        return lowered[query.lower().strip()]
    fronts = {_norm(n.split(" // ")[0]): n for n in names}
    if q in fronts:
        return fronts[q]
    normed = [(_norm(n), n) for n in names]
    tests = (
        lambda low: low.startswith(q) or low.removeprefix("the ").startswith(q),  # "gitrog" -> The Gitrog Monster
        lambda low: (" " + low).find(" " + q) >= 0,  # a word starts with the query
        lambda low: q in low,
    )
    for test in tests:
        hits = [n for low, n in normed if test(low)]
        if hits:
            return hits[0]
    # Typos: compare against full names and short names ("Muldrotha" from
    # "Muldrotha, the Gravetide"), since people usually type the short one.
    keys = dict(lowered)
    for n in names:
        keys.setdefault(n.lower().split(",")[0].split(" // ")[0], n)
    close = difflib.get_close_matches(q, keys, n=1, cutoff=cutoff)
    return keys[close[0]] if close else None


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

    def commander_names(self, popularity=None):
        """Every card that can lead a Commander deck, most-played first.

        With ``popularity`` ({name: decks led}, e.g. from EDHREC), cards are
        ordered by how often they lead a deck; unranked ones follow."""
        rows = self.conn.execute(
            "SELECT name, type_line, oracle_text FROM cards "
            "WHERE legal_commander = 1 AND (type_line LIKE '%Legendary%' "
            "OR oracle_text LIKE '%can be your commander%') "
            "ORDER BY edhrec_rank IS NULL, edhrec_rank, name"
        )
        names = [r["name"] for r in rows if can_be_commander(r)]
        if popularity:
            def decks(name):
                return popularity.get(name) or popularity.get(name.split(" // ")[0]) or 0
            names.sort(key=lambda n: -decks(n))  # stable: unranked keep card-popularity order
        return names

    def find_commander(self, query, cutoff=0.6, popularity=None):
        """Like ``find_name``, but only cards that can be a commander are considered,
        so "esika" is Esika, God of the Tree (not the fuzzy hit "Amnesia"). See
        ``best_match`` for the order. Returns the exact name or None.

        ``popularity`` ({name: decks led}) breaks ties by how often a card is the
        *commander*; without it, ties go to how often it's played at all, so
        "krenko" would be Tin Street Kingpin rather than Mob Boss."""
        return best_match(query, self.commander_names(popularity), cutoff)

    def partner_names(self, card):
        """Cards that can be ``card``'s second commander, most-played first."""
        if not pairing(card):
            return []
        rows = self.conn.execute(
            "SELECT * FROM cards WHERE legal_commander = 1 AND type_line LIKE '%Legendary%' "
            "ORDER BY edhrec_rank IS NULL, edhrec_rank, name"
        )
        return [r["name"] for r in rows if pairing(r) and pair_problem(card, r) is None]

    def find_partner(self, card, query, cutoff=0.6):
        """Best match for ``query`` among the cards that can pair with ``card``."""
        return best_match(query, self.partner_names(card), cutoff)

    def printings(self, name):
        """Every real printing of a card (newest first), as dicts; [] if unknown."""
        card = self.get(name)
        if card is None:
            return []
        rows = self.conn.execute(
            "SELECT * FROM printings WHERE oracle_id = ? "
            "ORDER BY released_at DESC, set_code, collector_number",
            (card["oracle_id"],),
        )
        return [dict(r) for r in rows]

    def game_changers(self):
        """Names of every card on the official Game Changers list, A-Z."""
        rows = self.conn.execute("SELECT name FROM cards WHERE game_changer = 1 ORDER BY name")
        return [r[0] for r in rows]

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


def _schema_version(db_path):
    db = CardDB(db_path)
    try:
        return db.meta().get("schema_version")
    finally:
        db.close()


def ensure_db(data_dir=DATA_DIR, max_age_hours=MAX_AGE_HOURS, refresh=False, log=print):
    """Return the path to an up-to-date database, downloading/building only if needed.

    - Younger than ``max_age_hours``: used as is (no network).
    - Older: one metadata request; if Scryfall's ``updated_at`` matches the
      database, it is just touched. Otherwise the bulk file is re-downloaded.
    """
    data_dir = Path(data_dir)
    db_path = data_dir / DB_NAME
    bulk_path = data_dir / BULK_NAME

    if db_path.exists() and bulk_path.exists() and _schema_version(db_path) != SCHEMA_VERSION:
        log("Card database format changed; rebuilding from the cached bulk file...")
        db = CardDB(db_path)
        try:
            updated_at = db.meta().get("updated_at", "")
        finally:
            db.close()
        build_db(bulk_path, db_path, updated_at=updated_at)
        refresh_check = True  # the rebuild reset the file age; still ask Scryfall
    else:
        refresh_check = False

    if db_path.exists() and not refresh and not refresh_check and _db_age_hours(db_path) < max_age_hours:
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
