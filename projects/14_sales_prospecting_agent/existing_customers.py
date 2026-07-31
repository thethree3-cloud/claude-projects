import csv
from pathlib import Path


def load_existing_customers(path):
    with Path(path).open(newline="") as f:
        rows = list(csv.DictReader(f))
    return {row["company_name"].strip().lower() for row in rows}


def is_existing_customer(company_name, existing_customers):
    """Case-insensitive exact match only -- deliberately no fuzzy matching.

    A fuzzy match risks flagging a similarly-named but different company as
    an existing customer, which is a worse mistake than under-flagging.
    """
    return company_name.strip().lower() in existing_customers
