import unittest

from extract_exhibitor_profiles import (
    _cluster_columns,
    _is_noise,
    _parse_column,
    build_profile_lookup,
    extract_exhibitor_profiles,
)
from generate_sample_data import DATA_DIR, EXHIBITOR_PROFILES, write_exhibitor_profiles_pdf


def _block(x0, y0, text, x1=None):
    # Mirrors PyMuPDF's get_text("blocks") tuple shape: (x0, y0, x1, y1,
    # text, block_no, block_type). Only x0/text matter to the functions
    # under test here, so the rest are filled with harmless placeholders.
    return (x0, y0, x1 if x1 is not None else x0 + 400, y0 + 10, text, 0, 0)


class IsNoiseTests(unittest.TestCase):
    def test_blank_text_is_noise(self):
        self.assertTrue(_is_noise("   \n  "))

    def test_control_character_garbage_is_noise(self):
        self.assertTrue(_is_noise("\x1f \x1e\x1d\x1c\n"))

    def test_real_short_line_is_not_noise(self):
        # A genuine short continuation line (e.g. the tail of a wrapped
        # sentence) must survive -- length alone isn't a noise signal.
        self.assertFalse(_is_noise("platforms.\n"))

    def test_real_paragraph_is_not_noise(self):
        self.assertFalse(_is_noise("Acme Mills Company\nAcme Mills is a textile maker.\n"))


class ClusterColumnsTests(unittest.TestCase):
    def test_separates_two_columns_by_gap(self):
        blocks = [_block(166, 100, "Left A"), _block(778, 100, "Right A")]
        columns = _cluster_columns(blocks)
        self.assertEqual(len(columns), 2)

    def test_drops_stray_block_misaligned_with_column(self):
        # Mirrors a real artifact found live: a stray logo-caption block
        # ("AeroGlow") sitting at a different x0 than the real column
        # (166), close enough in x0-gap terms to cluster with it, but not
        # actually aligned with the column's real left edge.
        blocks = [
            _block(166, 100, "Real Company One\nDescription one."),
            _block(100, 150, "AeroGlow"),
            _block(166, 200, "Real Company Two\nDescription two."),
        ]
        columns = _cluster_columns(blocks)
        self.assertEqual(len(columns), 1)
        texts = [b[4] for b in columns[0]]
        self.assertNotIn("AeroGlow", texts)
        self.assertEqual(len(texts), 2)


class ParseColumnTests(unittest.TestCase):
    def test_pairs_name_description_with_booth_block(self):
        blocks = [
            _block(166, 100, "Acme Mills Company\nAcme Mills is a textile maker."),
            _block(166, 120, "https://www.acmemills.example/\nBooth 2013"),
        ]
        entries = _parse_column(blocks, source="test.pdf page 1")
        self.assertEqual(len(entries), 1)
        entry = entries[0]
        self.assertEqual(entry["name"], "Acme Mills Company")
        self.assertEqual(entry["description"], "Acme Mills is a textile maker.")
        self.assertEqual(entry["website"], "https://www.acmemills.example/")
        self.assertEqual(entry["booth"], "2013")
        self.assertEqual(entry["source"], "test.pdf page 1")

    def test_accumulates_description_split_into_separate_block(self):
        # Mirrors a real layout variant found live (RENK Group): the
        # description sits in its own block, separate from the name block,
        # both still before the website/booth block.
        blocks = [
            _block(166, 100, "Vantage Group\nTrusted Partner"),
            _block(166, 120, "Vantage Group is a global technology leader."),
            _block(166, 140, "https://www.vantagegroup.example/\nBooth 5022"),
        ]
        entries = _parse_column(blocks, source="test.pdf page 1")
        self.assertEqual(len(entries), 1)
        entry = entries[0]
        self.assertEqual(entry["name"], "Vantage Group")
        self.assertEqual(
            entry["description"],
            "Trusted Partner Vantage Group is a global technology leader.",
        )
        self.assertEqual(entry["booth"], "5022")

    def test_drops_entry_with_no_real_description(self):
        # Mirrors a real false positive found live: a promo/ad callout
        # elsewhere in a program ("See X In Action. Visit us at: Booth N")
        # matches the same name+booth shape but has no real description.
        blocks = [
            _block(166, 100, "See Acme In Action. Visit us at:"),
            _block(166, 120, "Booth 2013"),
        ]
        entries = _parse_column(blocks, source="test.pdf page 1")
        self.assertEqual(entries, [])

    def test_leftover_pending_with_no_booth_is_discarded(self):
        blocks = [_block(166, 100, "Page footer text with no booth number.")]
        entries = _parse_column(blocks, source="test.pdf page 1")
        self.assertEqual(entries, [])


class BuildProfileLookupTests(unittest.TestCase):
    def test_normalizes_name_for_lookup(self):
        profiles = [
            {"name": "Acme Mills Company", "description": "", "website": None, "booth": "1", "source": "s"}
        ]
        lookup = build_profile_lookup(profiles)
        self.assertIn("acmemillscompany", lookup)
        self.assertEqual(lookup["acmemillscompany"]["name"], "Acme Mills Company")


class ExtractExhibitorProfilesIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        write_exhibitor_profiles_pdf()
        cls.pdf_path = DATA_DIR / "sample_exhibitor_profiles.pdf"
        cls.profiles = extract_exhibitor_profiles(cls.pdf_path)

    def test_extracts_all_known_profiles(self):
        self.assertEqual(len(self.profiles), len(EXHIBITOR_PROFILES))
        names = {p["name"] for p in self.profiles}
        self.assertEqual(names, {p["name"] for p in EXHIBITOR_PROFILES})

    def test_every_profile_has_website_and_booth(self):
        for profile in self.profiles:
            self.assertTrue(profile["website"], profile["name"])
            self.assertTrue(profile["booth"], profile["name"])

    def test_split_description_entry_merges_correctly(self):
        # Titanium Ridge Aerostructures is the fixture entry whose
        # description is deliberately split across two blocks.
        entry = next(p for p in self.profiles if p["name"] == "Titanium Ridge Aerostructures")
        expected = next(p for p in EXHIBITOR_PROFILES if p["name"] == "Titanium Ridge Aerostructures")
        self.assertIn(expected["description"], entry["description"])
        self.assertIn(expected["description_extra"], entry["description"])
        self.assertEqual(entry["booth"], expected["booth"])

    def test_booth_numbers_match_known_data(self):
        by_name = {p["name"]: p for p in self.profiles}
        for expected in EXHIBITOR_PROFILES:
            self.assertEqual(by_name[expected["name"]]["booth"], expected["booth"])


if __name__ == "__main__":
    unittest.main()
