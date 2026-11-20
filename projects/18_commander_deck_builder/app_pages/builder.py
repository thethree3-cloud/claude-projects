"""Deck builder page of the Streamlit app (run ``streamlit_app.py``).

Pick a commander (and a second one for partners / Backgrounds / Doctors) and
a budget, optionally use your scanned collection, then
build with the no-LLM baseline or with Claude. Every deck is checked by the
full validator before it is shown. Card images come from Scryfall. Click a
card name to open its page (every printing); the deck and settings stay.
"""

from urllib.parse import quote

import streamlit as st

import deck_service
import edhrec_client
import llm_deck
from collection import Collection
from flip_card import flip_card
from scan_binder import ScanError, make_client

CARD_PAGE = "app_pages/card.py"
GRID_COLUMNS = 5  # the alternates panel takes the right quarter
MODELS = ["claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5"]
ROLE_TITLES = {"land": "Lands", "ramp": "Ramp", "draw": "Card draw", "removal": "Removal",
               "wipe": "Board wipes", "tutor": "Tutors", "synergy": "Synergy"}

st.session_state.setdefault("result", None)
st.session_state.setdefault("swap_history", [])  # earlier results, for Undo


# ---------------------------------------------------------------------------
# Cached data
# ---------------------------------------------------------------------------


@st.cache_data(ttl="1d", show_spinner="Loading card data...")
def load_commanders():
    db = deck_service.open_db()
    try:
        return deck_service.commander_names(db)
    finally:
        db.close()


@st.cache_data(ttl="1d", max_entries=50)
def load_partners(commander):
    db = deck_service.open_db()
    try:
        return deck_service.partner_names(commander, db)
    finally:
        db.close()


@st.cache_data(ttl="1m")
def load_collection():
    col = Collection()
    try:
        return {"binders": [b["binder"] for b in col.binders()], "all": sorted(col.names())}
    finally:
        col.close()


@st.cache_data(ttl="1h", max_entries=20, show_spinner="Fetching EDHREC data...")
def load_prep(commander, partner, owned, max_card_price, max_salt=None, bracket=None, cut_combos=True):
    db = deck_service.open_db()
    try:
        return deck_service.prepare(commander, db, frozenset(owned), partner, max_card_price, max_salt, bracket,
                                    cut_combos)
    finally:
        db.close()


@st.cache_data(ttl="1d", max_entries=50, show_spinner="Checking bracket and salt...")
def load_profile(deck_key, commander, deck):
    db = deck_service.open_db()
    try:
        return deck_service.deck_profile(commander, deck, db)
    finally:
        db.close()


@st.cache_data(ttl="1d", max_entries=50, show_spinner="Asking Commander Spellbook...")
def load_combos(commanders, main):
    import combos
    db = deck_service.open_db()
    try:
        return combos.find_combos(list(commanders), list(main), db)
    finally:
        db.close()


@st.cache_data(ttl="5m")
def claude_available():
    """True if an Anthropic API key is set (environment, Streamlit secrets or the repo's .env).
    A hosted demo without a key still works with the code-only builder."""
    import os
    from dotenv import load_dotenv
    from scan_binder import ENV_PATH
    load_dotenv(ENV_PATH)
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


@st.cache_resource
def claude_client():
    return make_client().with_options(timeout=600, max_retries=4)


def owned_names(binder):
    if binder == "All binders":
        return tuple(load_collection()["all"])
    col = Collection()
    try:
        return tuple(sorted(col.names(binder=binder)))
    finally:
        col.close()


# ---------------------------------------------------------------------------
# Controls
# ---------------------------------------------------------------------------

commanders = load_commanders()
collection = load_collection()

with st.sidebar:
    st.header("Build a deck")
    commander = st.selectbox(
        "Commander", commanders, index=commanders.index("Kestia, the Cultivator")
        if "Kestia, the Cultivator" in commanders else 0, key="commander", persist_state="session",
        help="Type to search. Ordered by how many decks each commander leads (EDHREC, past 2 years).",
    )
    partners = load_partners(commander)
    partner = None
    if partners:
        partner = st.selectbox(
            "Second commander", partners, index=None, key=f"partner-{commander}", persist_state="session",
            placeholder="None (build with one commander)",
            help="Cards that can share the command zone with this one: partners, Backgrounds or Doctors.",
        )
    budget = st.number_input("Budget (USD, commander included)", min_value=0, max_value=5000, value=100,
                             step=10, key="budget", persist_state="session")
    max_card = st.number_input("Max price per card (USD, optional)", min_value=0.0, max_value=1000.0, value=None,
                               step=1.0, key="max_card_price", persist_state="session", placeholder="No limit",
                               help="Cards you'd have to buy above this price are left out. Owned cards and the "
                                    "commander don't count.")
    import salt as salt_mod
    bracket_target = st.selectbox(
        "Target bracket", [None, 2, 3, 4], key="target_bracket", persist_state="session",
        format_func=lambda b: "Any" if b is None else {2: "2 (Core): no Game Changers", 3: "3 (Upgraded): up to 3 Game Changers",
                                                       4: "4 (Optimized): anything"}[b],
        help="Limits Game Changers to what the bracket allows; the built deck is then checked by Commander Spellbook "
             "for combos and land denial too.")
    remove_combos = st.toggle(
        "Remove two-card combos", value=True, key="remove_combos", persist_state="session",
        disabled=bracket_target not in (2, 3),
        help="On: one piece of each two-card combo is left out, as the bracket rules require (bracket 3: only fast "
             "combos). Off: combos stay in, so you can build around them; the deck may then land above the target.")
    table = st.selectbox("Table", list(salt_mod.FRIENDLY), key="salt_table", persist_state="session",
                         help="Leave out cards players hate facing, by EDHREC's salt score (0-4).")
    use_owned = st.toggle("Use my collection (owned cards cost $0)", key="use_owned", persist_state="session",
                          disabled=not collection["all"],
                          help=None if collection["all"] else "Scan binder pages first (scan_binder.py --binder).")
    binder = st.selectbox("Binder", ["All binders", *collection["binders"]], key="binder", persist_state="session",
                          disabled=not use_owned)
    has_claude = claude_available()
    builder = st.segmented_control("Builder", ["Code only", "Claude"] if has_claude else ["Code only"],
                                   default="Code only", key="builder", persist_state="session", required=True,
                                   help=None if has_claude else "Claude needs an ANTHROPIC_API_KEY; this copy "
                                                                "runs the code-only builder.")
    model = st.selectbox("Claude model", MODELS, key="model", persist_state="session", disabled=builder != "Claude",
                         help="Opus won the eval (see README). Roughly $0.20 / $0.09 / $0.01 per deck.")
    build = st.button("Build deck", type="primary", icon=":material/construction:", width="stretch", key="build")
    st.caption("Card images and prices from Scryfall; deck data from EDHREC. Unofficial fan project, "
               "not affiliated with Wizards of the Coast.")

st.title("Commander deck builder")

# ---------------------------------------------------------------------------
# Build (only when the button is pressed)
# ---------------------------------------------------------------------------

if build:
    owned = owned_names(binder) if use_owned else ()
    try:
        prep = load_prep(commander, partner, owned, max_card, salt_mod.FRIENDLY[table], bracket_target,
                         remove_combos)
        db = deck_service.open_db()
        try:
            if builder == "Claude":
                with st.spinner(f"{model} is picking cards (about 20-60 seconds)..."):
                    result = deck_service.build_claude(prep, budget, db, claude_client(), frozenset(owned), model)
            else:
                result = deck_service.build_code(prep, budget, db, frozenset(owned), owned_mode=use_owned)
        finally:
            db.close()
    except (LookupError, ScanError, OSError, edhrec_client.EdhrecError) as exc:
        st.error(f"Couldn't build the deck: {exc}", icon=":material/error:")
        result = None
    if result is not None:
        st.session_state.result = result | {"commander": prep["commander"], "budget": budget, "prep": prep,
                                            "owned": tuple(owned)}
        st.session_state.swap_history = []

result = st.session_state.result

if result is None:
    st.info("Pick a commander and a budget in the sidebar, then press **Build deck**.", icon=":material/info:")
    st.stop()

# ---------------------------------------------------------------------------
# Result
# ---------------------------------------------------------------------------

cmd = result["commander"]
if result["deck"] is None:
    st.error(f"Claude didn't produce a valid deck in {len(result['attempts'])} attempts, so nothing is shown.",
             icon=":material/block:")
    for e in result["attempts"][-1]["errors"]:
        st.write(f"- {e}")
    st.stop()

deck, check = result["deck"], result["check"]
owned_cards = [c for c in deck["cards"] if c["owned"]]

st.subheader(f"{cmd['name']} - ${result['budget']:,} budget, {result['builder']}")
with st.container(horizontal=True):
    st.metric("Cost to buy", f"${check['stats']['cost_to_buy']:.2f}", border=True)
    st.metric("Lands", check["stats"]["lands"], border=True)
    st.metric("Avg mana value", f"{check['stats']['average_mana_value']:.2f}", border=True)
    st.metric("Owned cards used", len(owned_cards), border=True)
    st.metric("Validator", "Pass" if check["ok"] else "Fail", border=True)
    if result.get("cost_usd") is not None:
        st.metric("API cost", f"${result['cost_usd']:.2f}", border=True,
                  help=f"{len(result['attempts'])} attempt(s)")

profile = load_profile(result["text"], cmd, deck)
b = profile["bracket"]
with st.container(horizontal=True):
    st.metric("Bracket (estimate)", f"{b['lowest']} - {b['name']}" if b and b["lowest"] else (b["name"] if b else "n/a"),
              border=True, help="Lowest official bracket this deck fits, from Commander Spellbook's check "
                                "(Game Changers, combos, land denial, extra turns)")
    st.metric("Salt", f"{profile['salt']['total']:.1f}", border=True,
              help=f"Sum of EDHREC salt scores; average {profile['salt']['average']:.2f} per card")
prep_used = result.get("prep") or {}
if prep_used.get("bracket") in (2, 3) and not prep_used.get("cut_combos", True):
    st.info(f"Two-card combos were kept (Remove two-card combos is off), so this deck can land above bracket "
            f"{prep_used['bracket']}; the estimate below says where it actually sits. Open the Combos tab to see them.",
            icon=":material/join_inner:")
notes = prep_used.get("bracket_notes") or []
if notes:
    with st.expander(f"Left out for bracket {result['prep']['bracket']} ({len(notes)} cards)"):
        st.caption("Removed from the candidate cards before building: mass land denial and extra-turn cards "
                   "(Scryfall tags), and one piece of each two-card combo (Commander Spellbook"
                   + ("; only fast combos for bracket 3" if result["prep"]["bracket"] == 3 else "") + ").")
        for n in notes:
            st.markdown(f"- {n}")
if b or profile["salt"]["saltiest"]:
    with st.expander("Why this bracket, and the saltiest cards"):
        if b:
            for r in b["reasons"]:
                st.markdown(f"- {r}")
            st.caption(f"Commander Spellbook's own tag: {b['spellbook_tag']}.")
        if profile["salt"]["saltiest"]:
            st.markdown("**Saltiest:** " + ", ".join(f"{n} ({s:.2f})" for n, s in profile["salt"]["saltiest"]))

if result.get("strategy"):
    st.markdown(f":material/lightbulb: **Strategy:** {result['strategy']}")
for w in dict.fromkeys(deck["warnings"] + check["warnings"]):  # Claude decks already carry the validator's
    st.warning(w, icon=":material/warning:")
for e in check["errors"]:
    st.error(e, icon=":material/error:")

with st.container(horizontal=True):
    st.download_button("Download import list", result["text"] + "\n",
                       file_name=f"{edhrec_client.slugify(cmd['name'])}_{result['budget']}.txt",
                       icon=":material/download:", help="Paste into Moxfield or Archidekt.")
    basics = ", ".join(f"{n} {b}" for b, n in sorted(deck["basics"].items()))
    st.caption(f"Basic lands (free): {basics or 'none'}")

cards_tab, list_tab, combos_tab = st.tabs(["Cards", "List", "Combos"])

with combos_tab:
    combo_key = (tuple(c["name"] for c in cmd.get("members") or [cmd]), tuple(sorted(c["name"] for c in deck["cards"])))
    if st.session_state.get("combos_for") != combo_key:
        st.caption("Combos already in this deck, and combos one card away, from Commander Spellbook.")
        if st.button("Find combos", icon=":material/join_inner:", key="find_combos"):
            try:
                st.session_state.combos = load_combos(*combo_key)
                st.session_state.combos_for = combo_key
                st.rerun()
            except Exception as exc:  # network / API shape problems
                st.error(f"Couldn't reach Commander Spellbook: {exc}", icon=":material/error:")
    else:
        found = st.session_state.combos
        st.markdown(f"#### In this deck ({len(found['in_deck'])})")
        if not found["in_deck"]:
            st.caption("None found.")
        for c in found["in_deck"]:
            with st.expander(" + ".join(c["cards"])):
                st.markdown(f"**Produces:** {', '.join(c['produces']) or 'see link'}")
                if c["prerequisites"]:
                    st.markdown(f"**Needs:** {c['prerequisites']}")
                st.markdown(c["description"].replace("\n", "  \n"))
                st.link_button("Open on Commander Spellbook", c["url"], icon=":material/open_in_new:")
        st.markdown(f"#### One card away ({len(found['one_card_away'])})")
        if found["one_card_away"]:
            st.dataframe(
                [{"Add": c["missing"][0], "Price": f"${c['missing_usd']:.2f}" if c["missing_usd"] is not None else "n/a",
                  "Combo": " + ".join(c["cards"]), "Produces": ", ".join(c["produces"][:3]), "Link": c["url"]}
                 for c in found["one_card_away"]],
                column_config={"Link": st.column_config.LinkColumn(display_text="Open")}, hide_index=True)
        else:
            st.caption("None.")
        st.caption("Combo data: Commander Spellbook. The builder doesn't add combos on its own.")

with list_tab:
    st.dataframe(
        [{"Card": c["name"], "Role": ROLE_TITLES[c["role"]], "Price": deck_service.price_label(c),
          "EDHREC inclusion": c["inclusion"] if c["listed"] else None,
          "Versions": f"card?name={quote(c['name'])}", "Why": c.get("reason", "")}
         for _, group in deck_service.grouped(deck) for c in group],
        column_config={"EDHREC inclusion": st.column_config.ProgressColumn(format="percent", min_value=0, max_value=1),
                       "Versions": st.column_config.LinkColumn(display_text="All printings",
                                                               help="Opens the card's page in a new tab")},
        hide_index=True,
    )


def card_image(card, key, width="stretch"):
    """A card picture; two-faced cards turn over in 3D when clicked (in the browser, no rerun)."""
    if card.get("image_url") and card.get("image_url_back"):
        flip_card(card["name"], card["image_url"], card["image_url_back"], key=key)
    elif card.get("image_url"):
        st.image(card["image_url"], width=width, alt=card["name"])
    else:
        st.write(card["name"])


def card_link(name, label=None):
    """The card's name as a link to its page (every printing). Same tab, so the deck stays."""
    st.page_link(CARD_PAGE, label=label or name, query_params={"name": name},
                 help="See every printing of this card")


def card_grid(deck):
    """Image grid by role; card names link to the card page."""
    members = cmd.get("members") or [cmd]
    with st.container(horizontal=True):
        for member in members:
            with st.container(width=180):
                card_image(member, key=f"flip-cmd-{member['name']}")
                card_link(member["name"], f"Commander: {member['name']}")
    for role, cards in deck_service.grouped(deck):
        st.markdown(f"#### {ROLE_TITLES[role]} ({len(cards)})")
        for start in range(0, len(cards), GRID_COLUMNS):
            cols = st.columns(GRID_COLUMNS)
            for col, card in zip(cols, cards[start:start + GRID_COLUMNS]):
                with col:
                    card_image(card, key=f"flip-{card['name']}")
                    card_link(card["name"])
                    st.caption(deck_service.price_label(card))
                    if card.get("reason"):
                        st.caption(f":material/smart_toy: {card['reason']}")


def alternates_panel():
    """Top alternates by card type, with a validated swap and Undo."""
    prep = result.get("prep")
    st.markdown("#### Alternates")
    if not prep:
        st.caption("Build the deck again to see alternates.")
        return
    left = result["budget"] - check["stats"]["cost_to_buy"]
    st.caption(f"Next-best cards from the same checked pool. Budget left: **${left:.2f}**.")
    counts = deck_service.type_counts(deck)
    kinds = [k for k in deck_service.CARD_TYPES if counts.get(k) or deck_service.alternates(prep, deck, k, 1)]
    kind = st.selectbox("Card type", kinds, key="alt_kind", persist_state="session",
                        format_func=lambda k: f"{k} ({counts.get(k, 0)} in deck)")
    alts = deck_service.alternates(prep, deck, kind)
    pick_key = f"alt_pick-{kind}"
    if not alts:
        st.caption(f"No more {kind.lower()} cards in the pool.")
    picked_name = st.session_state.get(pick_key)
    pick = next((a for a in alts if a["name"] == picked_name), None)

    # Swap controls first, so they stay in view above the pictures.
    if alts and pick is None:
        st.caption("Select a card below to swap it in.")
    elif pick is not None:
        with st.container(border=True):
            any_type = st.toggle("Replace a card of any type", key="alt_any")
            options = deck_service.replace_options(deck, None if any_type else kind)
            by_name = {c["name"]: c for c in options}
            out_name = st.selectbox(
                f"{pick['name']} replaces", list(by_name), key=f"alt_out-{pick['name']}-{any_type}",
                help="Least-played cards first",
                format_func=lambda n: f"{n} ({by_name[n]['inclusion']:.0%}, {deck_service.price_label(by_name[n])})")
            extra = pick["cost"] - by_name[out_name]["cost"]
            st.caption(f"Cost change: {extra:+.2f} USD" + (" (over the budget left)" if extra > left + 1e-9 else ""))
            if st.button("Swap in", type="primary", icon=":material/swap_horiz:", key="alt_swap", width="stretch"):
                db = deck_service.open_db()
                try:
                    new, errors = deck_service.swap(prep, result, out_name, pick["name"], result["budget"], db,
                                                    frozenset(result.get("owned", ())))
                finally:
                    db.close()
                if errors:
                    st.error("Not swapped: " + " ".join(errors), icon=":material/block:")
                else:
                    st.session_state.swap_history.append(result)
                    st.session_state.result = new
                    st.session_state.pop(pick_key, None)
                    st.rerun()

    # The alternates as pictures, two per row; the selected one is outlined.
    for start in range(0, len(alts), 2):
        for col, a in zip(st.columns(2), alts[start:start + 2]):
            chosen = a["name"] == picked_name
            with col, st.container(border=chosen):
                card_image(a, key=f"alt-img-{a['name']}")
                card_link(a["name"])
                played = f"{a['inclusion']:.0%} of decks" if a["listed"] else "not on EDHREC list"
                st.caption(f"{deck_service.price_label(a)} · {played} · {ROLE_TITLES[a['role']]}")
                st.button("Selected" if chosen else "Select", key=f"alt_sel-{a['name']}", width="stretch",
                          type="primary" if chosen else "secondary",
                          icon=":material/check_circle:" if chosen else None,
                          on_click=lambda k=pick_key, n=a["name"]: st.session_state.update({k: n}))
    swaps = result.get("swaps", [])
    if swaps:
        with st.expander(f"Your swaps ({len(swaps)})"):
            for sw in swaps:
                st.caption(f"{sw['in']} in for {sw['out']} ({sw['extra']:+.2f} USD)")
    if st.session_state.swap_history and st.button("Undo last swap", icon=":material/undo:", key="alt_undo",
                                                   width="stretch"):
        st.session_state.result = st.session_state.swap_history.pop()
        st.rerun()


with cards_tab:
    grid_col, alt_col = st.columns([3, 1], gap="medium")
    with alt_col, st.container(border=True):
        alternates_panel()
    with grid_col:
        card_grid(deck)
