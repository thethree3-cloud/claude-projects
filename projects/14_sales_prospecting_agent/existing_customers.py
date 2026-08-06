import csv
from pathlib import Path

import openpyxl


def load_existing_customers(path):
    path = Path(path)
    if path.suffix.lower() in (".xlsx", ".xlsm"):
        return _load_from_xlsx(path)
    with path.open(newline="") as f:
        rows = list(csv.DictReader(f))
    return {row["company_name"].strip().lower() for row in rows}


def _load_from_xlsx(path):
    """Reads the first sheet, matching a 'company_name' header case/whitespace-
    insensitively -- unlike the CSV path, since real-world Excel customer
    lists are hand-authored and header casing varies ("Company Name",
    "COMPANY_NAME", etc.), not produced by this project's own CSV writer.
    """
    sheet = openpyxl.load_workbook(path, read_only=True, data_only=True).active
    rows = sheet.iter_rows(values_only=True)
    header = [str(cell).strip().lower() if cell is not None else "" for cell in next(rows)]
    name_col = header.index("company_name")
    return {
        str(row[name_col]).strip().lower()
        for row in rows
        if len(row) > name_col and row[name_col] is not None and str(row[name_col]).strip()
    }


def is_existing_customer(company_name, existing_customers):
    """Case-insensitive exact match only -- deliberately no fuzzy matching.

    A fuzzy match risks flagging a similarly-named but different company as
    an existing customer, which is a worse mistake than under-flagging.
    """
    return company_name.strip().lower() in existing_customers
