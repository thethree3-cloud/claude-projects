import csv
from pathlib import Path

US_COUNTRY_NAMES = {"USA", "UNITED STATES", "US", "UNITED STATES OF AMERICA"}
INTERNATIONAL_SENTINEL = "INTERNATIONAL"

NEEDS_REVIEW = {"salesperson_name": "Needs Review", "email": "", "territory": ""}


def load_territory_routing(path):
    with Path(path).open(newline="") as f:
        return list(csv.DictReader(f))


def route_salesperson(location, territory_rows):
    """Matches a company's location to a salesperson from territory_rows.

    Never invents an assignment not present in territory_rows -- any branch
    that can't find a covering row returns "Needs Review" instead of a
    guess. Domestic vs. international is decided by country first (an
    explicit non-US country always routes to the international row, if any,
    regardless of whether a state also happens to be present).
    """
    country = (location.get("country") or "").strip()
    if country and country.upper() not in US_COUNTRY_NAMES:
        for row in territory_rows:
            if row["coverage"] == INTERNATIONAL_SENTINEL:
                return {
                    "salesperson_name": row["salesperson_name"],
                    "email": row["email"],
                    "territory": row["territory"],
                    "assignment_reason": (
                        f"Non-domestic company (country: {country}) routed "
                        "to international coverage."
                    ),
                }
        return {
            **NEEDS_REVIEW,
            "assignment_reason": (
                f"Non-domestic company (country: {country}) but no "
                "international salesperson in territory_routing.csv."
            ),
        }

    state = (location.get("state") or "").strip()
    if state:
        for row in territory_rows:
            if row["coverage"] == INTERNATIONAL_SENTINEL:
                continue
            covered_states = [s.strip().upper() for s in row["coverage"].split(";")]
            if state.upper() in covered_states:
                return {
                    "salesperson_name": row["salesperson_name"],
                    "email": row["email"],
                    "territory": row["territory"],
                    "assignment_reason": (
                        f"Company state ({state}) matches the "
                        f"{row['territory']} territory."
                    ),
                }
        return {
            **NEEDS_REVIEW,
            "assignment_reason": f"No salesperson territory covers state: {state}.",
        }

    return {
        **NEEDS_REVIEW,
        "assignment_reason": "Could not determine company's state or country from research text.",
    }
