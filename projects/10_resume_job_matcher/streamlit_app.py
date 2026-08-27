"""Résumé & job matcher UI. Two modes:

- Score one listing: paste a résumé + a job listing -> evidence-backed fit
  score, gaps, and honest suggestions.
- Search live jobs: paste a résumé, give keywords + a location -> live job
  search (job_search.py) with every posting scored and ranked.

Thin UI over the same functions the CLI uses. Needs ANTHROPIC_API_KEY in the
repo-root .env, same as every other entry point in this project.

    streamlit run streamlit_app.py
"""

from pathlib import Path

import streamlit as st

from job_search import search_jobs
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
    """Run the full chain for one listing. Cached on the input text."""
    resume = parse_resume(resume_text)
    job = parse_job(job_text)
    comparison = match_requirements(resume, job)
    return {
        "comparison": comparison,
        "report": build_report(comparison, resume, job),
    }


@st.cache_data(show_spinner=False, ttl="1h", max_entries=10)
def search_and_score(
    resume_text: str, keywords: str, location: str, radius: int, count: int
) -> list[dict]:
    """Search live postings, score each against the résumé, return best-first.

    The résumé is parsed once; each posting is parsed + matched + reported.
    """
    resume = parse_resume(resume_text)
    results = []
    for job in search_jobs(keywords, location, radius_miles=radius, count=count):
        parsed_job = parse_job(job["description"])
        comparison = match_requirements(resume, parsed_job)
        results.append(
            {
                "report": build_report(comparison, resume, parsed_job),
                "comparison": comparison,
                "url": job["url"],
                "grounding": job["grounding"],
            }
        )
    results.sort(key=lambda r: r["report"]["score"], reverse=True)
    return results


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


def _run(spinner_text, fn, *args):
    """Call an LLM-backed function, turning its errors into an st.error."""
    try:
        with st.spinner(spinner_text):
            return fn(*args)
    except RuntimeError as exc:  # missing ANTHROPIC_API_KEY, etc.
        st.error(str(exc))
        st.stop()
    except Exception as exc:  # noqa: BLE001 — surface anything else to the user
        st.error(f"Failed: {exc}")
        st.stop()


# =============================================================================
# Page
# =============================================================================

st.markdown("# :material/work_history: Résumé & job matcher")
st.caption(
    "A skill only counts as met if it can be quoted from the résumé — and "
    "suggestions never tell you to claim something you can't back up."
)

samples_exist = (DATA_DIR / "sample_resume.txt").exists()

st.markdown("**Résumé**")
if st.button(
    "Load sample résumé", icon=":material/description:", disabled=not samples_exist
):
    st.session_state.resume_text = _sample("sample_resume.txt")
st.text_area(
    "Résumé",
    key="resume_text",
    height=260,
    placeholder="Paste the full résumé text…",
    label_visibility="collapsed",
)
if not samples_exist:
    st.caption("Run `python sample_data.py` to enable the sample buttons.")

mode = st.segmented_control(
    "Mode",
    ["Score one listing", "Search live jobs"],
    default="Score one listing",
    key="mode",
    label_visibility="collapsed",
)

# ---------------------------------------------------------------- one listing
if mode == "Score one listing":
    if st.button(
        "Load sample job listing",
        icon=":material/work:",
        disabled=not samples_exist,
    ):
        st.session_state.job_text = _sample("sample_job.txt")
    st.text_area(
        "Job listing",
        key="job_text",
        height=260,
        placeholder="Paste the job listing…",
        label_visibility="collapsed",
    )
    if st.button("Evaluate fit", icon=":material/compare_arrows:", type="primary"):
        if not st.session_state.get("resume_text", "").strip() or not st.session_state.get(
            "job_text", ""
        ).strip():
            st.warning("Paste both a résumé and a job listing first.")
            st.stop()
        st.session_state.single = _run(
            "Parsing, matching requirements, writing suggestions…",
            evaluate,
            st.session_state.resume_text,
            st.session_state.job_text,
        )

    if "single" in st.session_state:
        result = st.session_state.single
        _render_report(result["comparison"], result["report"])
        st.download_button(
            "Download report as text",
            format_report(result["report"]),
            file_name="fit_report.txt",
            icon=":material/download:",
        )

# --------------------------------------------------------------- search jobs
else:
    with st.form("search", border=False):
        keywords = st.text_input(
            "Role / keywords", placeholder="e.g. junior AI engineer or Python developer"
        )
        loc_col, radius_col, count_col = st.columns([2, 1, 1])
        location = loc_col.text_input("Location", placeholder="e.g. Portland, OR")
        radius = radius_col.number_input("Radius (mi)", 5, 200, 25, step=5)
        count = count_col.number_input("Max postings", 3, 20, 10)
        searched = st.form_submit_button(
            "Search & score", icon=":material/travel_explore:", type="primary"
        )

    if searched:
        if not st.session_state.get("resume_text", "").strip():
            st.warning("Paste a résumé first.")
            st.stop()
        if not keywords.strip() or not location.strip():
            st.warning("Enter both keywords and a location.")
            st.stop()
        st.session_state.search = _run(
            f"Searching job boards for “{keywords}” near {location}…",
            search_and_score,
            st.session_state.resume_text,
            keywords,
            location,
            int(radius),
            int(count),
        )

    if "search" in st.session_state:
        results = st.session_state.search
        if not results:
            st.info("No postings found. Try broader keywords or a larger radius.")
        else:
            st.caption(f"{len(results)} postings, best fit first — select a row for the full report.")
            table = [
                {
                    "Score": r["report"]["score"],
                    "Band": r["report"]["band"],
                    "Title": r["report"]["job_title"],
                    "Company": r["report"]["company"],
                    "Grounding": r["grounding"],
                }
                for r in results
            ]
            event = st.dataframe(
                table,
                hide_index=True,
                on_select="rerun",
                selection_mode="single-row",
                key="search_table",
            )
            if event.selection.rows:
                chosen = results[event.selection.rows[0]]

                @st.dialog(
                    f"{chosen['report']['job_title']} · {chosen['report']['company']}",
                    width="large",
                )
                def _detail():
                    st.link_button(
                        "Open posting", chosen["url"], icon=":material/open_in_new:"
                    )
                    if chosen["grounding"] == "search snippet":
                        st.warning(
                            "Scored from a short search snippet, not the full "
                            "posting — treat this as directional."
                        )
                    _render_report(chosen["comparison"], chosen["report"])

                _detail()
