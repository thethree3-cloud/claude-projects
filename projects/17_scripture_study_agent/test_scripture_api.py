"""Offline tests for scripture_api.

No network: every test stubs the module-level requests Session so we're
checking URL construction, parameter passing, and response handling -- not
the live API. A separate live smoke check lives in
``scripture_api.__main__`` and in the README.
"""

import unittest
from unittest.mock import MagicMock, patch

import scripture_api as s


class FakeResponse:
    def __init__(self, payload, status_code=200, is_json=True):
        self._payload = payload
        self.status_code = status_code
        self.ok = 200 <= status_code < 300
        self.url = "https://example.test/endpoint"
        self._is_json = is_json
        self.request = MagicMock(method="GET")

    def json(self):
        if not self._is_json:
            raise ValueError("no json")
        return self._payload


def stub_get(payload, **kw):
    """Patch _session.get to return FakeResponse(payload); capture the call."""
    fake = FakeResponse(payload, **kw)
    mock = MagicMock(return_value=fake)
    return patch.object(s._session, "get", mock), mock


def stub_post(payload, **kw):
    fake = FakeResponse(payload, **kw)
    mock = MagicMock(return_value=fake)
    return patch.object(s._session, "post", mock), mock


class ParseTests(unittest.TestCase):
    def test_error_payload_raises_even_on_200(self):
        ctx, _ = stub_get({"error": "Must provide a valid reference"})
        with ctx:
            with self.assertRaises(s.ScriptureAPIError):
                s.resolve_reference("")

    def test_non_json_raises(self):
        ctx, _ = stub_get(None, is_json=False)
        with ctx:
            with self.assertRaises(s.ScriptureAPIError):
                s.get_chapter("isaiah", 1)

    def test_non_2xx_raises(self):
        ctx, _ = stub_get({"foo": "bar"}, status_code=500)
        with ctx:
            with self.assertRaises(s.ScriptureAPIError):
                s.get_chapter("isaiah", 1)

    def test_ok_payload_returned(self):
        ctx, _ = stub_get({"valid": True, "prettyString": "Isaiah 1:1"})
        with ctx:
            out = s.resolve_reference("Isaiah 1:1")
        self.assertTrue(out["valid"])


class UrlTests(unittest.TestCase):
    def test_resolve_reference_url_and_param(self):
        ctx, mock = stub_get({"valid": True})
        with ctx:
            s.resolve_reference("Isaiah 1:1")
        url, kwargs = mock.call_args[0][0], mock.call_args[1]
        self.assertEqual(url, f"{s.SCRIPTURES_BASE}/referencesParser")
        self.assertEqual(kwargs["params"], {"reference": "Isaiah 1:1"})

    def test_get_verse_url(self):
        ctx, mock = stub_get({"text": "..."})
        with ctx:
            s.get_verse("isaiah", 1, 1)
        self.assertEqual(mock.call_args[0][0], f"{s.SCRIPTURES_BASE}/book/isaiah/1/1")

    def test_get_chapter_url(self):
        ctx, mock = stub_get({"chapter": {}})
        with ctx:
            s.get_chapter("1nephi", 3)
        self.assertEqual(mock.call_args[0][0], f"{s.SCRIPTURES_BASE}/book/1nephi/3")

    def test_study_help_entry_url(self):
        ctx, mock = stub_get({"_id": "tg-faith"})
        with ctx:
            s.get_study_help_entry("tg-faith")
        self.assertEqual(mock.call_args[0][0], f"{s.STUDY_HELPS_BASE}/entry/tg-faith")

    def test_list_study_help_entries_omits_q_when_none(self):
        ctx, mock = stub_get({"entries": []})
        with ctx:
            s.list_study_help_entries("tg")
        self.assertNotIn("q", mock.call_args[1]["params"])

    def test_list_study_help_entries_includes_q(self):
        ctx, mock = stub_get({"entries": []})
        with ctx:
            s.list_study_help_entries("tg", q="faith")
        self.assertEqual(mock.call_args[1]["params"]["q"], "faith")

    def test_get_talk_url_and_paragraph(self):
        ctx, mock = stub_get({"_id": "2024-04-11nelson"})
        with ctx:
            s.get_talk("2024-04-11nelson", paragraph=3)
        self.assertEqual(mock.call_args[0][0], f"{s.CONFERENCE_BASE}/talk/2024-04-11nelson")
        self.assertEqual(mock.call_args[1]["params"], {"paragraph": 3})

    def test_get_conference_include_talks_flag(self):
        ctx, mock = stub_get({"_id": "2024-04"})
        with ctx:
            s.get_conference("2024-04", include_talks=True)
        self.assertEqual(mock.call_args[1]["params"], {"include_talks": "true"})

    def test_search_passes_query_as_q(self):
        ctx, mock = stub_get({"results": []})
        with ctx:
            s.search_scripture("faith", volume="bookofmormon")
        params = mock.call_args[1]["params"]
        self.assertEqual(params["q"], "faith")
        self.assertEqual(params["volume"], "bookofmormon")


class FindReferencesTests(unittest.TestCase):
    def test_posts_text_body(self):
        ctx, mock = stub_post({"text": "x", "count": 0, "references": []})
        with ctx:
            s.find_references_in_text("See Alma 32:21.")
        url, kwargs = mock.call_args[0][0], mock.call_args[1]
        self.assertEqual(url, f"{s.SCRIPTURES_BASE}/referencesFinder")
        self.assertEqual(kwargs["json"], {"text": "See Alma 32:21."})


class FootnoteTests(unittest.TestCase):
    CHAPTER = {"chapter": {"verses": [
        {"text": "born goodly parents",
         "footNotes": [
             {"start": 0, "end": 4, "text": "TG Birthright."},
             {"start": 5, "end": 11, "text": "Prov. 22:1."},
             {"start": 12, "end": 19, "text": "Mosiah 1:2. TG Honoring Father and Mother."},
         ]},
    ]}}

    def test_markers_and_anchors(self):
        ctx, _ = stub_get(self.CHAPTER)
        with ctx:
            notes = s.get_footnotes("1nephi", 1, 1)
        self.assertEqual([n["marker"] for n in notes], ["a", "b", "c"])
        self.assertEqual(notes[0]["anchor"], "born")
        self.assertEqual(notes[1]["anchor"], "goodly")
        self.assertEqual(notes[2]["anchor"], "parents")
        self.assertEqual(notes[2]["text"], "Mosiah 1:2. TG Honoring Father and Mother.")

    def test_verse_out_of_range_raises(self):
        ctx, _ = stub_get(self.CHAPTER)
        with ctx:
            with self.assertRaises(s.ScriptureAPIError):
                s.get_footnotes("1nephi", 1, 99)

    def test_no_footnotes_returns_empty(self):
        ctx, _ = stub_get({"chapter": {"verses": [{"text": "x", "footNotes": []}]}})
        with ctx:
            self.assertEqual(s.get_footnotes("isaiah", 1, 1), [])


class StudyHelpSlugTests(unittest.TestCase):
    def test_slug_cases(self):
        self.assertEqual(s.study_help_slug("Faith"), "faith")
        self.assertEqual(s.study_help_slug("Honoring Father and Mother"),
                         "honoring-father-and-mother")
        self.assertEqual(s.study_help_slug("Israel, Judah, People of"),
                         "israel-judah-people-of")
        self.assertEqual(s.study_help_slug("God, Gifts of"), "god-gifts-of")
        self.assertEqual(s.study_help_slug("  Grace  "), "grace")

    def test_get_topical_guide_builds_entry_id(self):
        ctx, mock = stub_get({"_id": "tg-faith"})
        with ctx:
            s.get_topical_guide("Faith")
        self.assertEqual(mock.call_args[0][0], f"{s.STUDY_HELPS_BASE}/entry/tg-faith")

    def test_get_bible_dictionary_builds_entry_id(self):
        ctx, mock = stub_get({"_id": "bd-aaron"})
        with ctx:
            s.get_bible_dictionary("Aaron")
        self.assertEqual(mock.call_args[0][0], f"{s.STUDY_HELPS_BASE}/entry/bd-aaron")


class ByLetterTests(unittest.TestCase):
    def _pages(self, *pages):
        """Return a side_effect that yields successive {'entries': [...]} dicts."""
        payloads = [FakeResponse({"entries": p}) for p in pages]
        return MagicMock(side_effect=payloads)

    def test_filters_by_first_letter_and_stops_early(self):
        page = [{"title": "Aaron"}, {"title": "Abase"}, {"title": "Baal"},
                {"title": "Cain"}]
        with patch.object(s._session, "get", self._pages(page)):
            out = s.study_help_entries_by_letter("tg", "A", page_size=500)
        self.assertEqual([e["title"] for e in out], ["Aaron", "Abase"])

    def test_paginates_until_short_page(self):
        with patch.object(s._session, "get", self._pages(
            [{"title": "Adam"}, {"title": "Alma"}],   # full page (size 2)
            [{"title": "Amos"}],                        # short page -> stop
        )):
            out = s.study_help_entries_by_letter("tg", "A", page_size=2)
        self.assertEqual([e["title"] for e in out], ["Adam", "Alma", "Amos"])

    def test_case_insensitive_letter(self):
        page = [{"title": "Zion"}, {"title": "Zoram"}]
        with patch.object(s._session, "get", self._pages(page)):
            out = s.study_help_entries_by_letter("tg", "z", page_size=500)
        self.assertEqual(len(out), 2)


class SectionHeadingTests(unittest.TestCase):
    def test_extracts_introduction_augmentation(self):
        payload = {"chapter": {"chapterAugmentations": [
            {"type": "summary", "text": "1-3, ..."},
            {"type": "introduction", "text": "Revelation given ... April 6, 1830."},
        ]}}
        ctx, _ = stub_get(payload)
        with ctx:
            out = s.section_heading("doctrineandcovenants", 21)
        self.assertEqual(out, "Revelation given ... April 6, 1830.")

    def test_returns_none_when_no_introduction(self):
        payload = {"chapter": {"chapterAugmentations": [
            {"type": "summary", "text": "1-3, ..."},
        ]}}
        ctx, _ = stub_get(payload)
        with ctx:
            self.assertIsNone(s.section_heading("isaiah", 1))

    def test_returns_none_when_no_augmentations(self):
        ctx, _ = stub_get({"chapter": {}})
        with ctx:
            self.assertIsNone(s.section_heading("isaiah", 1))


if __name__ == "__main__":
    unittest.main()
