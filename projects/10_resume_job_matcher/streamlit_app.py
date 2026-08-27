"""Résumé & job matcher — paste a résumé and a job listing, get an
evidence-backed fit score, the gaps, and honest suggestions.

Thin UI over the same functions the CLI uses (parse_resume / parse_job /
match_requirements / build_report). Needs ANTHROPIC_API_KEY in the repo-root
.env, same as every other entry point in this project.

    streamlit run streamlit_app.py
"""

from pathlib import Path

import streamlit as st

from match import match_requirements
from parse_job import parse_job
from parse_resume import parse_resume
from report import build_report, format_report

st.set_page_config(
    page_title="Résumé & job matcher",
    page_icon=":material/work_history:",
    layout="wide",
)

DATA_DIR = Path(__file__).resolve().parent / "data"

BAND_COLOR = {"Strong": "green", "Possible": "orange", "Weak": "red"}
ASSESSMENT = {
    "surface_it_better": ("blue", "Surface it better"),
    "adjacent_experience": ("violet", "Adjacent experience"),
    "genuine_gap": ("red", "Genuine gap"),
}


@st.cache_data(show_spinner=False, ttl="1h", max_entries=50)
def evaluate(resume_text: str, job_text: str) -> dict:
    """Run the full chain. Cached so re-submitting identical text is free."""
    resume = parse_resume(resume_text)
    job = parse_job(job_text)
    comparison = match_requirements(resume, job)
    return {
        "comparison": comparison,
        "report": build_report(comparison, resume, job),
    }


def _sample(name: str) -> str:
    path = DATA_DIR / name
    return path.read_text() if path.exists() else ""


def _render_skill_evidence(comparison: dict) -> None:
    for label, rows in (
        ("Required", comparison["required_skills"]),
        ("Preferred", comparison["preferred_skills"]),
    ):
        if not rows:
            continue
        st.markdown(f"**{label}**")
        for row in rows:
            icon = ":material/check_circle:" if row["met"] else ":material/cancel:"
            st.markdown(f"{icon} {row['skill']}")
            if row["evidence"]:
                st.caption(f"“{row['evidence']}”")


def _render_report(comparison: dict, report: dict) -> None:
    heading = report["job_title"]
    if report.get("company"):
        heading += f" · {report['company']}"
    st.markdown(f"## {heading}")

    score_col, breakdown_col = st.columns([1, 2], gap="large")
    with score_col:
        st.metric("Fit score", f"{report['score']} / 100")
        st.badge(f"{report['band']} fit", color=BAND_COLOR.get(report["band"], "gray"))
    with breakdown_col:
        for component in report["breakdown"]:
            ceiling = component["max_points"] or 1
            st.progress(
                min(component["points"] / ceiling, 1.0),
                text=f"{component['component']} — {component['points']:g}/{component['max_points']}",
            )
            st.caption(component["detail"])

    gaps = report["gaps"]
    if report["suggestions"] or any(
        [
            gaps["unmet_required_skills"],
            gaps["unmet_preferred_skills"],
            gaps["years_short"],
            gaps["education_unmet"],
        ]
    ):
        st.markdown("### Gaps")
        with st.container(border=True):
            if gaps["unmet_required_skills"]:
                st.markdown(
                    "Required, not shown: "
                    + " ".join(f":red-badge[{s}]" for s in gaps["unmet_required_skills"])
                )
            if gaps["unmet_preferred_skills"]:
                st.markdown(
                    "Preferred, not shown: "
                    + " ".join(
                        f":gray-badge[{s}]" for s in gaps["unmet_preferred_skills"]
                    )
                )
            if gaps["years_short"]:
                st.markdown(
                    f":orange-badge[Years: {gaps['years_short']['candidate']} "
                    f"vs {gaps['years_short']['required']} required]"
                )
            if gaps["education_unmet"]:
                st.markdown(":orange-badge[Education requirement not met]")

    if report["suggestions"]:
        st.markdown("### Suggestions")
        for item in report["suggestions"]:
            color, label = ASSESSMENT.get(item["assessment"], ("gray", item["assessment"]))
            with st.container(border=True):
                st.markdown(f":{color}-badge[{label}] &nbsp; **{item['gap']}**")
                st.write(item["suggestion"])

    st.markdown("### Overall")
    st.info(report["overall"])

    with st.expander("Skill-by-skill evidence"):
        _render_skill_evidence(comparison)


# =============================================================================
# Page
# =============================================================================

st.markdown("# :material/work_history: Résumé & job matcher")
st.caption(
    "Paste a résumé and a job listing. Every skill is only counted as met if it "
    "can be quoted from the résumé — and suggestions never tell you to claim "
    "something you can't back up."
)

samples_exist = (DATA_DIR / "sample_resume.txt").exists()
with st.container(horizontal=True):
    if st.button(
        "Load sample résumé",
        icon=":material/description:",
        disabled=not samples_exist,
    ):
        st.session_state.resume_text = _sample("sample_resume.txt")
    if st.button(
        "Load sample job listing",
        icon=":material/work:",
        disabled=not samples_exist,
    ):
        st.session_state.job_text = _sample("sample_job.txt")
if not samples_exist:
    st.caption("Run `python sample_data.py` to enable the sample buttons.")

with st.form("evaluate", border=False):
    resume_col, job_col = st.columns(2, gap="large")
    with resume_col:
        st.text_area(
            "Résumé",
            key="resume_text",
            height=340,
            placeholder="Paste the full résumé text…",
        )
    with job_col:
        st.text_area(
            "Job listing",
            key="job_text",
            height=340,
            placeholder="Paste the job listing…",
        )
    submitted = st.form_submit_button(
        "Evaluate fit", icon=":material/compare_arrows:", type="primary"
    )

if submitted:
    resume_text = st.session_state.get("resume_text", "").strip()
    job_text = st.session_state.get("job_text", "").strip()
    if not resume_text or not job_text:
        st.warning("Paste both a résumé and a job listing first.")
        st.stop()
    try:
        with st.spinner("Parsing, matching requirements, writing suggestions…"):
            st.session_state.result = evaluate(resume_text, job_text)
    except RuntimeError as exc:
        st.error(f"{exc}")
        st.stop()
    except Exception as exc:  # noqa: BLE001 — surface anything else to the user
        st.error(f"Evaluation failed: {exc}")
        st.stop()

if "result" in st.session_state:
    result = st.session_state.result
    _render_report(result["comparison"], result["report"])
    st.download_button(
        "Download report as text",
        format_report(result["report"]),
        file_name="fit_report.txt",
        icon=":material/download:",
    )
