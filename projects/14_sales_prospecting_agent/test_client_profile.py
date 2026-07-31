import unittest

from client_profile import flatten_signals, load_client_profile
from generate_sample_data import DATA_DIR, write_sample_client_profile


class FlattenSignalsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        write_sample_client_profile()
        cls.profile = load_client_profile(DATA_DIR / "sample_client_profile.yaml")

    def test_flattens_every_industry_and_signal(self):
        flat = flatten_signals(self.profile)
        self.assertEqual(len(flat), 9)
        self.assertIn(
            {"industry": "Aerospace & Defense", "term": "MIL-STD-810", "weight": 25},
            flat,
        )
        self.assertIn(
            {"industry": "Medical Devices", "term": "ISO 13485", "weight": 15},
            flat,
        )


if __name__ == "__main__":
    unittest.main()
