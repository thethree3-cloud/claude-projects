"""Browser view for the scripture study agent (Project 17).

Everything shown here comes from the Open Scripture API via scripture_api --
no local corpus, no LLM yet. It's a way to see the "reference in -> sourced
study view out" fan-out working on real data before the agent flow is built.

    streamlit run streamlit_app.py

The active reference lives in the URL (``?ref=Isaiah 1:1``), so footnote and
study-help references render as ordinary links: click one to bring it up, and
the browser back button walks your history.
"""

from urllib.parse import quote

import streamlit as st

import scripture_api as api

st.set_page_config(page_title="Scripture study", page_icon=":material/menu_book:")

DEFAULT_REF = "Isaiah 1:1"
_TTL = "6h"


# --- cached API wrappers -------------------------------------------------

@st.cache_data(ttl=_TTL, max_entries=256, show_spinner=False)
def resolve(reference: str) -> dict:
    return api.resolve_reference(reference)


@st.cache_data(ttl=_TTL, max_entries=256, show_spinner=False)
def verse(book: str, chapter: int, v: int) -> dict:
    return api.get_verse(book, chapter, v)


@st.cache_data(ttl=_TTL, max_entries=256, show_spinner=False)
def footnotes(book: str, chapter: int, v: int) -> list[dict]:
    return api.get_footnotes(book, chapter, v)


@st.cache_data(ttl=_TTL, max_entries=128, show_spinner=False)
def chapter(book: str, chapter_number: int) -> dict:
    return api.get_chapter(book, chapter_number)


@st.cache_data(ttl=_TTL, max_entries=64, show_spinner=False)
def heading(book: str, chapter_number: int) -> str | None:
    return api.section_heading(book, chapter_number)


@st.cache_data(ttl=_TTL, max_entries=256, show_spinner=False)
def study_help(entry_id: str) -> dict:
    return api.get_study_help_entry(entry_id)


@st.cache_data(ttl=_TTL, max_entries=64, show_spinner=False)
def entries_by_letter(help_type: str, letter: str) -> list[dict]:
    return api.study_help_entries_by_letter(help_type, letter)


@st.cache_data(ttl=_TTL, max_entries=512, show_spinner=False)
def refs_in_text(text: str) -> list[str]:
    """Unique pretty reference strings the API finds in a block of text."""
    try:
        found = api.find_references_in_text(text)
    except api.ScriptureAPIError:
        return []
    out: list[str] = []
    for ref in found.get("references", []):
        pretty = ref.get("prettyString")
        if pretty and pretty not in out:
            out.append(pretty)
    return out


# --- helpers ------------------------------------------------------------

def ref_link(label: str, target: str | None = None) -> str:
    """A markdown link that reloads the page with ?ref=<target>."""
    return f"[{label}](?ref={quote(target or label)})"


def link_row(refs: list[str], prefix: str = "") -> None:
    if refs:
        st.markdown(prefix + " &nbsp;·&nbsp; ".join(ref_link(r) for r in refs))


def first_target(parsed: dict):
    """(book_id, chapter, (v_start, v_end) | None) from a resolve payload.

    A ``None`` verse span means the whole chapter was requested. A study-help
    reference comes back as ("__studyhelp__", entry_id, None).
    """
    for ref in parsed.get("references") or []:
        if ref.get("type") == "studyHelp":
            return ("__studyhelp__", ref.get("entryId"), None)
        chapters = ref.get("chapters") or []
        if not chapters:
            continue
        ch = chapters[0]
        verses = ch.get("verses") or []
        span = (verses[0]["start"], verses[0]["end"]) if verses else None
        return (ref["book"], ch["start"], span)
    return (None, None, None)


def chapter_target(pretty: str) -> str:
    """'Isaiah 1:1-5' -> 'Isaiah 1'; 'D&C 21' -> 'D&C 21'."""
    return pretty.rsplit(":", 1)[0]


_HELP_PREFIX = {"tg": "TG", "bd": "BD", "index": "Index"}


def render_study_help_body(entry: dict) -> None:
    for block in entry.get("content", []):
        st.markdown(block.get("text", ""))
        cites: list[str] = []
        for ref in block.get("references", []):
            label = ref.get("text")
            if label and label not in cites:
                cites.append(label)
        link_row(cites, prefix="→ &nbsp;")


def render_study_help_entry(entry_id: str, note: str | None = None) -> None:
    """Fetch and render a study-help entry (raises ScriptureAPIError first if
    there is no such entry, before anything is written)."""
    entry = study_help(entry_id)
    if note:
        st.caption(note)
    st.subheader(entry.get("title", entry_id), anchor=False)
    render_study_help_body(entry)
    see_also = entry.get("seeAlso") or []
    if see_also:
        prefix = _HELP_PREFIX.get(entry.get("type", ""), "TG")
        st.markdown(
            "**See also:** "
            + " &nbsp;·&nbsp; ".join(
                ref_link(sa["title"], f"{prefix} {sa['title']}") for sa in see_also
            )
        )
    st.caption(f"Source: Open Scripture API ({entry_id})")


def render_verse_view(book: str, ch: int, v: int, pretty: str) -> None:
    data = verse(book, ch, v)

    st.subheader(pretty, anchor=False)
    st.markdown(f"> {data['text']}")
    st.caption("Source: Open Scripture API")

    notes = footnotes(book, ch, v)
    if notes:
        st.markdown("**Footnotes** (as printed)")
        for note in notes:
            anchor = f"_{note['anchor']}_ — " if note["anchor"] else ""
            st.markdown(f"&nbsp;&nbsp;**{note['marker']}** &nbsp;{anchor}{note['text']}")
        referenced: list[str] = []
        for note in notes:
            for pretty_ref in refs_in_text(note["text"]):
                if pretty_ref not in referenced:
                    referenced.append(pretty_ref)
        link_row(referenced, prefix="**Referenced passages** &nbsp; ")
        st.caption("Source: Open Scripture API")

    help_ids: list[tuple[str, str]] = []
    for xref in data.get("crossReferences", []):
        for ref in xref.get("references", []):
            if ref.get("type") == "studyHelp" and ref.get("entryId"):
                pair = (ref["entryId"], ref.get("title", ref["entryId"]))
                if pair not in help_ids:
                    help_ids.append(pair)

    for jst in data.get("jstReferences", []):
        with st.expander(f"Joseph Smith Translation — {jst.get('raw', '')}"):
            st.markdown(jst.get("inlineText") or "_Full text via the JST entry._")
            st.caption(f"Source: Open Scripture API ({jst.get('entryId', '')})")

    for entry_id, title in help_ids:
        with st.expander(f"Study help — {title}"):
            render_study_help_body(study_help(entry_id))
            st.caption(f"Source: Open Scripture API ({entry_id})")

    section = heading(book, ch)
    if section:
        st.markdown("**Section heading**")
        st.info(section)
        st.caption("Source: Open Scripture API")

    st.divider()
    st.markdown(ref_link(f"Open all of {chapter_target(pretty)}", chapter_target(pretty)))


def render_multi_verse(book: str, ch: int, span, pretty: str) -> None:
    """A verse range (span = (start, end)) or a whole chapter (span = None)."""
    data = chapter(book, ch).get("chapter", {})
    book_title = data.get("bookTitle", chapter_target(pretty))
    st.subheader(pretty if span else f"{book_title} {ch}", anchor=False)
    if data.get("summary"):
        st.caption(data["summary"])
    section = heading(book, ch)
    if section:
        st.info(section)

    base = chapter_target(pretty)  # "Isaiah 1"
    lo, hi = span if span else (1, len(data.get("verses", [])))
    for i, vs in enumerate(data.get("verses", []), start=1):
        if lo <= i <= hi:
            marker = ref_link(f"**{i}**", f"{base}:{i}")
            st.markdown(f"{marker}&nbsp; {vs['text']}")
    st.caption("Source: Open Scripture API — verse numbers link to the full study view")

    if span:
        st.divider()
        st.markdown(ref_link(f"Open all of {base}", base))


# --- page --------------------------------------------------------------

st.title("Scripture study")
st.caption("Grounded study helps from the Open Scripture API. Nothing here is generated.")

mode = st.segmented_control(
    "Mode",
    ["Study a reference", "Browse the Topical Guide"],
    default="Study a reference",
    label_visibility="collapsed",
)

if mode == "Study a reference":
    active = st.query_params.get("ref", DEFAULT_REF)

    with st.form("ref", border=False):
        raw = st.text_input(
            "Reference",
            value=active,
            placeholder="Isaiah 1:1  ·  Isaiah 1:1-5  ·  D&C 21  ·  TG Faith",
        )
        submitted = st.form_submit_button("Look up", icon=":material/search:")
    if submitted and raw.strip():
        st.query_params["ref"] = raw.strip()
        active = raw.strip()

    try:
        parsed = resolve(active)
    except api.ScriptureAPIError:
        parsed = None

    if parsed is None:
        # Not a scripture reference. It may be a study-help subject typed
        # without the "TG "/"BD " prefix (e.g. "Jesus Christ", "Passover").
        slug = api.study_help_slug(active)
        for help_type, name in (("tg", "Topical Guide"), ("bd", "Bible Dictionary")):
            try:
                render_study_help_entry(
                    f"{help_type}-{slug}",
                    note=f"Not a scripture reference — showing the {name} entry.",
                )
            except api.ScriptureAPIError:
                continue
            st.stop()
        st.error(
            f"Couldn't find “{active}” as a scripture reference or a "
            "Topical Guide / Bible Dictionary subject."
        )
        st.stop()

    pretty = parsed.get("prettyString", active)
    if pretty.lower() != active.lower():
        st.warning(f"Read as **{pretty}**. If that's not what you meant, rephrase.")

    book, ch, span = first_target(parsed)
    if book == "__studyhelp__":
        render_study_help_entry(ch)
    elif book and span and span[0] == span[1]:
        render_verse_view(book, ch, span[0], pretty)
    elif book:
        render_multi_verse(book, ch, span, pretty)
    else:
        st.error("That reference didn't resolve to a passage.")

else:
    help_type = st.segmented_control(
        "Study help",
        options=["tg", "bd"],
        format_func={"tg": "Topical Guide", "bd": "Bible Dictionary"}.get,
        default="tg",
    )
    tab_subject, tab_letter = st.tabs(["By subject", "By first letter"])

    with tab_subject:
        with st.form("subject", border=False):
            subject = st.text_input("Subject", placeholder="Faith")
            go = st.form_submit_button("Look up", icon=":material/search:")
        if go and subject.strip():
            entry_id = f"{help_type}-{api.study_help_slug(subject)}"
            try:
                render_study_help_entry(entry_id)
            except api.ScriptureAPIError:
                st.error(f"No entry for “{subject.strip()}”. Try the by-letter list.")

    with tab_letter:
        letter = st.select_slider(
            "Letter", options=[chr(c) for c in range(ord("A"), ord("Z") + 1)], value="A"
        )
        matches = entries_by_letter(help_type, letter)
        st.caption(f"{len(matches)} entries starting with {letter} — open one to load it")
        for entry in matches:
            exp = st.expander(entry["title"], on_change="rerun")
            if exp.open:
                with exp:
                    render_study_help_body(study_help(entry["_id"]))
                    st.caption(f"Source: Open Scripture API ({entry['_id']})")
