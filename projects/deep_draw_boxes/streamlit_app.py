from pathlib import Path

import streamlit as st

from deep_draw_catalog import (
    DEEP_DRAW_BOXES, COVER_TYPES, NUTPLATE_PATTERNS, FINISH_TYPES,
    ZMS_BOXES, ZMR_BOXES,
)
from deep_draw_pricing import compute_box_quote
from mini_series_pricing import MATERIALS, compute_mini_box_quote
from diagram import draw_box
from quote_lookup import estimate_from_history, load_quotes
from branding import render_header
from quote_export import to_pdf, to_pdf_mini

st.set_page_config(page_title="Deep-draw box configurator", layout="wide")
render_header("Deep-Draw Box Configurator")

FINISH_COLORS = {
    "mill finish": "#b8bcc0",
    "black anodized": "#1c1c1c",
}


MINI_DB_PATH = Path(__file__).parent / "data" / "mini_quote_history.db"


@st.cache_data
def _load_quote_history():
    return load_quotes()


@st.cache_data
def _load_mini_quote_history():
    return load_quotes(MINI_DB_PATH)


def _finish_and_color(key_prefix: str):
    st.subheader("Finish")
    finish = st.segmented_control("Finish", FINISH_TYPES, default="mill finish", key=f"{key_prefix}_finish")
    if finish == "powder coat (custom color)":
        color_hex = st.color_picker("Powder coat color", value="#2a4d69", key=f"{key_prefix}_color")
    elif finish:
        color_hex = FINISH_COLORS[finish]
    else:
        color_hex = FINISH_COLORS["mill finish"]
    return finish, color_hex


with st.sidebar:
    st.subheader("Catalog series")
    series = st.radio(
        "Series", ["Standard (Rectangular Boxes)", "Miniature (ZMR/ZMS)"],
        label_visibility="collapsed",
    )

if series == "Miniature (ZMR/ZMS)":
    with st.sidebar:
        st.subheader("Box size")
        shape = st.radio("Shape", ["Square (ZMS)", "Rectangular (ZMR)"])
        mini_boxes = ZMS_BOXES if shape == "Square (ZMS)" else ZMR_BOXES
        mini_by_part_no = {b["part_no"]: b for b in mini_boxes}
        mini_part_no = st.selectbox(
            "Catalog part number",
            sorted(mini_by_part_no.keys(), key=lambda p: mini_by_part_no[p]["width_in"]),
            format_func=lambda p: f"{p} ({mini_by_part_no[p]['width_in']:g}\" x {mini_by_part_no[p]['length_in']:g}\")",
        )
        mini_box = mini_by_part_no[mini_part_no]

        st.caption(f"Maximum depth (fixed, no adjustable range published): {mini_box['max_depth_in']:g}\"")

        st.subheader("Material")
        material_key = st.selectbox(
            "Material", list(MATERIALS.keys()),
            format_func=lambda k: MATERIALS[k]["label"],
        )

        finish, color_hex = _finish_and_color("mini")

    if not finish:
        st.info("Select a finish in the sidebar.")
        st.stop()

    height_in = mini_box["max_depth_in"]
    series_label = "ZMS" if shape == "Square (ZMS)" else "ZMR"
    st.caption(
        f"{series_label} miniature series — small enclosures cross-referenced off the main "
        "Rectangular Boxes table, available in steel, aluminum, brass, or Monel. No cover or "
        "nutplate options modeled for this series yet."
    )
    quote = compute_mini_box_quote(
        width_in=mini_box["width_in"], length_in=mini_box["length_in"], height_in=height_in,
        material_code=mini_box["material_code"], gauge_override_in=mini_box["gauge_override_in"],
        material_key=material_key, finish=finish,
    )

    st.write(
        f"**{mini_part_no}**: {mini_box['width_in']:g}\" W x {mini_box['length_in']:g}\" L x "
        f"{height_in:g}\" H max, {quote['gauge_in']:g}\" gauge, {MATERIALS[material_key]['label']} "
        f"(catalog page {mini_box['catalog_page']})"
    )

    fig = draw_box(
        width_in=mini_box["width_in"], length_in=mini_box["length_in"], height_in=height_in,
        r1_in=mini_box["r1_in"], r2_in=mini_box["r2_in"], gauge_in=quote["gauge_in"],
        cover_type="none", nutplate_pattern="none", color_hex=color_hex,
    )
    st.pyplot(fig, width=900)

    mini_quote_col, mini_history_col = st.columns(2)

    with mini_quote_col:
        st.subheader("Formula quote")
        st.caption(f"Estimated draw operations: {quote['num_draws']}")

        label_map = {"material": "Material", "labor": "Fabrication labor", "finish": "Finish upcharge"}
        for key, amount in quote["line_items"].items():
            st.write(f"{label_map.get(key, key)}: ${amount:,.2f}")

        st.divider()
        st.write(f"Subtotal: ${quote['subtotal']:,.2f}")
        st.write(f"Markup: ${quote['markup']:,.2f}")
        st.metric("Total estimate", f"${quote['total']:,.2f}")
        st.caption("Placeholder pricing — see mini_series_pricing.py for sources/assumptions.")

    with mini_history_col:
        st.subheader("Similar past quotes")
        st.caption("Synthetic historical data — see generate_mini_quote_history.py.")

        mini_history = _load_mini_quote_history()
        mini_estimate = None
        if not mini_history:
            st.info("No quote history found. Run `python generate_mini_quote_history.py` to build it.")
        else:
            mini_estimate = estimate_from_history(
                mini_history, width_in=mini_box["width_in"], length_in=mini_box["length_in"], height_in=height_in,
            )
            if mini_estimate is None:
                st.warning("No similar historical quotes found for this size.")
            else:
                st.write(f"Based on **{mini_estimate.match_count}** similar past quotes:")
                st.write(
                    f"Average: \\${mini_estimate.avg_price:,.2f}  "
                    f"(range \\${mini_estimate.min_price:,.2f}\u2013\\${mini_estimate.max_price:,.2f})"
                )
                st.progress(mini_estimate.confidence, text=f"Confidence: {mini_estimate.confidence:.0%}")

    st.divider()
    pdf_bytes = to_pdf_mini(
        mini_part_no, series_label, mini_box["width_in"], mini_box["length_in"], height_in,
        MATERIALS[material_key]["label"], quote, fig, finish=finish, estimate=mini_estimate,
    )
    st.download_button(
        "Download quote as PDF",
        data=pdf_bytes,
        file_name=f"zero_box_quote_{mini_part_no}.pdf",
        mime="application/pdf",
        icon=":material/download:",
    )
    st.stop()

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

    finish, color_hex = _finish_and_color("standard")

    st.subheader("Add-ons")
    cover_type = st.segmented_control("Cover type", COVER_TYPES, default="none")
    nutplate_pattern = st.segmented_control("Nutplate pattern", NUTPLATE_PATTERNS, default="none")

if not finish or not cover_type or not nutplate_pattern:
    st.info("Select a finish, cover type, and nutplate pattern in the sidebar (or leave the latter two on \"none\").")
    st.stop()

st.write(
    f"**{part_no}**: {box['width_in']:g}\" W x {box['length_in']:g}\" L x {height_in:g}\" H, "
    f".{str(box['gauge_in']).split('.')[1]}\" gauge, {box['alloy']} aluminum "
    f"(catalog page {box['catalog_page']})"
)

fig = draw_box(
    width_in=box["width_in"], length_in=box["length_in"], height_in=height_in,
    r1_in=box["r1_in"], r2_in=box["r2_in"], gauge_in=box["gauge_in"],
    cover_type=cover_type, nutplate_pattern=nutplate_pattern, color_hex=color_hex,
)
st.pyplot(fig, width=900)

quote_col, history_col = st.columns(2)

with quote_col:
    st.subheader("Formula quote")
    quote = compute_box_quote(
        width_in=box["width_in"], length_in=box["length_in"], height_in=height_in,
        gauge_in=box["gauge_in"], cover_type=cover_type, nutplate_pattern=nutplate_pattern,
        finish=finish,
    )
    st.caption(f"Estimated draw operations: {quote['num_draws']}")

    label_map = {
        "material": "Material", "labor": "Fabrication labor", "cover": "Cover",
        "nutplates": "Nutplates", "finish": "Finish upcharge",
    }
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
    estimate = None
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

st.divider()
pdf_bytes = to_pdf(part_no, box, height_in, quote, fig, cover_type, nutplate_pattern, finish=finish, estimate=estimate)
st.download_button(
    "Download quote as PDF",
    data=pdf_bytes,
    file_name=f"zero_box_quote_{part_no}.pdf",
    mime="application/pdf",
    icon=":material/download:",
)
