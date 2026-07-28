"""Schema introspection for the NL-to-SQL reporting agent.

Builds a compact text description of every table/column plus foreign key
relationships in AdventureWorks, meant to be handed to the LLM as context
so it can generate accurate SQL (including correct joins) from a plain
English question.
"""
from pathlib import Path

from db import get_connection

BASE_DIR = Path(__file__).resolve().parent
SCHEMA_CONTEXT_PATH = BASE_DIR / "data" / "schema_context.txt"

COLUMNS_SQL = """
SELECT TABLE_SCHEMA, TABLE_NAME, COLUMN_NAME, DATA_TYPE, IS_NULLABLE
FROM INFORMATION_SCHEMA.COLUMNS
ORDER BY TABLE_SCHEMA, TABLE_NAME, ORDINAL_POSITION;
"""

PRIMARY_KEYS_SQL = """
SELECT s.name, t.name, c.name
FROM sys.indexes i
JOIN sys.index_columns ic ON i.object_id = ic.object_id AND i.index_id = ic.index_id
JOIN sys.columns c ON ic.object_id = c.object_id AND ic.column_id = c.column_id
JOIN sys.tables t ON i.object_id = t.object_id
JOIN sys.schemas s ON t.schema_id = s.schema_id
WHERE i.is_primary_key = 1;
"""

FOREIGN_KEYS_SQL = """
SELECT fs.name, ft.name, fc.name, rs.name, rt.name, rc.name
FROM sys.foreign_keys fk
JOIN sys.foreign_key_columns fkc ON fk.object_id = fkc.constraint_object_id
JOIN sys.tables ft ON fkc.parent_object_id = ft.object_id
JOIN sys.schemas fs ON ft.schema_id = fs.schema_id
JOIN sys.columns fc ON fkc.parent_object_id = fc.object_id AND fkc.parent_column_id = fc.column_id
JOIN sys.tables rt ON fkc.referenced_object_id = rt.object_id
JOIN sys.schemas rs ON rt.schema_id = rs.schema_id
JOIN sys.columns rc ON fkc.referenced_object_id = rc.object_id AND fkc.referenced_column_id = rc.column_id
ORDER BY fs.name, ft.name;
"""


def list_schema():
    """Return a compact text block describing every table, column, and FK."""
    conn = get_connection()
    cur = conn.cursor()

    cur.execute(PRIMARY_KEYS_SQL)
    pk_lookup = {(schema, table, col) for schema, table, col in cur.fetchall()}

    cur.execute(COLUMNS_SQL)
    columns = cur.fetchall()

    cur.execute(FOREIGN_KEYS_SQL)
    foreign_keys = cur.fetchall()
    conn.close()

    lines = []
    current_table = None
    for schema, table, column, dtype, nullable in columns:
        table_key = f"{schema}.{table}"
        if table_key != current_table:
            if current_table is not None:
                lines.append("")
            lines.append(f"{table_key}")
            current_table = table_key
        is_pk = (schema, table, column) in pk_lookup
        flags = " PK" if is_pk else ("" if nullable == "NO" else " NULL")
        lines.append(f"  {column} {dtype}{flags}")

    lines.append("")
    lines.append("Foreign Keys:")
    for from_schema, from_table, from_col, to_schema, to_table, to_col in foreign_keys:
        lines.append(
            f"  {from_schema}.{from_table}.{from_col} -> {to_schema}.{to_table}.{to_col}"
        )

    return "\n".join(lines)


if __name__ == "__main__":
    context = list_schema()
    SCHEMA_CONTEXT_PATH.parent.mkdir(exist_ok=True)
    SCHEMA_CONTEXT_PATH.write_text(context)
    print(f"Wrote schema context ({len(context)} chars, {len(context.split(chr(10)))} lines) "
          f"to {SCHEMA_CONTEXT_PATH.relative_to(BASE_DIR.parent.parent)}")
