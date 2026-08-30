import datetime
import unittest

import tenure


def _roles(*date_strings):
    return [{"dates": d, "title": "t", "organization": "o", "highlights": []} for d in date_strings]


class SpanTests(unittest.TestCase):
    def test_month_and_year(self):
        self.assertEqual(tenure._span("Feb 2021 - Feb 2024"), (2021 * 12 + 2, 2024 * 12 + 2))

    def test_year_only_range_covers_whole_years(self):
        # Jan 2019 -> Jan 2022  =>  three full years
        start, end = tenure._span("2019 - 2021")
        self.assertEqual(end - start, 36)

    def test_bare_year_dash_year(self):
        self.assertEqual(tenure._span("2019-2021"), tenure._span("2019 - 2021"))

    def test_numeric_month_formats(self):
        self.assertEqual(tenure._span("03/2020 - 06/2020"), (2020 * 12 + 3, 2020 * 12 + 6))
        self.assertEqual(tenure._span("2020-03 - 2020-06"), (2020 * 12 + 3, 2020 * 12 + 6))

    def test_present_uses_today(self):
        today = datetime.date.today()
        _, end = tenure._span("Jan 2020 - Present")
        self.assertEqual(end, today.year * 12 + today.month)

    def test_unparseable_or_reversed_returns_none(self):
        self.assertIsNone(tenure._span(""))
        self.assertIsNone(tenure._span("a while ago"))
        self.assertIsNone(tenure._span("2019"))            # not a range
        self.assertIsNone(tenure._span("2024 - 2020"))     # end before start


class TotalYearsTests(unittest.TestCase):
    def test_single_role(self):
        self.assertEqual(tenure.total_years(_roles("Feb 2021 - Feb 2024")), 3.0)

    def test_adjacent_roles_add_up(self):
        total = tenure.total_years(_roles("Jan 2018 - Jan 2020", "Jan 2020 - Jan 2022"))
        self.assertEqual(total, 4.0)

    def test_overlapping_roles_are_merged_not_double_counted(self):
        # Jan 2020 - Jun 2022 is 29 months, not 4 years of summed tenure
        total = tenure.total_years(_roles("Jan 2020 - Jan 2022", "Jun 2020 - Jun 2022"))
        self.assertEqual(total, 2.4)

    def test_gap_between_roles_is_excluded(self):
        total = tenure.total_years(_roles("Jan 2015 - Jan 2016", "Jan 2020 - Jan 2021"))
        self.assertEqual(total, 2.0)

    def test_none_when_no_roles(self):
        self.assertIsNone(tenure.total_years([]))

    def test_none_when_most_dates_unparseable(self):
        self.assertIsNone(
            tenure.total_years(_roles("Feb 2021 - Feb 2024", "", "sometime", "n/a"))
        )

    def test_partial_parse_ok_when_at_least_half(self):
        self.assertEqual(
            tenure.total_years(_roles("Jan 2018 - Jan 2022", "")), 4.0
        )


if __name__ == "__main__":
    unittest.main()
