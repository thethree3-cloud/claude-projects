# Python Basics: Quotes vs No Quotes

**Rule:** Quotes always mean *string*. No quotes means Python tries to read it as a literal value.

| Written as | Type | Example |
|---|---|---|
| `"2026"` or `'2026'` | `str` | Text, even if it looks like a number |
| `2026` | `int` | Whole number, no decimal point |
| `5.00` | `float` | Has a decimal point |
| `True` / `False` | `bool` | Capitalized, no quotes |
| `total` (no quotes, not a number/bool) | *reference* | Python assumes it's an existing variable name — errors if undefined |

**Why it matters:**
- `"2026"` is a string that *contains* digits — you can't do math on it without converting (`int("2026")` first).
- Leading zeros get dropped from numbers but preserved in strings — that's why things like zip codes (`"08540"`) should be stored as strings, not ints. `08540` as an int becomes `8540`.

**Quick gut check:** if it needs to keep its exact formatting (zip code, phone number) or you'll never do math on it → string. If you'll calculate with it → int/float.
