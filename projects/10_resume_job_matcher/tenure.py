"""Total years of professional experience, computed from the résumé's own
date ranges rather than asked of the model.

`parse_resume` still extracts each role's ``dates`` string as written; this
turns those into one number, merging overlapping ranges so two concurrent
jobs aren't counted twice. It returns ``None`` when too few of the ranges
parse, and `parse_resume` then keeps the model's estimate as the fallback.
"""

import datetime
import re

_MONTHS = {
    name: n
    for n, name in enumerate(
        ["jan", "feb", "mar", "apr", "may", "jun",
         "jul", "aug", "sep", "oct", "nov", "dec"],
        start=1,
    )
}
_PRESENT = ("present", "current", "now", "ongoing", "to date", "till date")
# A range separator: an en/em dash (spaces optional), or " to " / " - " with
# spaces — a bare hyphen with no spaces is left alone so it doesn't split a
# date like "2020-03" or "2019-2021".
_SEPARATOR = re.compile(r"\s*[–—]\s*|\s+(?:to|until|through|-)\s+", re.I)
_YEAR_RANGE = re.compile(r"^\s*((?:19|20)\d{2})\s*-\s*((?:19|20)\d{2})\s*$")


def _months(text, *, is_end):
    """A date-ish string -> a month count (year * 12 + month), or None.

    With only a year, a start snaps to January and an end to December, so a
    "2021 - 2023" range reads as the full three years.
    """
    text = text.strip().lower()
    if not text:
        return None
    if any(token in text for token in _PRESENT):
        today = datetime.date.today()
        return today.year * 12 + today.month

    month_year = re.search(r"\b([a-z]{3,9})\.?\s+((?:19|20)\d{2})\b", text)
    if month_year and month_year.group(1)[:3] in _MONTHS:
        return int(month_year.group(2)) * 12 + _MONTHS[month_year.group(1)[:3]]

    num_month_year = re.search(r"\b(\d{1,2})[/\-]((?:19|20)\d{2})\b", text)
    if num_month_year and 1 <= int(num_month_year.group(1)) <= 12:
        return int(num_month_year.group(2)) * 12 + int(num_month_year.group(1))

    year_num_month = re.search(r"\b((?:19|20)\d{2})[/\-](\d{1,2})\b", text)
    if year_num_month and 1 <= int(year_num_month.group(2)) <= 12:
        return int(year_num_month.group(1)) * 12 + int(year_num_month.group(2))

    year_only = re.search(r"\b((?:19|20)\d{2})\b", text)
    if year_only:
        # a year-only start is January; a year-only end is the following
        # January, so "2019 - 2021" reads as the full three years.
        return int(year_only.group(1)) * 12 + (13 if is_end else 1)

    return None


def _span(dates):
    """One role's ``dates`` string -> (start_months, end_months) or None."""
    text = (dates or "").strip()
    year_range = _YEAR_RANGE.match(text)
    if year_range:
        left, right = year_range.group(1), year_range.group(2)
    else:
        parts = _SEPARATOR.split(text, maxsplit=1)
        if len(parts) != 2:
            return None
        left, right = parts

    start = _months(left, is_end=False)
    end = _months(right, is_end=True)
    if start is None or end is None or end < start:
        return None
    return start, end


def total_years(experience):
    """Sum the résumé's role date ranges into total years, merging overlaps.

    Returns ``None`` when there are no roles, or fewer than half of them have a
    parseable range — in which case the caller should trust the model's number.
    """
    spans = sorted(s for role in experience if (s := _span(role.get("dates", ""))))
    if not spans or len(spans) * 2 < len(experience):
        return None

    total, cur_start, cur_end = 0, *spans[0]
    for start, end in spans[1:]:
        if start <= cur_end:
            cur_end = max(cur_end, end)
        else:
            total += cur_end - cur_start
            cur_start, cur_end = start, end
    total += cur_end - cur_start
    return round(total / 12, 1)
