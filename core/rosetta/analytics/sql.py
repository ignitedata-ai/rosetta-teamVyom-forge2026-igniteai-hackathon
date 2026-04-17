"""SQL bridge over the parsed workbook.

Every sheet becomes an in-memory DuckDB table built from the sheet's data
rows (headers → column names). The connection is lazy — created only on
the first `sql_query` call per request, attached to the `WorkbookModel`
instance, and reused for subsequent calls within the same request.

No filesystem, no separate process. Adding this tool does not change
deployment topology — duckdb is a Python library that runs in-process,
the same lifecycle as openpyxl.
"""

from __future__ import annotations

import logging
import re
from typing import Any

import duckdb

from ..models import WorkbookModel
from . import build_envelope, error
from .view import DataView

log = logging.getLogger("rosetta.analytics.sql")

_SANITIZE_RE = re.compile(r"[^a-z0-9_]+")
_SQL_CONN_ATTR = "__sql_conn__"
_SQL_META_ATTR = "__sql_meta__"

# Hard caps — DuckDB will happily scan 10M rows; we keep responses bounded.
DEFAULT_LIMIT = 200
MAX_LIMIT = 1000


def sql_query(wb: WorkbookModel, query: str, limit: int = DEFAULT_LIMIT) -> dict:
    """Execute a SQL query against sheet-derived tables.

    Returns rows as a list of dicts. Column provenance (sheet + column
    letter) is included in the meta block so the coordinator can cite
    specific refs in its answer.
    """
    if not query or not query.strip():
        return error("query is empty")
    limit = max(1, min(limit, MAX_LIMIT))

    conn, meta = _connection(wb)
    # Auto-LIMIT if the user didn't specify one (keeps tool-result size bounded).
    safe_query = query.strip().rstrip(";")
    lowered = safe_query.lower()
    if "limit " not in lowered:
        safe_query = f"{safe_query} LIMIT {limit}"

    try:
        cursor = conn.execute(safe_query)
    except duckdb.Error as e:
        return error(f"sql error: {e}", query=safe_query, tables=sorted(meta["sheet_by_table"].keys()))

    columns = [d[0] for d in cursor.description] if cursor.description else []
    rows = [dict(zip(columns, row)) for row in cursor.fetchall()]
    return build_envelope(
        {
            "query": safe_query,
            "columns": columns,
            "rows": rows,
            "row_count": len(rows),
            "tables_available": sorted(meta["sheet_by_table"].keys()),
        },
        evidence_range=None,
        row_count=len(rows),
        warnings=([] if len(rows) < limit else [f"result truncated at limit {limit}"]),
    )


def sql_schema(wb: WorkbookModel) -> dict:
    """Return the sheet-to-table mapping + column schema DuckDB would use.

    Useful as a discovery tool — coordinator can call this before writing
    a SQL query to learn the available table/column names.
    """
    _, meta = _connection(wb)
    schema_out = []
    for table, info in meta["tables"].items():
        schema_out.append(
            {
                "table": table,
                "sheet": info["sheet"],
                "row_count": info["row_count"],
                "columns": [
                    {"name": c["name"], "excel_column": c["letter"], "label": c["label"]}
                    for c in info["columns"]
                ],
            }
        )
    return build_envelope({"tables": schema_out})


# --- connection lifecycle ------------------------------------------------


def _connection(wb: WorkbookModel) -> tuple[duckdb.DuckDBPyConnection, dict[str, Any]]:
    """Lazily build a DuckDB connection populated from `wb`'s sheets.

    Attaches the connection + table metadata to the WorkbookModel via
    attribute assignment. Subsequent calls within the same request reuse
    it; when `wb` goes out of scope, Python GC drops the connection.

    Note: Pydantic models accept arbitrary attribute assignment when
    `model_config` doesn't forbid extras (the default). We treat this as
    a request-scoped cache, not persistent state.
    """
    conn = getattr(wb, _SQL_CONN_ATTR, None)
    meta = getattr(wb, _SQL_META_ATTR, None)
    if conn is not None and meta is not None:
        return conn, meta
    conn = duckdb.connect(":memory:")
    meta = _build_tables(conn, wb)
    try:
        object.__setattr__(wb, _SQL_CONN_ATTR, conn)
        object.__setattr__(wb, _SQL_META_ATTR, meta)
    except (AttributeError, TypeError):
        # Pydantic v2 frozen model — fall through, we'll rebuild next call.
        pass
    return conn, meta


def _build_tables(conn: duckdb.DuckDBPyConnection, wb: WorkbookModel) -> dict[str, Any]:
    """Populate DuckDB with one table per sheet.

    Each non-hidden sheet with at least one data row becomes a table.
    Column names come from the header row, sanitized for SQL. Dup names
    get a numeric suffix. An index column `__row__` preserves the 1-based
    Excel row number so SQL results can be mapped back to cell refs.
    """
    tables: dict[str, dict[str, Any]] = {}
    sheet_by_table: dict[str, str] = {}

    for sheet in wb.sheets:
        if sheet.hidden:
            continue
        view = DataView.for_sheet(wb, sheet.name)
        if view is None or view.row_count == 0:
            continue

        header_map = view.header_map  # {letter: label}
        # Build a reproducible ordering: by column letter
        ordered_cols = sorted(view.populated_columns, key=lambda c: (len(c), c))
        col_info: list[dict[str, str]] = []
        used_names: set[str] = {"__row__"}
        for letter in ordered_cols:
            label = header_map.get(letter, letter)
            sane = _sanitize_name(label) or _sanitize_name(letter) or "col"
            if sane in used_names:
                i = 2
                while f"{sane}_{i}" in used_names:
                    i += 1
                sane = f"{sane}_{i}"
            used_names.add(sane)
            col_info.append({"letter": letter, "label": label, "name": sane})

        table_name = _unique_table_name(_sanitize_name(sheet.name) or "sheet", sheet_by_table)
        sheet_by_table[table_name] = sheet.name

        # Build rows — tuple order matches col_info
        rows = []
        for row in view.data_rows:
            rows.append(tuple([row] + [view.value(row, c["letter"]) for c in col_info]))

        # DuckDB schema: __row__ as INTEGER, everything else as VARCHAR for
        # maximum interoperability (Claude can CAST when needed). This
        # avoids type-inference surprises on mixed columns.
        col_defs = ", ".join(
            [f'"__row__" INTEGER'] + [f'"{c["name"]}" VARCHAR' for c in col_info]
        )
        conn.execute(f'CREATE TABLE "{table_name}" ({col_defs})')
        placeholders = ", ".join(["?"] * (len(col_info) + 1))
        conn.executemany(
            f'INSERT INTO "{table_name}" VALUES ({placeholders})',
            [tuple(_coerce_for_sql(v) for v in r) for r in rows],
        )

        tables[table_name] = {
            "sheet": sheet.name,
            "row_count": len(rows),
            "columns": col_info,
        }
    return {"tables": tables, "sheet_by_table": sheet_by_table}


def _sanitize_name(raw: str) -> str:
    s = raw.strip().lower()
    s = _SANITIZE_RE.sub("_", s).strip("_")
    if s and s[0].isdigit():
        s = "c_" + s
    return s


def _unique_table_name(base: str, used: dict[str, str]) -> str:
    if base not in used:
        return base
    i = 2
    while f"{base}_{i}" in used:
        i += 1
    return f"{base}_{i}"


def _coerce_for_sql(v: Any) -> Any:
    """Coerce openpyxl values to a form DuckDB accepts via VARCHAR inserts."""
    if v is None:
        return None
    if hasattr(v, "isoformat"):  # datetime/date
        return v.isoformat()
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    return str(v)


# --- tool schemas --------------------------------------------------------

TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "name": "sql_schema",
        "description": (
            "List the tables DuckDB has built from this workbook — one per "
            "sheet — and their columns. Call this before sql_query if you "
            "need to discover available table/column names. Each column "
            "carries its Excel column letter so you can cite specific refs."
        ),
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "sql_query",
        "description": (
            "Run a SQL SELECT against sheet-derived tables. Each sheet is a "
            "table; each data row is a row; `__row__` holds the Excel row "
            "number. Use for questions that need joins, subqueries, window "
            "functions, or complex group-bys. Call sql_schema first to learn "
            "the table names. Values are stored as VARCHAR — CAST to numeric "
            "when comparing: `WHERE CAST(latitude AS DOUBLE) > 40`. "
            "DuckDB dialect."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "A single SELECT statement."},
                "limit": {"type": "integer", "default": DEFAULT_LIMIT, "maximum": MAX_LIMIT},
            },
            "required": ["query"],
        },
    },
]
