"""Thin Python client for the Open Scripture API (https://openscriptureapi.org).

This is the project's single web dependency. Everything else the scripture
study agent uses (the converted PDF/EPUB corpus, the verse -> passage index)
lives locally. See README.md for the project's scope.

The API is free, public, read-only, and needs no key. It serves Gospel
Library data: the standard works with footnotes, the study helps (Topical
Guide, Bible Dictionary, Triple Combination Index, Joseph Smith
Translation), General Conference talks (1971-present), plus endpoints that
parse a reference string and detect references inside free text.

Design notes
------------
- Every function maps to exactly one documented endpoint, returns the parsed
  JSON, and does no interpretation of its own. Grounding lives here: if the
  API didn't return it, the agent doesn't get it.
- `resolve_reference` is the validation gate. Call it first on any
  user-supplied reference; a typo comes back with ``valid: False`` instead
  of a guess.
- `section_heading` is a convenience wrapper: it pulls the "introduction"
  augmentation off a Doctrine and Covenants chapter, which carries the date
  and place the revelation was received -- the key used later to match
  Joseph Smith Papers documents in the local corpus.
"""

from __future__ import annotations

import re

import requests

# Base URLs. The scriptures API encodes version/denomination/language in the
# path; the study-helps and conference APIs use their own prefixes.
SCRIPTURES_BASE = "https://openscriptureapi.org/api/scriptures/v1/lds/en"
STUDY_HELPS_BASE = "https://openscriptureapi.org/api/study-helps/v1/lds/en"
CONFERENCE_BASE = "https://openscriptureapi.org/api/conference/v1/lds/en"
COME_FOLLOW_ME_BASE = "https://openscriptureapi.org/api/manuals/v1/lds/en"

DEFAULT_TIMEOUT = 20  # seconds

_session = requests.Session()
_session.headers.update({"User-Agent": "scripture-study-agent/0.1 (personal study tool)"})


class ScriptureAPIError(RuntimeError):
    """Raised when the API returns an error payload or a non-2xx status."""


def _get(url: str, params: dict | None = None) -> dict:
    resp = _session.get(url, params=params, timeout=DEFAULT_TIMEOUT)
    return _parse(resp)


def _post(url: str, json_body: dict) -> dict:
    resp = _session.post(url, json=json_body, timeout=DEFAULT_TIMEOUT)
    return _parse(resp)


def _parse(resp: requests.Response) -> dict:
    try:
        data = resp.json()
    except ValueError:
        raise ScriptureAPIError(
            f"{resp.request.method} {resp.url} -> {resp.status_code}, non-JSON body"
        )
    # The API returns 200 with an {"error": "..."} body for bad references,
    # so check the payload as well as the status code.
    if isinstance(data, dict) and "error" in data:
        raise ScriptureAPIError(f"{resp.url} -> {data['error']}")
    if not resp.ok:
        raise ScriptureAPIError(f"{resp.request.method} {resp.url} -> {resp.status_code}")
    return data


# --------------------------------------------------------------------------
# Reference parsing / detection
# --------------------------------------------------------------------------

def resolve_reference(reference: str) -> dict:
    """Parse and validate a plain-text reference without fetching verse text.

    Returns ``{"references": [...], "prettyString": str, "valid": bool}``.
    Recognises scripture refs, JST refs (``JST Matt 5:22``), and study-help
    entries (``TG Faith``, ``BD Aaron``, ``Index God``). Use this as the
    validation gate before fetching anything.
    """
    return _get(f"{SCRIPTURES_BASE}/referencesParser", {"reference": reference})


def find_references_in_text(text: str) -> dict:
    """Scan a block of free text and return every scripture reference found.

    Returns ``{"text": str, "count": int, "references": [...]}`` where each
    reference carries ``start``/``end`` character offsets, the ``raw``
    matched string, a ``prettyString``, and the parsed ``reference`` data.

    Used at corpus-build time to tag each converted page with the verses it
    discusses, and at answer time to find which Conference talks cite a verse.
    """
    return _post(f"{SCRIPTURES_BASE}/referencesFinder", {"text": text})


# --------------------------------------------------------------------------
# Scripture text
# --------------------------------------------------------------------------

def get_chapter(book_id: str, chapter: int) -> dict:
    """Fetch a full chapter: all verses with footnotes, plus the summary."""
    return _get(f"{SCRIPTURES_BASE}/book/{book_id}/{chapter}")


def get_verse(book_id: str, chapter: int, verse: int) -> dict:
    """Fetch one verse and its cross-references (parsed from its footnotes).

    Returns ``{"reference", "book", "chapter", "verse", "text",
    "crossReferences", "jstReferences"}``.
    """
    return _get(f"{SCRIPTURES_BASE}/book/{book_id}/{chapter}/{verse}")


def get_cross_references(book_id: str, chapter: int, verse: int) -> dict:
    """Cross-references for a verse, resolved from its footnote data.

    Same endpoint as :func:`get_verse`; named separately to match how the
    agent instructions describe the step. The ``crossReferences`` list is
    the *parsed* view of the verse's footnotes -- each entry has ``raw``,
    ``prettyString`` and structured ``references`` (scripture and/or study
    help). For the footnotes *as printed* (letter marker anchored to a word
    in the verse), use :func:`get_footnotes`.
    """
    return _get(f"{SCRIPTURES_BASE}/book/{book_id}/{chapter}/{verse}")


def get_footnotes(book_id: str, chapter: int, verse: int) -> list[dict]:
    """The lettered footnotes on a verse, as printed in the scriptures.

    Returns a list of
    ``{"marker", "anchor", "text", "start", "end"}`` where ``marker`` is the
    superscript letter (a, b, c, ...), ``anchor`` is the word or phrase in
    the verse the note attaches to, and ``text`` is the raw footnote content
    (which may bundle several scripture refs and/or Topical Guide entries,
    e.g. "Mosiah 1:2 (2-3); D&C 68:25. TG Honoring Father and Mother.").

    This is the footnote view; :func:`get_cross_references` is the resolved
    scripture-reference view of the same underlying data. A full study view
    shows both.
    """
    chapter_data = get_chapter(book_id, chapter)
    verses = chapter_data.get("chapter", {}).get("verses", [])
    if not 1 <= verse <= len(verses):
        raise ScriptureAPIError(f"{book_id} {chapter}:{verse} not found")
    verse_obj = verses[verse - 1]
    text = verse_obj.get("text", "")
    notes = []
    for i, footnote in enumerate(verse_obj.get("footNotes", [])):
        start = footnote.get("start", 0)
        end = footnote.get("end", 0)
        notes.append({
            "marker": chr(ord("a") + i) if i < 26 else str(i + 1),
            "anchor": text[start:end],
            "text": footnote.get("text", ""),
            "start": start,
            "end": end,
        })
    return notes


def section_heading(book_id: str, chapter: int) -> str | None:
    """Return the section-heading / introduction text for a chapter, or None.

    For Doctrine and Covenants sections this is the paragraph naming the
    date and place the revelation was received (e.g. "... at Fayette, New
    York, April 6, 1830."), which is the match key for Joseph Smith Papers
    documents in the local corpus.
    """
    chapter_data = get_chapter(book_id, chapter)
    augmentations = chapter_data.get("chapter", {}).get("chapterAugmentations", [])
    for aug in augmentations:
        if aug.get("type") == "introduction":
            return aug.get("text")
    return None


def search_scripture(query: str, **params) -> dict:
    """Full-text search. Supports the API's query syntax (phrases, wildcards,
    boolean OR/NOT, proximity). Pass ``volume=``/``book=`` to scope it,
    ``highlight=True`` for KWIC snippets, ``context_verses=N`` for context.
    """
    params["q"] = query
    return _get(f"{SCRIPTURES_BASE}/search", params)


# --------------------------------------------------------------------------
# Study helps: Topical Guide, Bible Dictionary, Triple Combination Index, JST
# --------------------------------------------------------------------------

def list_study_help_types() -> dict:
    """List study-help types (tg, bd, index, jst) with entry counts."""
    return _get(f"{STUDY_HELPS_BASE}/types")


def list_study_help_entries(type: str, q: str | None = None,
                            limit: int = 50, offset: int = 0) -> dict:
    """List entries for a study-help type, sorted alphabetically by title.

    ``q`` is a case-insensitive *substring* match on the title (``q="vis"``
    matches "Vision", "First Vision", "Provision", "Invisible"). For a
    prefix / "everything starting with A" query use
    :func:`study_help_entries_by_letter`.
    """
    params: dict = {"type": type, "limit": limit, "offset": offset}
    if q is not None:
        params["q"] = q
    return _get(f"{STUDY_HELPS_BASE}/entries", params)


def get_study_help_entry(entry_id: str) -> dict:
    """Fetch one study-help entry by id.

    Entry ids: ``tg-faith``, ``bd-aaron``, ``index-god``, and JST chapters
    as ``jst-{bookId}-{chapter}`` (e.g. ``jst-matthew-5``).
    """
    return _get(f"{STUDY_HELPS_BASE}/entry/{entry_id}")


def study_help_slug(subject: str) -> str:
    """Turn a human subject into the API's entry slug.

    "Faith" -> "faith"; "Honoring Father and Mother" ->
    "honoring-father-and-mother"; "Israel, Judah, People of" ->
    "israel-judah-people-of". Lowercase, ``&`` -> "and", punctuation
    dropped, whitespace -> single hyphens.
    """
    text = subject.strip().lower().replace("&", " and ")
    text = re.sub(r"[^\w\s-]", "", text)      # drop commas, periods, apostrophes
    text = re.sub(r"[\s_-]+", "-", text)
    return text.strip("-")


def get_study_help_by_subject(type: str, subject: str) -> dict:
    """Fetch a study-help entry by human subject name instead of entry id.

    ``get_study_help_by_subject("tg", "Faith")`` -> entry ``tg-faith``.
    Raises :class:`ScriptureAPIError` if there is no such entry.
    """
    return get_study_help_entry(f"{type}-{study_help_slug(subject)}")


def get_topical_guide(subject: str) -> dict:
    """Topical Guide entry by subject, e.g. ``get_topical_guide("Faith")``."""
    return get_study_help_by_subject("tg", subject)


def get_bible_dictionary(subject: str) -> dict:
    """Bible Dictionary entry by subject, e.g. ``get_bible_dictionary("Aaron")``."""
    return get_study_help_by_subject("bd", subject)


def study_help_entries_by_letter(type: str, letter: str,
                                 page_size: int = 500) -> list[dict]:
    """Every entry of a study-help type whose title starts with ``letter``.

    Returns the entry-list dicts (``_id``, ``type``, ``slug``, ``title``) in
    alphabetical order. Pages the list endpoint and filters client-side,
    since the API's ``q`` is a substring match, not a prefix. Stops early
    once the alphabetical listing moves past the target letter.
    """
    letter = letter.strip()[:1].upper()
    matches: list[dict] = []
    offset = 0
    while True:
        page = list_study_help_entries(type, limit=page_size, offset=offset)
        entries = page.get("entries", [])
        if not entries:
            break
        for entry in entries:
            first = (entry.get("title") or "").lstrip()[:1].upper()
            if first == letter:
                matches.append(entry)
            elif first > letter:
                return matches  # list is sorted; nothing more can match
        if len(entries) < page_size:
            break
        offset += page_size
    return matches


# --------------------------------------------------------------------------
# General Conference (1971-present)
# --------------------------------------------------------------------------

def list_conferences(limit: int = 20, offset: int = 0,
                     start_year: int | None = None,
                     end_year: int | None = None) -> dict:
    """List conferences, most recent first."""
    params: dict = {"limit": limit, "offset": offset}
    if start_year is not None:
        params["start_year"] = start_year
    if end_year is not None:
        params["end_year"] = end_year
    return _get(f"{CONFERENCE_BASE}/conferences", params)


def get_latest_conference() -> dict:
    """The most recent conference available."""
    return _get(f"{CONFERENCE_BASE}/conferences/latest")


def get_conference(conference_id: str, include_talks: bool = False) -> dict:
    """One conference by id (e.g. ``2024-04``). ``include_talks`` adds talk
    metadata (title/speaker/session) but not full content.
    """
    params = {"include_talks": "true"} if include_talks else None
    return _get(f"{CONFERENCE_BASE}/conference/{conference_id}", params)


def get_talk(talk_id: str, paragraph: int | None = None) -> dict:
    """One talk by id (e.g. ``2024-04-11nelson``), full content with
    paragraphs and footnotes. ``paragraph=N`` returns only that paragraph.
    """
    params = {"paragraph": paragraph} if paragraph is not None else None
    return _get(f"{CONFERENCE_BASE}/talk/{talk_id}", params)


# --------------------------------------------------------------------------
# Come, Follow Me (weekly home-and-church study curriculum)
# --------------------------------------------------------------------------

def list_come_follow_me_lessons(year: int | None = None,
                                limit: int = 60, offset: int = 0) -> dict:
    """List weekly lessons, earliest to latest. Full lesson text is omitted
    from the listing -- fetch a lesson for that. ``year`` filters to one
    manual year.
    """
    params: dict = {"limit": limit, "offset": offset}
    if year is not None:
        params["year"] = year
    return _get(f"{COME_FOLLOW_ME_BASE}/come-follow-me", params)


def get_come_follow_me_lesson(lesson_id: str = "current") -> dict:
    """One weekly lesson. ``lesson_id`` is the week's start date
    (``"2026-01-05"``) or ``"current"`` for the week containing today.

    Returns ``{"_id", "title", "year", "manualId", "dateRange",
    "scriptureReferences", "content": {"text": ...}}``.
    """
    return _get(f"{COME_FOLLOW_ME_BASE}/come-follow-me/{lesson_id}")


if __name__ == "__main__":  # pragma: no cover - manual smoke check
    import json
    import sys

    ref = sys.argv[1] if len(sys.argv) > 1 else "Isaiah 1:1"
    print(f"resolve_reference({ref!r}):")
    print(json.dumps(resolve_reference(ref), indent=2))
