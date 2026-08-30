import json
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import job_search
import job_sites


class JobSitesTests(unittest.TestCase):
    def test_all_sites_has_no_duplicates(self):
        self.assertEqual(
            len(job_sites.ALL_JOB_SITES), len(set(job_sites.ALL_JOB_SITES))
        )

    def test_fetchable_is_subset_of_all(self):
        self.assertTrue(set(job_sites.FETCHABLE) <= set(job_sites.ALL_JOB_SITES))

    def test_sites_are_bare_hostnames(self):
        every_site = job_sites.ALL_JOB_SITES + [
            s for p in job_sites.LOCAL_PRESETS.values() for s in p["extra_sites"]
        ]
        for site in every_site:
            self.assertNotIn("/", site)
            self.assertFalse(site.startswith("http"))
            self.assertIn(".", site)

    def test_salt_lake_city_preset_shape(self):
        preset = job_sites.LOCAL_PRESETS["Salt Lake City"]
        self.assertEqual(preset["radius_miles"], 25)
        self.assertIn("Utah", preset["location"])
        self.assertTrue(preset["extra_sites"])

    def test_preset_sites_unions_all_plus_local_without_dupes(self):
        sites = job_sites.preset_sites("Salt Lake City")
        self.assertEqual(len(sites), len(set(sites)))
        self.assertTrue(set(job_sites.ALL_JOB_SITES) <= set(sites))
        self.assertIn("jobs.ksl.com", sites)
        self.assertIn("jobs.utah.gov", sites)


def _resp(content, stop_reason="end_turn"):
    return SimpleNamespace(content=content, stop_reason=stop_reason)


def _text(t, stop_reason="end_turn"):
    return _resp([SimpleNamespace(type="text", text=t)], stop_reason)


FINDINGS = (
    "Junior AI Engineer at Northwind, Portland OR, "
    "https://jobs.lever.co/northwind/1, FULL POSTING, builds LLM features, 2+ yrs Python."
)

JOBS_JSON = {
    "jobs": [
        {
            "title": "Junior AI Engineer",
            "company": "Northwind",
            "location": "Portland, OR",
            "url": "https://jobs.lever.co/northwind/1",
            "description": "Build LLM-backed features. 2+ years Python.",
            "grounding": "full posting",
        }
    ]
}


class SearchJobsTests(unittest.TestCase):
    @patch("job_search.get_client")
    def test_search_then_structure_in_two_calls(self, mock_get_client):
        mock_client = MagicMock()
        mock_client.messages.create.side_effect = [
            _text(FINDINGS),                 # call 1: agentic search
            _text(json.dumps(JOBS_JSON)),    # call 2: structuring
        ]
        mock_get_client.return_value = mock_client

        jobs = job_search.search_jobs("AI engineer", "Portland, OR")

        self.assertEqual(mock_client.messages.create.call_count, 2)
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]["company"], "Northwind")
        self.assertEqual(jobs[0]["grounding"], "full posting")

    @patch("job_search.get_client")
    def test_resends_on_pause_turn_before_structuring(self, mock_get_client):
        mock_client = MagicMock()
        mock_client.messages.create.side_effect = [
            _resp([SimpleNamespace(type="server_tool_use", id="x")], stop_reason="pause_turn"),
            _text(FINDINGS),                 # resumed search -> findings
            _text(json.dumps(JOBS_JSON)),    # structuring
        ]
        mock_get_client.return_value = mock_client

        jobs = job_search.search_jobs("AI engineer", "Portland, OR")

        self.assertEqual(mock_client.messages.create.call_count, 3)
        self.assertEqual(len(jobs), 1)

    @patch("job_search.get_client")
    def test_first_call_forces_tool_use_and_scopes_domains(self, mock_get_client):
        mock_client = MagicMock()
        mock_client.messages.create.side_effect = [
            _text(FINDINGS),
            _text(json.dumps({"jobs": []})),
        ]
        mock_get_client.return_value = mock_client

        job_search.search_jobs("x", "y", sites=["jobs.lever.co"])

        _, kwargs = mock_client.messages.create.call_args_list[0]
        self.assertEqual(kwargs["tool_choice"], {"type": "any"})
        self.assertEqual(kwargs["tools"][0]["allowed_domains"], ["jobs.lever.co"])
        self.assertEqual(kwargs["tools"][0]["type"], "web_search_20250305")
        self.assertEqual(kwargs["tools"][1]["type"], "web_fetch_20250910")

    @patch("job_search.get_client")
    def test_structuring_call_has_no_tools_and_uses_schema(self, mock_get_client):
        mock_client = MagicMock()
        mock_client.messages.create.side_effect = [
            _text(FINDINGS),
            _text(json.dumps({"jobs": []})),
        ]
        mock_get_client.return_value = mock_client

        job_search.search_jobs("x", "y")

        _, structure_kwargs = mock_client.messages.create.call_args_list[1]
        self.assertNotIn("tools", structure_kwargs)
        self.assertNotIn("tool_choice", structure_kwargs)
        self.assertIn("output_config", structure_kwargs)

    @patch("job_search.get_client")
    def test_empty_findings_skip_structuring(self, mock_get_client):
        mock_client = MagicMock()
        mock_client.messages.create.return_value = _text("")
        mock_get_client.return_value = mock_client

        self.assertEqual(job_search.search_jobs("x", "y"), [])
        self.assertEqual(mock_client.messages.create.call_count, 1)

    @patch("job_search.get_client")
    def test_stops_after_max_rounds(self, mock_get_client):
        mock_client = MagicMock()
        mock_client.messages.create.return_value = _resp([], stop_reason="pause_turn")
        mock_get_client.return_value = mock_client

        jobs = job_search.search_jobs("x", "y")

        self.assertEqual(jobs, [])
        # MAX_TOOL_ROUNDS + 1 search calls; structuring is skipped (no findings)
        self.assertEqual(
            mock_client.messages.create.call_count, job_search.MAX_TOOL_ROUNDS + 1
        )


class FetchPostingTests(unittest.TestCase):
    @patch("job_search.get_client")
    def test_forces_web_fetch_and_returns_text(self, mock_get_client):
        mock_client = MagicMock()
        mock_client.messages.create.return_value = _text(
            "Data Analyst — Cedar Ridge — Portland, OR\nRequirements: SQL, Excel, pandas."
        )
        mock_get_client.return_value = mock_client

        text = job_search.fetch_posting("https://boards.greenhouse.io/x/jobs/1")

        _, kwargs = mock_client.messages.create.call_args
        self.assertEqual(kwargs["tool_choice"], {"type": "tool", "name": "web_fetch"})
        self.assertEqual(kwargs["tools"][0]["type"], "web_fetch_20250910")
        self.assertIn("https://boards.greenhouse.io/x/jobs/1", kwargs["messages"][0]["content"])
        self.assertIn("SQL, Excel, pandas", text)

    @patch("job_search.get_client")
    def test_resends_while_the_fetch_runs(self, mock_get_client):
        mock_client = MagicMock()
        mock_client.messages.create.side_effect = [
            _resp([SimpleNamespace(type="server_tool_use", id="x")], stop_reason="pause_turn"),
            _text("Data Analyst posting text."),
        ]
        mock_get_client.return_value = mock_client

        text = job_search.fetch_posting("https://x/1")
        self.assertEqual(mock_client.messages.create.call_count, 2)
        self.assertIn("Data Analyst", text)

    @patch("job_search.get_client")
    def test_not_a_posting_returns_empty(self, mock_get_client):
        mock_client = MagicMock()
        mock_client.messages.create.return_value = _text("NOT A POSTING")
        mock_get_client.return_value = mock_client

        self.assertEqual(job_search.fetch_posting("https://indeed.com/jobs?q=analyst"), "")


if __name__ == "__main__":
    unittest.main()
