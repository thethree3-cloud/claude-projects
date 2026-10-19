"""Binder page photo -> the cards on it, checked against the local card database.

Claude only reads the title bars. Every name it returns goes through
``CardDB``: an exact hit is kept, a near miss is corrected to the real card
name (and flagged), and anything else is reported as unknown, never guessed.

Usage:
    python scan_binder.py page1.jpg page2.jpg
    python scan_binder.py ~/Downloads/magic/*.jpeg --truth fixtures/binder_truth.json
    python scan_binder.py page1.jpg --json
"""

import argparse
import base64
import io
import json
import os
import sys
from pathlib import Path

import anthropic
from dotenv import load_dotenv
from PIL import Image, ImageOps
from pydantic import BaseModel, ValidationError

import card_db

MODEL = "claude-opus-5-5"
MAX_EDGE = 2576  # largest long edge the model uses; bigger photos are downscaled
JPEG_QUALITY = 90
ENV_PATH = Path(__file__).resolve().parents[2] / ".env"

PROMPT = """This photo shows one page of a binder of Magic: The Gathering cards, laid out in a grid.

List every card on the page in reading order: left to right, top to bottom. Slot 1 is the top-left pocket.
Copy each card's name exactly as printed in its title bar. Do not guess from the artwork.
If a title is hard to read (glare, angle, foil), give your best reading and set legible to false.
Skip cards that only peek in from the edge of the photo and are not in this page's pockets."""


class ScanError(Exception):
    """The photo could not be read."""


class CardSlot(BaseModel):
    slot: int
    name: str
    legible: bool


class BinderPage(BaseModel):
    cards: list[CardSlot]


# JSON schema for structured output (output_config.format); the reply is then
# validated with BinderPage.
PAGE_SCHEMA = {
    "type": "object",
    "properties": {
        "cards": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "slot": {"type": "integer"},
                    "name": {"type": "string"},
                    "legible": {"type": "boolean"},
                },
                "required": ["slot", "name", "legible"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["cards"],
    "additionalProperties": False,
}


# ---------------------------------------------------------------------------
# Image
# ---------------------------------------------------------------------------


def prepare_image(path, max_edge=MAX_EDGE):
    """Upright, downscaled JPEG as base64. Phone photos carry rotation in EXIF."""
    try:
        img = Image.open(path)
    except (OSError, ValueError) as exc:
        raise ScanError(f"Could not open image {path}: {exc}") from exc
    img = ImageOps.exif_transpose(img).convert("RGB")
    img.thumbnail((max_edge, max_edge))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=JPEG_QUALITY)
    return base64.standard_b64encode(buf.getvalue()).decode("ascii")


# ---------------------------------------------------------------------------
# Read (Claude)
# ---------------------------------------------------------------------------


def make_client():
    load_dotenv(ENV_PATH)
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise ScanError(f"ANTHROPIC_API_KEY is not set (looked in the environment and {ENV_PATH}).")
    return anthropic.Anthropic()


def read_names(image_path, client, model=MODEL):
    """Ask Claude for the card names on one page -> list of ``CardSlot``."""
    image_b64 = prepare_image(image_path)
    try:
        response = client.beta.messages.create(
            model=model,
            max_tokens=4000,
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            output_config={"effort": "low", "format": {"type": "json_schema", "schema": PAGE_SCHEMA}},
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": image_b64}},
                    {"type": "text", "text": PROMPT},
                ],
            }],
        )
    except anthropic.APIConnectionError as exc:
        raise ScanError(f"Could not reach the Claude API: {exc}") from exc
    except anthropic.APIStatusError as exc:
        raise ScanError(f"Claude API error {exc.status_code}: {exc.message}") from exc

    if response.stop_reason == "refusal":
        raise ScanError(f"Claude declined to read {image_path}.")
    text = "".join(b.text for b in response.content if b.type == "text")
    try:
        if response.stop_reason == "max_tokens":
            raise ValueError("answer cut off")
        page = BinderPage.model_validate_json(text)
    except (ValueError, ValidationError) as exc:
        raise ScanError(f"Claude's answer for {image_path} was cut off or unreadable: {exc}") from exc
    return sorted(page.cards, key=lambda c: c.slot)


# ---------------------------------------------------------------------------
# Check (card database)
# ---------------------------------------------------------------------------


def match_names(slots, db):
    """Check each read name against the card database.

    status: ``exact`` (name is a real card), ``corrected`` (near miss fixed
    to the real name), or ``unknown`` (no card close enough; never guessed).
    """
    results = []
    for slot in slots:
        card = db.get(slot.name)
        if card:
            status, name = "exact", card["name"]
        else:
            name = db.find_name(slot.name)
            status = "corrected" if name else "unknown"
        results.append({
            "slot": slot.slot,
            "read": slot.name,
            "name": name,
            "status": status,
            "legible": slot.legible,
        })
    return results


def scan_page(image_path, db, client, model=MODEL):
    return {"image": Path(image_path).name, "cards": match_names(read_names(image_path, client, model), db)}


# ---------------------------------------------------------------------------
# Accuracy against a hand-checked answer key
# ---------------------------------------------------------------------------


def score_page(cards, expected):
    """Compare scanned cards to the expected names (slot order). Name match only."""
    got = [c["name"] for c in cards]
    misses = []
    for i, want in enumerate(expected):
        have = got[i] if i < len(got) else None
        if have != want:
            misses.append({"slot": i + 1, "expected": want, "got": have})
    extra = got[len(expected):]
    correct = len(expected) - len(misses)
    return {"correct": correct, "total": len(expected), "misses": misses, "extra": extra}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


STATUS_MARK = {"exact": "", "corrected": "  (corrected)", "unknown": "  ?? not a known card"}


def print_page(page, score=None):
    print(f"\n{page['image']}")
    for c in page["cards"]:
        shown = c["name"] or c["read"]
        note = STATUS_MARK[c["status"]]
        if c["status"] == "corrected":
            note = f"  (read as '{c['read']}')"
        if not c["legible"]:
            note += "  [hard to read]"
        print(f"  {c['slot']:>2}. {shown}{note}")
    if score:
        print(f"  accuracy: {score['correct']}/{score['total']}")
        for m in score["misses"]:
            print(f"    slot {m['slot']}: expected {m['expected']!r}, got {m['got']!r}")
        for name in score["extra"]:
            print(f"    extra card not on the page: {name!r}")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Read the cards on binder page photos.")
    parser.add_argument("images", nargs="+", type=Path)
    parser.add_argument("--truth", type=Path, help="JSON answer key: {image file name: [names in slot order]}")
    parser.add_argument("--model", default=MODEL)
    parser.add_argument("--json", action="store_true", help="print JSON instead of a list")
    args = parser.parse_args(argv)

    truth = json.loads(args.truth.read_text()) if args.truth else {}
    try:
        client = make_client()
        db = card_db.open_db()
    except (ScanError, card_db.BulkDataError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    pages, correct, total = [], 0, 0
    for path in args.images:
        try:
            page = scan_page(path, db, client, args.model)
        except ScanError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            continue
        score = score_page(page["cards"], truth[page["image"]]) if page["image"] in truth else None
        if score:
            page["score"] = score
            correct += score["correct"]
            total += score["total"]
        pages.append(page)
        if not args.json:
            print_page(page, score)

    if args.json:
        print(json.dumps(pages, indent=2))
    elif total:
        print(f"\nOverall: {correct}/{total} cards read correctly ({correct / total:.0%})")
    return 0 if pages else 1


if __name__ == "__main__":
    sys.exit(main())
