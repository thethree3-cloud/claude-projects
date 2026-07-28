"""Shared SQL Server connection helper for the NL-to-SQL reporting agent.

Only ever connects via the read-only login (see setup_readonly_login.py).
There is deliberately no sa/write-capable path here -- the agent's safety
story depends on nothing in the query pipeline being able to reach for
elevated access, even by accident.
"""
import os
from pathlib import Path

import pyodbc
from dotenv import load_dotenv

ENV_PATH = Path(__file__).resolve().parents[2] / ".env"
DRIVER = "{ODBC Driver 18 for SQL Server}"

_env_loaded = False


def get_connection(autocommit=False):
    global _env_loaded
    if not _env_loaded:
        load_dotenv(ENV_PATH)
        _env_loaded = True

    user = os.environ["MSSQL_READONLY_USER"]
    password = os.environ["MSSQL_READONLY_PASSWORD"]
    host = os.environ["MSSQL_HOST"]
    port = os.environ["MSSQL_PORT"]
    database = os.environ["MSSQL_DATABASE"]
    conn_str = (
        f"DRIVER={DRIVER};SERVER={host},{port};DATABASE={database};"
        f"UID={user};PWD={password};TrustServerCertificate=yes;"
    )
    return pyodbc.connect(conn_str, autocommit=autocommit)
