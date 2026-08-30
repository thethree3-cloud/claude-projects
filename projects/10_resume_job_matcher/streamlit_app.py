"""Résumé & job matcher UI. Two modes:

- Score one listing: paste a résumé + a job listing -> evidence-backed fit
  score, gaps, and honest suggestions.
- Search live jobs: paste a résumé, give keywords + a location -> live job
  search (job_search.py) with every posting scored and ranked.

Thin UI over the same functions the CLI uses. Needs ANTHROPIC_API_KEY in the
repo-root .env, same as every other entry point in this project.

    streamlit run streamlit_app.py
"""

import datetime
import os
from pathlib import Path

import streamlit as st

import applications
import job_sites
from cover_letter import build_cover_letter
from job_search import search_jobs
from match import match_requirements
from parse_job import parse_job
from parse_resume import parse_resume
from report import build_report, format_report
from resume_export import to_docx, to_pdf
from resume_source import extract_text
from tailor_resume import build_tailored_resume

st.set_page_config(
    page_title="Résumé & job matcher",
    page_icon=":material/work_history:",
    layout="wide",
)

DATA_DIR = Path(__file__).resolve().parent / "data"
APPLICATIONS_DB = Path(os.environ.get("APPLICATIONS_DB", DATA_DIR / "applications.db"))

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
        "resume": resume,
        "job": job,
        "comparison": comparison,
        "report": build_report(comparison, resume, job),
    }


@st.cache_data(show_spinner=False, ttl="1h", max_entries=20)
def tailor(resume_text: str, job_text: str) -> dict:
    """Reframe the résumé for one listing. Cached on the input text.

    Re-parses rather than leaning on `evaluate`'s cache so the two features
    stay independent; the parse calls are cheap.
    """
    resume = parse_resume(resume_text)
    job = parse_job(job_text)
    comparison = match_requirements(resume, job)
    return build_tailored_resume(comparison, resume, job)


@st.cache_data(show_spinner=False, ttl="1h", max_entries=20)
def cover_letter(resume_text: str, job_text: str) -> dict:
    """Draft a grounded cover letter for one listing. Cached on input text."""
    resume = parse_resume(resume_text)
    job = parse_job(job_text)
    comparison = match_requirements(resume, job)
    return build_cover_letter(comparison, resume, job)


@st.cache_data(show_spinner=False, ttl="1h", max_entries=10)
def search_and_score(
    resume_text: str,
    keywords: str,
    location: str,
    radius: int,
    count: int,
    sites: tuple | None = None,
) -> list[dict]:
    """Search live postings, score each against the résumé, return best-first.

    The résumé is parsed once; each posting is parsed + matched + reported.
    `sites` (a tuple, so it's cache-hashable) overrides the board list.
    """
    resume = parse_resume(resume_text)
    results = []
    for job in search_jobs(
        keywords, location, radius_miles=radius, count=count,
        sites=list(sites) if sites else None,
    ):
        job_text = (
            f"{job['title']}\n{job['company']}\n{job['location']}\n\n{job['description']}"
        )
        parsed_job = parse_job(job_text)
        parsed_job["title"] = job["title"] or parsed_job["title"]
        parsed_job["company"] = job["company"] or parsed_job["company"]
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
upload_col, sample_col = st.columns([3, 1])
upload = upload_col.file_uploader(
    "Upload a résumé file",
    type=["pdf", "docx", "txt", "md"],
    help="PDF, Word (.docx), or plain text. The extracted text lands in the box below — edit it there.",
)
if upload is not None and upload.file_id != st.session_state.get("resume_file_id"):
    try:
        st.session_state.resume_text = extract_text(upload.getvalue(), upload.name)
        st.session_state.resume_file_id = upload.file_id
        for stale in ("single", "tailored", "cover"):
            st.session_state.pop(stale, None)
    except (ValueError, RuntimeError) as exc:
        st.error(str(exc))
if sample_col.button(
    "Load sample", icon=":material/description:", disabled=not samples_exist
):
    st.session_state.resume_text = _sample("sample_resume.txt")
st.text_area(
    "Résumé",
    key="resume_text",
    height=260,
    placeholder="Paste the full résumé text, or upload a file above…",
    label_visibility="collapsed",
)
if not samples_exist:
    st.caption("Run `python sample_data.py` to enable the sample button.")

mode = st.segmented_control(
    "Mode",
    ["Score one listing", "Search live jobs", "Applications"],
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
        for stale in ("tailored", "cover"):  # stale for the new listing
            st.session_state.pop(stale, None)

    if "single" in st.session_state:
        result = st.session_state.single
        _render_report(result["comparison"], result["report"])
        st.download_button(
            "Download report as text",
            format_report(result["report"]),
            file_name="fit_report.txt",
            icon=":material/download:",
        )

        st.divider()
        st.markdown("### Tailored résumé")
        st.caption(
            "Reframes your résumé for this listing — rewrites the summary, "
            "leads with the job-relevant roles and skills, and re-words your "
            "existing bullets in the listing's language. It never adds a "
            "skill, employer, or accomplishment your résumé doesn't already "
            "show, and a second pass drops any bullet that drifted."
        )
        if st.button("Build tailored résumé", icon=":material/edit_document:"):
            st.session_state.tailored = _run(
                "Reframing your résumé, then checking every bullet…",
                tailor,
                st.session_state.resume_text,
                st.session_state.job_text,
            )

        if "tailored" in st.session_state:
            tailored = st.session_state.tailored

            flags = tailored.get("flags", [])
            if flags:
                st.warning(
                    f"Dropped {len(flags)} bullet(s) that claimed more than your "
                    "résumé supports:"
                )
                for flag in flags:
                    with st.container(border=True):
                        st.markdown(f"**{flag['role']}** — {flag['issue']}")
                        st.caption(f"removed: “{flag['bullet']}”")

            if tailored["changes"]:
                with st.expander("What changed", expanded=not flags):
                    for change in tailored["changes"]:
                        st.markdown(f"- {change}")

            diff = tailored.get("diff", [])
            if diff:
                with st.expander("Before / after, bullet by bullet"):
                    for role in diff:
                        st.markdown(f"**{role['title']} — {role['organization']}**")
                        before_col, after_col = st.columns(2)
                        before_col.caption("Original")
                        for bullet in role["original"] or ["—"]:
                            before_col.markdown(f"- {bullet}")
                        after_col.caption("Tailored")
                        for bullet in role["tailored"] or ["—"]:
                            after_col.markdown(f"- {bullet}")

            st.markdown("**Download**")
            pdf_col, docx_col, md_col = st.columns(3)
            resume_dict = tailored.get("resume") or {}
            if resume_dict:
                pdf_col.download_button(
                    "PDF",
                    to_pdf(resume_dict),
                    file_name="tailored_resume.pdf",
                    mime="application/pdf",
                    icon=":material/picture_as_pdf:",
                    type="primary",
                    use_container_width=True,
                )
                docx_col.download_button(
                    "Word",
                    to_docx(resume_dict),
                    file_name="tailored_resume.docx",
                    mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    icon=":material/description:",
                    use_container_width=True,
                )
            md_col.download_button(
                "Markdown",
                tailored["markdown"],
                file_name="tailored_resume.md",
                icon=":material/code:",
                use_container_width=True,
            )
            with st.container(border=True):
                st.markdown(tailored["markdown"])

        st.divider()
        st.markdown("### Cover letter")
        st.caption(
            "Three short paragraphs, first person, grounded the same way — it "
            "leans on the skills your résumé evidences, is told not to claim "
            "the gaps, and a second pass flags any sentence the résumé "
            "doesn't back up (prose isn't auto-edited — you fix or cut it)."
        )
        if st.button("Write cover letter", icon=":material/mail:"):
            st.session_state.cover = _run(
                "Drafting the letter, then checking every claim…",
                cover_letter,
                st.session_state.resume_text,
                st.session_state.job_text,
            )

        if "cover" in st.session_state:
            cover = st.session_state.cover
            if cover["flags"]:
                st.warning(
                    f"{len(cover['flags'])} claim(s) the résumé doesn't clearly "
                    "support — edit or cut these before sending:"
                )
                for flag in cover["flags"]:
                    with st.container(border=True):
                        st.markdown(f"**{flag['claim']}**")
                        st.caption(flag["issue"])
            st.download_button(
                "Download cover letter",
                cover["text"],
                file_name="cover_letter.txt",
                icon=":material/download:",
                type="primary",
            )
            with st.container(border=True):
                st.text(cover["text"])
            with st.expander("Every claim, and the résumé line behind it"):
                for claim in cover["claims"]:
                    st.markdown(f"- {claim['claim']}")
                    st.caption(f"“{claim['evidence']}”")

# --------------------------------------------------------------- search jobs
elif mode == "Search live jobs":
    area = st.selectbox("Search area", ["Custom", *job_sites.LOCAL_PRESETS])
    preset = job_sites.LOCAL_PRESETS.get(area)
    if preset:
        st.caption(
            f":material/place: {preset['location']} · {preset['radius_miles']} mi · "
            f"the standard boards plus {len(preset['extra_sites'])} local Utah/SLC "
            "boards (state jobs, Salt Lake County, KSL, Silicon Slopes, U of U)."
        )

    with st.form("search", border=False):
        keywords = st.text_input(
            "Role / keywords", placeholder="e.g. junior AI engineer or Python developer"
        )
        if preset:
            location = preset["location"]
            radius = preset["radius_miles"]
            count = st.number_input("Max postings", 3, 20, 10)
        else:
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
        if not keywords.strip() or not str(location).strip():
            st.warning("Enter both keywords and a location.")
            st.stop()
        sites = tuple(job_sites.preset_sites(area)) if preset else None
        st.session_state.search = _run(
            f"Searching job boards for “{keywords}” near {location}…",
            search_and_score,
            st.session_state.resume_text,
            keywords,
            location,
            int(radius),
            int(count),
            sites,
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

# -------------------------------------------------------------- applications
else:
    conn = applications.connect(APPLICATIONS_DB)

    single = st.session_state.get("single")
    if single:
        rpt = single["report"]
        listing = rpt["job_title"] + (
            f" · {rpt['company']}" if rpt.get("company") else ""
        )
        variant = "tailored" if "tailored" in st.session_state else "base"
        st.caption(f"Last scored: **{listing}**")
        if st.button(
            f"Log this application ({variant} résumé)", icon=":material/add:"
        ):
            applications.add_application(
                conn,
                company=rpt.get("company") or "—",
                role=rpt["job_title"] or "—",
                resume_variant=variant,
            )
            st.toast("Logged with today's date.")
            st.rerun()

    buckets = applications.agenda(conn)
    st.markdown("### Coming up")
    if not any(buckets.values()):
        st.caption("Nothing scheduled — add a next-action date to see it here.")
    for key, heading in (
        ("overdue", ":red[Overdue]"),
        ("this_week", ":orange[This week]"),
        ("later", "Later"),
    ):
        if not buckets[key]:
            continue
        st.markdown(f"**{heading}**")
        for row in buckets[key]:
            st.markdown(
                f"- `{row['next_action_on']}` &nbsp; **{row['company']}** — "
                f"{row['role']} &nbsp;·&nbsp; {row['next_action'] or 'follow up'}"
            )

    st.divider()

    with st.expander("Add an application", icon=":material/note_add:"):
        with st.form("add_application", clear_on_submit=True):
            name_col, role_col = st.columns(2)
            new_company = name_col.text_input("Company")
            new_role = role_col.text_input("Role")
            date_col, var_col = st.columns(2)
            new_applied = date_col.date_input("Applied on", value="today")
            new_variant = var_col.text_input(
                "Résumé used", placeholder="tailored / base / v2"
            )
            status_col, next_col = st.columns(2)
            new_status = status_col.selectbox("Status", applications.STATUSES)
            new_next_on = next_col.date_input("Next action on", value=None)
            new_next = st.text_input(
                "Next action", placeholder="follow up, thank-you note…"
            )
            new_link = st.text_input("Link")
            new_notes = st.text_area("Notes")
            if st.form_submit_button("Add", type="primary"):
                if not new_company.strip() or not new_role.strip():
                    st.warning("Company and role are required.")
                else:
                    applications.add_application(
                        conn,
                        company=new_company.strip(),
                        role=new_role.strip(),
                        applied_on=new_applied.isoformat(),
                        resume_variant=new_variant.strip(),
                        status=new_status,
                        next_action=new_next.strip(),
                        next_action_on=(
                            new_next_on.isoformat() if new_next_on else None
                        ),
                        link=new_link.strip(),
                        notes=new_notes.strip(),
                    )
                    st.rerun()

    apps = applications.list_applications(conn)
    if not apps:
        st.info("No applications logged yet.")
    else:
        st.caption(f"{len(apps)} logged — select a row to update it.")
        event = st.dataframe(
            [
                {
                    "Company": a["company"],
                    "Role": a["role"],
                    "Applied": a["applied_on"],
                    "Résumé": a["resume_variant"],
                    "Status": a["status"],
                    "Next": a["next_action_on"] or "",
                }
                for a in apps
            ],
            hide_index=True,
            on_select="rerun",
            selection_mode="single-row",
            key="apps_table",
        )
        if event.selection.rows:
            app = apps[event.selection.rows[0]]

            @st.dialog(f"{app['company']} — {app['role']}")
            def _edit_application():
                status = st.selectbox(
                    "Status",
                    applications.STATUSES,
                    index=applications.STATUSES.index(app["status"]),
                )
                action = st.text_input("Next action", app["next_action"])
                current = (
                    datetime.date.fromisoformat(app["next_action_on"])
                    if app["next_action_on"]
                    else None
                )
                action_on = st.date_input("Next action on", value=current)
                notes = st.text_area("Notes", app["notes"])
                if app["link"]:
                    st.link_button("Open posting", app["link"])
                save_col, delete_col = st.columns(2)
                if save_col.button("Save", type="primary"):
                    applications.update_application(
                        conn,
                        app["id"],
                        status=status,
                        next_action=action.strip(),
                        next_action_on=(
                            action_on.isoformat() if action_on else None
                        ),
                        notes=notes.strip(),
                    )
                    st.rerun()
                if delete_col.button("Delete"):
                    applications.delete_application(conn, app["id"])
                    st.rerun()

            _edit_application()
