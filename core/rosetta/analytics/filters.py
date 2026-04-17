"""Filter / lookup / scenario tools.

Covers:
  - filter_rows       (the "show me rows where…" class)
  - lookup_row        (single-row retrieval by a match predicate)
  - scenario_filter   (analytic what-if: "if I exclude X, what's the new avg?")
  - compare_scenarios (base vs alternative filter, side-by-side)

All four build on DataView — column resolution, predicate parsing, and
evidence are inherited from there.
"""

from __future__ import annotations

from typing import Any

from ..models import WorkbookModel
from . import build_envelope, error
from .aggregators import aggregate_column
from .view import DataView


def filter_rows(
    wb: WorkbookModel,
    sheet: str,
    where: list[dict],
    select: list[str] | None = None,
    max_rows: int = 50,
) -> dict:
    """Return rows matching all predicates. `select` restricts columns;
    omit to include every populated column for each row.
    """
    view = DataView.for_sheet(wb, sheet)
    if view is None:
        return error(f"sheet not found: {sheet}")
    try:
        narrowed = view.filter(where)
    except ValueError as e:
        return error(str(e))

    cols = (
        [narrowed.resolve_column(c) or c for c in select]
        if select
        else narrowed.populated_columns
    )
    limit = max(1, min(max_rows, 500))
    rows: list[dict] = []
    for row in narrowed.data_rows[:limit]:
        rows.append(
            {
                "row": row,
                "ref": f"{sheet}!A{row}",
                "values": {narrowed.header_label(c): narrowed.value(row, c) for c in cols},
            }
        )
    return build_envelope(
        {
            "sheet": sheet,
            "matched_rows": narrowed.row_count,
            "returned": len(rows),
            "rows": rows,
            "truncated": narrowed.row_count > len(rows),
        },
        evidence_range=narrowed.evidence_range(),
        row_count=narrowed.row_count,
        refs=[r["ref"] for r in rows[:20]],
    )


def lookup_row(
    wb: WorkbookModel,
    sheet: str,
    match_column: str,
    match_value: Any,
    return_columns: list[str] | None = None,
) -> dict:
    """Return the first row whose `match_column` equals `match_value`.

    Equality is case-insensitive for strings, exact for numbers. If more
    than one row matches, the first (lowest row number) is returned and a
    warning is emitted with the match count.
    """
    view = DataView.for_sheet(wb, sheet)
    if view is None:
        return error(f"sheet not found: {sheet}")
    letter = view.resolve_column(match_column)
    if letter is None:
        return error(f"column not found: {match_column}")

    # Default op: equality for scalars, contains for string search feel
    op = "=" if not isinstance(match_value, str) else "="
    narrowed = view.filter([{"column": letter, "op": op, "value": match_value}])
    if narrowed.row_count == 0:
        # Fall back to contains for string match_value
        if isinstance(match_value, str):
            narrowed = view.filter([{"column": letter, "op": "contains", "value": match_value}])
    if narrowed.row_count == 0:
        return build_envelope(
            None,
            evidence_range=view.evidence_range(letter),
            warnings=[f"no rows found where {view.header_label(letter)} = {match_value!r}"],
        )

    target_row = narrowed.data_rows[0]
    cols = (
        [narrowed.resolve_column(c) or c for c in return_columns]
        if return_columns
        else narrowed.populated_columns
    )
    values = {narrowed.header_label(c): narrowed.value(target_row, c) for c in cols}
    warnings = (
        [f"{narrowed.row_count} rows matched; returning the first (row {target_row})"]
        if narrowed.row_count > 1
        else []
    )
    return build_envelope(
        {
            "sheet": sheet,
            "row": target_row,
            "ref": f"{sheet}!A{target_row}",
            "values": values,
            "matches_total": narrowed.row_count,
        },
        evidence_range=f"{sheet}!A{target_row}:A{target_row}",
        row_count=1,
        refs=[f"{sheet}!A{target_row}"],
        warnings=warnings,
    )


def scenario_filter(
    wb: WorkbookModel,
    sheet: str,
    where: list[dict],
    aggregation: dict,
) -> dict:
    """Apply a filter, then compute an aggregate on the resulting subset.

    `aggregation = {"column": str, "agg": str}` — the aggregate to compute
    over the filtered rows. Returns the base and filtered values so the
    caller can see the delta directly.
    """
    col = aggregation.get("column")
    agg = aggregation.get("agg", "mean")
    if not col:
        return error("aggregation.column is required")
    base = aggregate_column(wb, sheet, col, agg)
    filtered = aggregate_column(wb, sheet, col, agg, where=where)
    if "error" in base:
        return base
    if "error" in filtered:
        return filtered
    base_val = base["result"]["value"] if base["result"] else None
    filt_val = filtered["result"]["value"] if filtered["result"] else None
    delta = (filt_val - base_val) if (base_val is not None and filt_val is not None) else None
    pct = (delta / base_val * 100) if (delta is not None and base_val not in (None, 0)) else None
    return build_envelope(
        {
            "sheet": sheet,
            "column": aggregation["column"],
            "aggregation": agg,
            "base_value": base_val,
            "base_rows": base["evidence"].get("row_count"),
            "filtered_value": filt_val,
            "filtered_rows": filtered["evidence"].get("row_count"),
            "delta": delta,
            "pct_change": pct,
            "where": where,
        },
        evidence_range=filtered["evidence"].get("range"),
        row_count=filtered["evidence"].get("row_count"),
    )


def compare_scenarios(
    wb: WorkbookModel,
    sheet: str,
    base_where: list[dict] | None,
    alt_where: list[dict],
    aggregation: dict,
) -> dict:
    """Run the same aggregation under two filter sets and report both."""
    col = aggregation.get("column")
    agg = aggregation.get("agg", "mean")
    if not col:
        return error("aggregation.column is required")
    base = aggregate_column(wb, sheet, col, agg, where=base_where)
    alt = aggregate_column(wb, sheet, col, agg, where=alt_where)
    if "error" in base:
        return base
    if "error" in alt:
        return alt
    base_val = base["result"]["value"] if base["result"] else None
    alt_val = alt["result"]["value"] if alt["result"] else None
    delta = (alt_val - base_val) if (base_val is not None and alt_val is not None) else None
    return build_envelope(
        {
            "sheet": sheet,
            "column": aggregation["column"],
            "aggregation": agg,
            "base": {"where": base_where or [], "value": base_val, "rows": base["evidence"].get("row_count")},
            "alt": {"where": alt_where, "value": alt_val, "rows": alt["evidence"].get("row_count")},
            "delta": delta,
        },
        evidence_range=alt["evidence"].get("range"),
        chart_data={
            "type": "bar",
            "x": ["base", "alt"],
            "y": [base_val, alt_val],
            "x_label": "scenario",
            "y_label": f"{agg}({aggregation['column']})",
        },
    )


# --- tool schemas --------------------------------------------------------

TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "name": "filter_rows",
        "description": (
            "Return rows on a sheet matching all predicates. Use for "
            "'rows where X > Y', 'show all stations in Illinois', "
            "'deals in March with gross > 3000'. Predicate 'op' values: "
            "= / != / > / >= / < / <= / in / not_in / contains / startswith / endswith."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "sheet": {"type": "string"},
                "where": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "column": {"type": "string"},
                            "op": {"type": "string"},
                            "value": {},
                        },
                        "required": ["column", "op", "value"],
                    },
                },
                "select": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Columns to include per returned row (omit for all).",
                },
                "max_rows": {"type": "integer", "default": 50},
            },
            "required": ["sheet", "where"],
        },
    },
    {
        "name": "lookup_row",
        "description": (
            "Return the first row on a sheet whose match_column equals "
            "match_value. Use for 'what is the latitude of Chicago?', "
            "'find the row for deal 1047'. Falls back to case-insensitive "
            "substring match for string values."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "sheet": {"type": "string"},
                "match_column": {"type": "string"},
                "match_value": {},
                "return_columns": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Columns to return (omit for all populated).",
                },
            },
            "required": ["sheet", "match_column", "match_value"],
        },
    },
    {
        "name": "scenario_filter",
        "description": (
            "Analytical what-if: compute an aggregate with and without a "
            "filter, return both plus delta. Example: 'average temp if I "
            "exclude stations below 100 elevation' — where + aggregation."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "sheet": {"type": "string"},
                "where": {"type": "array", "items": {"type": "object"}},
                "aggregation": {
                    "type": "object",
                    "properties": {
                        "column": {"type": "string"},
                        "agg": {"type": "string", "default": "mean"},
                    },
                    "required": ["column"],
                },
            },
            "required": ["sheet", "where", "aggregation"],
        },
    },
    {
        "name": "compare_scenarios",
        "description": (
            "Run an aggregation under two filter sets and compare. "
            "Example: 'average front gross for Toyota deals vs all deals'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "sheet": {"type": "string"},
                "base_where": {
                    "type": "array",
                    "items": {"type": "object"},
                    "description": "Filter for the base scenario (omit for full sheet).",
                },
                "alt_where": {"type": "array", "items": {"type": "object"}},
                "aggregation": {
                    "type": "object",
                    "properties": {"column": {"type": "string"}, "agg": {"type": "string", "default": "mean"}},
                    "required": ["column"],
                },
            },
            "required": ["sheet", "alt_where", "aggregation"],
        },
    },
]
