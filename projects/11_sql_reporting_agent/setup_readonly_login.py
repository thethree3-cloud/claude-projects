"""One-time setup: create a read-only SQL Server login for the NL-to-SQL agent.

Connects as sa, creates a login scoped to MSSQL_DATABASE with only the
db_datareader role (SELECT everywhere, nothing else), then verifies the
new login can SELECT but is denied on INSERT. Credentials are written to
the root .env, never printed or committed.
"""
import os
import secrets
import string
from pathlib import Path

import pyodbc
from dotenv import load_dotenv, set_key

ENV_PATH = Path(__file__).resolve().parents[2] / ".env"
READONLY_USER = "nlreport_reader"
DRIVER = "{ODBC Driver 18 for SQL Server}"


def generate_password(length=24):
    alphabet = string.ascii_letters + string.digits + "!@#%^*_-+="
    return "".join(secrets.choice(alphabet) for _ in range(length))


def connect(user, password, database, autocommit=True):
    host = os.environ["MSSQL_HOST"]
    port = os.environ["MSSQL_PORT"]
    conn_str = (
        f"DRIVER={DRIVER};SERVER={host},{port};DATABASE={database};"
        f"UID={user};PWD={password};TrustServerCertificate=yes;"
    )
    return pyodbc.connect(conn_str, autocommit=autocommit)


def main():
    load_dotenv(ENV_PATH)
    database = os.environ["MSSQL_DATABASE"]
    sa_password = os.environ["MSSQL_SA_PASSWORD"]

    if os.environ.get("MSSQL_READONLY_PASSWORD"):
        print(f"{READONLY_USER} already configured in .env — skipping creation.")
        return

    reader_password = generate_password()

    # DDL statements don't accept parameter markers, so values are inlined.
    # Safe here only because reader_password is generated from an alphabet
    # with no quote/backslash characters -- checked explicitly (not via
    # `assert`, which `python -O` strips) since this guards a real
    # SQL-injection invariant, not just a debugging sanity check.
    if "'" in reader_password or '"' in reader_password:
        raise RuntimeError("Generated password contains a quote character -- refusing to inline into DDL.")

    # CREATE LOGIN is server-scoped; must run against master with autocommit.
    master_conn = connect("sa", sa_password, "master")
    cur = master_conn.cursor()
    cur.execute(
        f"IF NOT EXISTS (SELECT 1 FROM sys.sql_logins WHERE name = '{READONLY_USER}') "
        f"CREATE LOGIN {READONLY_USER} WITH PASSWORD = '{reader_password}';"
    )
    master_conn.close()

    # CREATE USER + role membership are database-scoped.
    db_conn = connect("sa", sa_password, database)
    cur = db_conn.cursor()
    cur.execute(
        f"IF NOT EXISTS (SELECT 1 FROM sys.database_principals WHERE name = '{READONLY_USER}') "
        f"CREATE USER {READONLY_USER} FOR LOGIN {READONLY_USER};"
    )
    cur.execute(f"ALTER ROLE db_datareader ADD MEMBER {READONLY_USER};")
    db_conn.close()

    set_key(str(ENV_PATH), "MSSQL_READONLY_USER", READONLY_USER)
    set_key(str(ENV_PATH), "MSSQL_READONLY_PASSWORD", reader_password)
    print(f"Created login '{READONLY_USER}' with db_datareader on {database}.")
    print("Credentials written to .env as MSSQL_READONLY_USER / MSSQL_READONLY_PASSWORD.")

    verify(reader_password, database)


def verify(reader_password, database):
    conn = connect(READONLY_USER, reader_password, database, autocommit=False)
    cur = conn.cursor()

    cur.execute("SELECT TOP 1 Name FROM Production.Product;")
    row = cur.fetchone()
    print(f"SELECT check: OK (sample row: {row[0]!r})")

    try:
        cur.execute(
            "INSERT INTO Production.ProductCategory (Name, rowguid, ModifiedDate) "
            "VALUES ('should_fail', NEWID(), GETDATE());"
        )
        conn.commit()
        print("INSERT check: FAILED — write succeeded, permissions are wrong!")
    except pyodbc.Error:
        conn.rollback()
        print("INSERT check: OK (write correctly denied)")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
