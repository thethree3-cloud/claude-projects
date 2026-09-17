import streamlit as st

from deep_draw_catalog import DEEP_DRAW_BOXES, ALLOY, COVER_TYPES, NUTPLATE_PATTERNS
from deep_draw_pricing import compute_box_quote
from diagram import draw_box
from quote_lookup import estimate_from_history, load_quotes
from branding import render_header

st.set_page_config(page_title="Deep-draw box configurator", layout="wide")
render_header("Deep-Draw Box Configurator")


@st.cache_data
def _load_quote_history():
    return load_quotes()


st.caption(
    "A representative sample of real Zero Manufacturing deep-drawn box sizes "
    "(width, length, height range, gauge) — pick a size, an optional cover, "
    "and an optional nutplate pattern to get a formula quote and a comparison "
    "to similar synthetic historical quotes."
)

box_by_part_no = {b["part_no"]: b for b in DEEP_DRAW_BOXES}

with st.sidebar:
    st.subheader("Box size")
    part_no = st.selectbox(
        "Catalog part number",
        sorted(box_by_part_no.keys(), key=lambda p: box_by_part_no[p]["width_in"]),
        format_func=lambda p: f"{p} ({box_by_part_no[p]['width_in']:g}\" x {box_by_part_no[p]['length_in']:g}\")",
    )
    box = box_by_part_no[part_no]

    height_in = st.slider(
        "Height", min_value=box["height_min_in"], max_value=box["height_max_in"],
        value=box["height_min_in"], step=0.25,
    )

    st.subheader("Add-ons")
    cover_type = st.segmented_control("Cover type", COVER_TYPES, default="none")
    nutplate_pattern = st.segmented_control("Nutplate pattern", NUTPLATE_PATTERNS, default="none")

if not cover_type or not nutplate_pattern:
    st.info("Select a cover type and nutplate pattern in the sidebar (or leave both on \"none\").")
    st.stop()

st.write(
    f"**{part_no}**: {box['width_in']:g}\" W x {box['length_in']:g}\" L x {height_in:g}\" H, "
    f".{str(box['gauge_in']).split('.')[1]}\" gauge, {ALLOY} aluminum "
    f"(catalog page {box['catalog_page']})"
)

fig = draw_box(
    width_in=box["width_in"], length_in=box["length_in"], height_in=height_in,
    r1_in=box["r1_in"], r2_in=box["r2_in"], gauge_in=box["gauge_in"],
    cover_type=cover_type, nutplate_pattern=nutplate_pattern,
)
st.pyplot(fig, width=650)

quote_col, history_col = st.columns(2)

with quote_col:
    st.subheader("Formula quote")
    quote = compute_box_quote(
        width_in=box["width_in"], length_in=box["length_in"], height_in=height_in,
        gauge_in=box["gauge_in"], cover_type=cover_type, nutplate_pattern=nutplate_pattern,
    )
    st.caption(f"Estimated draw operations: {quote['num_draws']}")

    label_map = {"material": "Material", "labor": "Fabrication labor", "cover": "Cover", "nutplates": "Nutplates"}
    for key, amount in quote["line_items"].items():
        st.write(f"{label_map.get(key, key)}: ${amount:,.2f}")

    st.divider()
    st.write(f"Subtotal: ${quote['subtotal']:,.2f}")
    st.write(f"Markup: ${quote['markup']:,.2f}")
    st.metric("Total estimate", f"${quote['total']:,.2f}")
    st.caption("Placeholder pricing — see deep_draw_pricing.py for sources/assumptions.")

with history_col:
    st.subheader("Similar past quotes")
    st.caption("Synthetic historical data — see generate_quote_history.py.")

    history = _load_quote_history()
    if not history:
        st.info("No quote history found. Run `python generate_quote_history.py` to build it.")
    else:
        estimate = estimate_from_history(
            history, width_in=box["width_in"], length_in=box["length_in"], height_in=height_in,
        )
        if estimate is None:
            st.warning("No similar historical quotes found for this size.")
        else:
            st.write(f"Based on **{estimate.match_count}** similar past quotes:")
            st.write(
                f"Average: \\${estimate.avg_price:,.2f}  "
                f"(range \\${estimate.min_price:,.2f}\u2013\\${estimate.max_price:,.2f})"
            )
            st.progress(estimate.confidence, text=f"Confidence: {estimate.confidence:.0%}")
