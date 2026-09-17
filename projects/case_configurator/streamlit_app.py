import streamlit as st

from pricing import CaseSpec, MATERIAL_THICKNESS_IN, PRICING, compute_quote
from diagram import draw_case
from quote_lookup import estimate_from_history, load_quotes

st.set_page_config(page_title="Case configurator", layout="wide")

FINISH_COLORS = {
    "mill finish": "#b8bcc0",
    "black anodized": "#1c1c1c",
}


@st.cache_data
def _load_quote_history():
    return load_quotes()

st.title("Aluminum case configurator")
st.caption("Pick dimensions and options to see a scaled diagram and an instant quote.")

with st.sidebar:
    st.subheader("Dimensions (inches)")
    width_in = st.number_input("Width", min_value=4.0, max_value=72.0, value=30.0, step=1.0)
    height_in = st.number_input("Height", min_value=4.0, max_value=72.0, value=30.0, step=1.0)
    depth_in = st.number_input("Depth", min_value=4.0, max_value=48.0, value=18.0, step=1.0)

    st.subheader("Material & finish")
    material = st.segmented_control(
        "Material", list(MATERIAL_THICKNESS_IN.keys()),
        default=list(MATERIAL_THICKNESS_IN.keys())[0],
    )
    finish = st.segmented_control(
        "Finish", list(PRICING["finish_per_sqft"].keys()),
        default="mill finish",
    )

    if finish == "powder coat (custom color)":
        color_hex = st.color_picker("Powder coat color", value="#2a4d69")
    else:
        color_hex = FINISH_COLORS[finish]

    st.subheader("Style options")
    num_draws = st.number_input(
        "Forming operations (draws/bends)", min_value=1, max_value=16, value=4, step=1,
        help="How many press-brake bends/draws it takes to form this case. More draws = more labor.",
    )
    handle_count = st.number_input("Handles", min_value=0, max_value=4, value=2, step=1)
    bumper_count = st.number_input("Corner bumpers", min_value=0, max_value=4, value=4, step=1)
    foam_interior = st.toggle("Foam interior insert", value=False)
    mounting_flanges = st.toggle("Welded mounting flanges (back, w/ bolt holes)", value=True)
    reinforced_opening = st.toggle("Reinforced opening (for latches/hinges)", value=True)
    rack_rails = st.toggle('19" rack rails inside', value=False)

if not material or not finish:
    st.info("Select a material and finish in the sidebar to see a diagram and quote.")
    st.stop()

spec = CaseSpec(
    width_in=width_in,
    height_in=height_in,
    depth_in=depth_in,
    material=material,
    finish=finish,
    num_draws=int(num_draws),
    handle_count=int(handle_count),
    bumper_count=int(bumper_count),
    foam_interior=foam_interior,
    rack_rails=rack_rails,
    reinforced_opening=reinforced_opening,
    mounting_flanges=mounting_flanges,
)

diagram_col, quote_col = st.columns([2, 1])

with diagram_col:
    fig = draw_case(spec, color_hex=color_hex)
    st.pyplot(fig)

with quote_col:
    st.subheader("Estimated quote")
    quote = compute_quote(spec)

    label_map = {
        "material": "Material",
        "labor": "Fabrication labor",
        "finish": "Finish upcharge",
        "handles": "Handles",
        "bumpers": "Corner bumpers",
        "foam_interior": "Foam interior",
        "rack_rails": "Rack rails",
        "reinforced_opening": "Reinforced opening",
        "mounting_flanges": "Mounting flanges",
    }
    for key, amount in quote.line_items.items():
        st.write(f"{label_map.get(key, key)}: ${amount:,.2f}")

    st.divider()
    st.write(f"Subtotal: ${quote.subtotal:,.2f}")
    st.write(f"Markup ({PRICING['markup_pct']:.0%}): ${quote.markup:,.2f}")
    st.metric("Total estimate", f"${quote.total:,.2f}")

    st.caption("Placeholder pricing — tune the constants in pricing.py against real shop costs.")

    st.divider()
    st.subheader("Similar past quotes")
    st.caption("Synthetic historical data — see generate_quote_history.py.")

    history = _load_quote_history()
    if not history:
        st.info("No quote history found. Run `python generate_quote_history.py` to build it.")
    else:
        thickness = MATERIAL_THICKNESS_IN[material]
        estimate = estimate_from_history(
            history, width_in=width_in, height_in=height_in, depth_in=depth_in,
            num_draws=int(num_draws), thickness_in=thickness,
        )
        if estimate is None:
            st.warning("No similar historical quotes found for this size/material combo.")
        else:
            st.write(f"Based on **{estimate.match_count}** similar past quotes:")
            st.write(
                f"Average: \\${estimate.avg_price:,.2f}  "
                f"(range \\${estimate.min_price:,.2f}\u2013\\${estimate.max_price:,.2f})"
            )
            st.progress(estimate.confidence, text=f"Confidence: {estimate.confidence:.0%}")
