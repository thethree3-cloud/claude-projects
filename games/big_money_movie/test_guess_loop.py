import unittest

from guess_loop import (
    check_guess,
    elapsed_ms,
    mask_title,
    mask_title_with_reveals,
    partial_reveal_positions,
)


class MaskTitleTests(unittest.TestCase):
    def test_masks_letters_keeps_digits_and_spaces(self):
        self.assertEqual(mask_title("101 Dalmatians"), "101 __________")

    def test_masks_multi_word_title(self):
        self.assertEqual(mask_title("Dirty Harry"), "_____ _____")

    def test_keeps_punctuation_visible(self):
        self.assertEqual(mask_title("Ocean's Eleven"), "_____'_ ______")

    def test_single_word_title(self):
        self.assertEqual(mask_title("Chinatown"), "_________")

    def test_empty_title(self):
        self.assertEqual(mask_title(""), "")


class CheckGuessTests(unittest.TestCase):
    def test_exact_match_is_correct(self):
        self.assertTrue(check_guess("Dirty Harry", "Dirty Harry"))

    def test_case_and_punctuation_insensitive(self):
        self.assertTrue(check_guess("dirty harry!", "Dirty Harry"))

    def test_ampersand_and_spelled_out_and_are_equivalent(self):
        self.assertTrue(check_guess("Starsky & Hutch", "Starsky and Hutch"))

    def test_wrong_title_is_incorrect(self):
        self.assertFalse(check_guess("The Godfather", "Dirty Harry"))

    def test_partial_title_is_incorrect(self):
        self.assertFalse(check_guess("Dirty", "Dirty Harry"))

    def test_extra_whitespace_is_ignored(self):
        self.assertTrue(check_guess("  Dirty   Harry  ", "Dirty Harry"))


class MaskTitleWithRevealsTests(unittest.TestCase):
    def test_no_reveals_matches_plain_mask_title(self):
        self.assertEqual(mask_title_with_reveals("Dirty Harry"), mask_title("Dirty Harry"))

    def test_reveals_every_occurrence_of_a_letter(self):
        self.assertEqual(
            mask_title_with_reveals("Dirty Harry", revealed_letters={"a"}), "_____ _a___"
        )

    def test_letter_reveal_is_case_insensitive_and_keeps_original_case(self):
        self.assertEqual(
            mask_title_with_reveals("Dirty Harry", revealed_letters={"h"}), "_____ H____"
        )

    def test_reveals_a_whole_word_by_index(self):
        self.assertEqual(
            mask_title_with_reveals("Dirty Harry", revealed_word_indices={0}), "Dirty _____"
        )
        self.assertEqual(
            mask_title_with_reveals("Dirty Harry", revealed_word_indices={1}), "_____ Harry"
        )

    def test_reveals_specific_character_positions(self):
        # "Chinatown" -> reveal the first 5 character indices (0-4).
        self.assertEqual(
            mask_title_with_reveals("Chinatown", revealed_char_indices={0, 1, 2, 3, 4}),
            "China____",
        )

    def test_combines_letter_and_word_reveals(self):
        self.assertEqual(
            mask_title_with_reveals(
                "Dirty Harry", revealed_letters={"a"}, revealed_word_indices={0}
            ),
            "Dirty _a___",
        )

    def test_structural_characters_always_visible(self):
        self.assertEqual(mask_title_with_reveals("101 Dalmatians"), "101 __________")


class PartialRevealPositionsTests(unittest.TestCase):
    def test_reveals_first_half_of_letters_rounded_up(self):
        # "Chinatown" has 9 letters -> ceil(9/2) = 5 revealed.
        positions = partial_reveal_positions("Chinatown")
        self.assertEqual(positions, {0, 1, 2, 3, 4})

    def test_deterministic_for_the_same_title(self):
        self.assertEqual(partial_reveal_positions("Chinatown"), partial_reveal_positions("Chinatown"))

    def test_single_letter_title_reveals_that_letter(self):
        self.assertEqual(partial_reveal_positions("X"), {0})


class ElapsedMsTests(unittest.TestCase):
    def test_computes_millisecond_difference(self):
        self.assertEqual(
            elapsed_ms("2026-09-11T00:00:00+00:00", "2026-09-11T00:00:01+00:00"), 1000
        )

    def test_handles_sub_second_difference(self):
        self.assertEqual(
            elapsed_ms(
                "2026-09-11T00:00:00.000000+00:00", "2026-09-11T00:00:00.250000+00:00"
            ),
            250,
        )

    def test_zero_when_timestamps_equal(self):
        ts = "2026-09-11T00:00:00+00:00"
        self.assertEqual(elapsed_ms(ts, ts), 0)


if __name__ == "__main__":
    unittest.main()
