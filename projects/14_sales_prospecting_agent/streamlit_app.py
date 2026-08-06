"""Sales Prospecting Agent -- lead triage dashboard.

Browses the output of a pipeline.evaluate_lead() batch run (e.g.
run_full_exhibitor_list.py): a sortable, filterable leaderboard of scored
leads with a per-lead drill-down showing the full fit reason and where the
score was grounded (a specific PDF page, or a live web search).

Reads whatever lead CSVs already exist in data/ -- data/ is gitignored, so
this app never ships with real exhibitor data; run the pipeline first to
generate something to view.
"""

from pathlib import Path

import pandas as pd

import streamlit as st

st.set_page_config(
    page_title="Sales Prospecting Dashboard",
    page_icon=":material/storefront:",
    layout="wide",
)

DATA_DIR = Path(__file__).resolve().parent / "data"
PREFERRED_FILE = "full_real_exhibitor_run.csv"

BAND_ORDER = ["High", "Medium", "Low", "Unknown"]
BAND_BADGE_COLOR = {"High": "green", "Medium": "orange", "Low": "gray", "Unknown": "blue"}

# This project has produced two different CSV shapes across earlier slices
# -- crm_export.py's Title Case columns (demo_leads.csv,
# full_exhibitor_leads.csv) and run_full_exhibitor_list.py's snake_case
# columns (full_real_exhibitor_run.csv, which also adds `source`, not
# present in the older schema). Aliasing both into one canonical shape
# means the dashboard works with either file instead of only the newest.
COLUMN_ALIASES = {
    "company_name": ["company_name", "Company Name"],
    "score": ["score", "Fit Score"],
    "band": ["band", "Fit Band"],
    "fit_reason": ["fit_reason", "Fit Reason"],
    "state": ["state", "State"],
    "country": ["country", "Country"],
    "salesperson": ["salesperson_name", "Assigned Salesperson"],
    "territory": ["territory", "Territory"],
    "source": ["source"],
}


def _find_lead_csvs() -> list[Path]:
    if not DATA_DIR.exists():
        return []
    return sorted(DATA_DIR.glob("*.csv"), key=lambda p: p.stat().st_mtime, reverse=True)


@st.cache_data(show_spinner="Loading leads...")
def load_leads(csv_path: str) -> pd.DataFrame:
    raw = pd.read_csv(csv_path)
    normalized = pd.DataFrame(index=raw.index)
    for canonical, aliases in COLUMN_ALIASES.items():
        source_col = next((a for a in aliases if a in raw.columns), None)
        normalized[canonical] = raw[source_col] if source_col else pd.NA

    normalized["score"] = pd.to_numeric(normalized["score"], errors="coerce").fillna(0).astype(int)
    normalized["band"] = normalized["band"].fillna("Unknown")
    normalized["company_name"] = normalized["company_name"].fillna("Unknown")

    # A "Web search" source means score_fit only had a generic company-name
    # search to work with (corporate overview text, not a verified source
    # page) -- real, but weaker evidence than a PDF-grounded lead. Flagging
    # it here rather than trusting the score alone; see README's "Known
    # limitations" for the live Collins Aerospace/BAE Systems/Boeing SC
    # example that surfaced this.
    def _confidence(s):
        if pd.isna(s):
            return "Unknown"
        return "⚠️ Verify manually" if s == "Web search" else "📄 PDF-grounded"

    normalized["confidence"] = normalized["source"].apply(_confidence)
    return normalized.sort_values("score", ascending=False).reset_index(drop=True)


def render_lead_dialog(row: pd.Series) -> None:
    badge_color = BAND_BADGE_COLOR.get(row["band"], "gray")
    st.markdown(f":{badge_color}-badge[{row['band']} fit -- score {row['score']}]")

    if row["source"] == "Web search":
        st.warning(
            "Score is directional only -- grounded in a generic company-name "
            "search (corporate overview text), not a verified product/spec "
            "source. Confirm fit manually before treating this as a "
            "qualified lead."
        )

    st.markdown("**Fit reason**")
    st.write(row["fit_reason"] if pd.notna(row["fit_reason"]) else "Not available")

    col1, col2 = st.columns(2)
    with col1:
        st.markdown("**Location**")
        location = ", ".join(
            str(v) for v in (row["state"], row["country"]) if pd.notna(v) and str(v).strip()
        )
        st.write(location or "Not found")

        st.markdown("**Salesperson**")
        st.write(row["salesperson"] if pd.notna(row["salesperson"]) else "Not assigned")
    with col2:
        st.markdown("**Territory**")
        st.write(row["territory"] if pd.notna(row["territory"]) else "Not found")

        if pd.notna(row["source"]):
            st.markdown("**Source**")
            st.write(row["source"])


# =============================================================================
# Page layout
# =============================================================================

st.markdown("# :material/storefront: Sales prospecting dashboard")
st.caption(
    "Triaged leads from a trade-show exhibitor list -- fit score, reason, "
    "and where each score was grounded."
)

csv_files = _find_lead_csvs()
if not csv_files:
    st.warning(
        "No lead CSVs found in `data/`. Run `python run_full_exhibitor_list.py` "
        "(needs a real exhibitor PDF -- see the README) to generate one, or "
        "`python generate_sample_data.py` for fictional sample data."
    )
    st.stop()

default_index = next(
    (i for i, p in enumerate(csv_files) if p.name == PREFERRED_FILE), 0
)
selected_file = st.selectbox(
    "Lead file", options=csv_files, index=default_index, format_func=lambda p: p.name
)

leads = load_leads(str(selected_file))
if leads.empty:
    st.warning("This file has no leads.")
    st.stop()

# KPI row
band_counts = leads["band"].value_counts()
kpi_cols = st.columns(len(BAND_ORDER) + 1)
with kpi_cols[0]:
    st.metric("Total leads", len(leads))
for col, band in zip(kpi_cols[1:], BAND_ORDER):
    with col:
        st.metric(band, int(band_counts.get(band, 0)))

if leads["source"].notna().any():
    grounded = int((leads["source"].notna() & (leads["source"] != "Web search")).sum())
    st.caption(
        f":material/verified: {grounded} of {len(leads)} leads grounded directly from a "
        f"PDF page -- no live search needed; {len(leads) - grounded} used live web search."
    )

# Filters
with st.container(border=True):
    st.markdown("**Filters**")
    band_filter = st.pills(
        "Fit band", options=BAND_ORDER, default=BAND_ORDER, selection_mode="multi"
    )
    search = st.text_input("Search company name", placeholder="e.g. Acme")

filtered = leads[leads["band"].isin(band_filter or BAND_ORDER)]
if search:
    filtered = filtered[filtered["company_name"].str.contains(search, case=False, na=False)]

# Fit distribution chart
with st.container(border=True):
    st.markdown("**Fit distribution**")
    chart_data = (
        filtered["band"].value_counts().reindex(BAND_ORDER).fillna(0).reset_index()
    )
    chart_data.columns = ["band", "count"]
    st.bar_chart(chart_data, x="band", y="count", height=200)

# Leads table
with st.container(border=True):
    st.markdown(f"**Leads ({len(filtered)})**")
    selection = st.dataframe(
        filtered,
        column_config={
            "company_name": st.column_config.TextColumn(
                "Company (click for details)", width="medium"
            ),
            "score": st.column_config.NumberColumn("Score", format="%d"),
            "band": st.column_config.TextColumn("Band", width="small"),
            "confidence": st.column_config.TextColumn("Confidence", width="small"),
            "fit_reason": st.column_config.TextColumn("Fit reason", width="large"),
            "salesperson": st.column_config.TextColumn("Salesperson", width="small"),
            "territory": st.column_config.TextColumn("Territory", width="small"),
            "source": st.column_config.TextColumn("Source", width="medium"),
        },
        column_order=[
            "company_name",
            "score",
            "band",
            "confidence",
            "fit_reason",
            "salesperson",
            "territory",
            "source",
        ],
        hide_index=True,
        on_select="rerun",
        selection_mode="single-row",
        key="leads_table",
    )

if selection.selection.rows:
    row_idx = selection.selection.rows[0]
    row = filtered.iloc[row_idx]

    @st.dialog(str(row["company_name"]), width="large")
    def show_lead_dialog() -> None:
        render_lead_dialog(row)

    show_lead_dialog()
