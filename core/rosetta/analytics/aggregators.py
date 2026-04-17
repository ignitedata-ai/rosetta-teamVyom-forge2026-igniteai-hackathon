"""Descriptive analytics primitives (Bucket A).

Every tool here operates on a DataView, optionally narrowed by a filter.
Values are resolved via the shared Evaluator, so a formula-backed column
returns computed numbers — aggregators are indifferent to the source.

The envelope contract (from analytics/__init__.py) is respected by every
tool: `result`, `evidence`, `chart_data`, `warnings`.
"""

from __future__ import annotations

import math
from collections import Counter
from typing import Any

from ..models import WorkbookModel
from . import build_envelope, error
from .view import DataView

# Aggregation dispatch. Each fn takes a list[float|int], returns a float.
_AGGS = {
    "sum": lambda xs: sum(xs),
    "mean": lambda xs: sum(xs) / len(xs) if xs else None,
    "avg": lambda xs: sum(xs) / len(xs) if xs else None,
    "average": lambda xs: sum(xs) / len(xs) if xs else None,
    "median": lambda xs: _median(xs),
    "min": lambda xs: min(xs) if xs else None,
    "max": lambda xs: max(xs) if xs else None,
    "count": lambda xs: len(xs),
    "stddev": lambda xs: _stddev(xs),
    "std": lambda xs: _stddev(xs),
    "var": lambda xs: _variance(xs),
    "variance": lambda xs: _variance(xs),
}


# --- public ops ----------------------------------------------------------


def aggregate_column(
    wb: WorkbookModel,
    sheet: str,
    column: str,
    agg: str,
    where: list[dict] | None = None,
) -> dict:
    """Compute an aggregate over one numeric column, optionally filtered."""
    view = DataView.for_sheet(wb, sheet)
    if view is None:
        return error(f"sheet not found: {sheet}")
    narrowed = view.filter(where) if where else view
    letter = narrowed.resolve_column(column)
    if letter is None:
        return error(f"column not found on '{sheet}': {column}")
    agg_key = agg.lower().strip()
    if agg_key not in _AGGS:
        return error(f"unknown aggregation '{agg}'; supported: {sorted(set(_AGGS))}")

    rows = narrowed.column_values(letter)
    nums = [_num(v) for _, v in rows if _is_numeric(v)]
    non_numeric = len(rows) - len(nums)
    warnings = []
    if non_numeric:
        warnings.append(f"{non_numeric} non-numeric values skipped in column '{narrowed.header_label(letter)}'")
    if not nums and agg_key not in ("count",):
        return build_envelope(
            None,
            evidence_range=narrowed.evidence_range(letter),
            row_count=narrowed.row_count,
            warnings=warnings + ["no numeric values in column"],
        )
    result = _AGGS[agg_key](nums)
    return build_envelope(
        {
            "column": narrowed.header_label(letter),
            "aggregation": agg_key,
            "value": result,
            "n": len(nums),
            "filtered_rows": narrowed.row_count,
        },
        evidence_range=narrowed.evidence_range(letter),
        row_count=narrowed.row_count,
        warnings=warnings,
    )


def unique_values(
    wb: WorkbookModel,
    sheet: str,
    column: str,
    limit: int = 50,
    where: list[dict] | None = None,
) -> dict:
    """Return the set of distinct values in a column with per-value counts."""
    view = DataView.for_sheet(wb, sheet)
    if view is None:
        return error(f"sheet not found: {sheet}")
    narrowed = view.filter(where) if where else view
    letter = narrowed.resolve_column(column)
    if letter is None:
        return error(f"column not found: {column}")
    rows = narrowed.column_values(letter)
    counter: Counter = Counter(_hashable(v) for _, v in rows)
    most = counter.most_common(limit)
    return build_envelope(
        {
            "column": narrowed.header_label(letter),
            "distinct_count": len(counter),
            "values": [{"value": k, "count": c} for k, c in most],
            "truncated": len(counter) > limit,
        },
        evidence_range=narrowed.evidence_range(letter),
        row_count=narrowed.row_count,
    )


def top_n(
    wb: WorkbookModel,
    sheet: str,
    column: str,
    n: int = 5,
    order: str = "desc",
    include: list[str] | None = None,
    where: list[dict] | None = None,
) -> dict:
    """Return the top (or bottom) N rows by a numeric column."""
    view = DataView.for_sheet(wb, sheet)
    if view is None:
        return error(f"sheet not found: {sheet}")
    narrowed = view.filter(where) if where else view
    letter = narrowed.resolve_column(column)
    if letter is None:
        return error(f"column not found: {column}")
    rows = [(r, _num(v)) for r, v in narrowed.column_values(letter) if _is_numeric(v)]
    if not rows:
        return build_envelope(
            {"column": narrowed.header_label(letter), "rows": []},
            evidence_range=narrowed.evidence_range(letter),
            row_count=narrowed.row_count,
            warnings=["no numeric values in column"],
        )
    rows.sort(key=lambda t: t[1], reverse=order.lower() != "asc")
    picks = rows[: max(1, n)]

    include_cols = (
        [narrowed.resolve_column(c) or c for c in include] if include else narrowed.populated_columns[:6]
    )
    out_rows: list[dict] = []
    for row_n, sort_val in picks:
        out_rows.append(
            {
                "row": row_n,
                "ref": f"{sheet}!A{row_n}",
                "sort_value": sort_val,
                "values": {narrowed.header_label(c): narrowed.value(row_n, c) for c in include_cols},
            }
        )
    return build_envelope(
        {
            "column": narrowed.header_label(letter),
            "order": order,
            "n_requested": n,
            "rows": out_rows,
        },
        evidence_range=narrowed.evidence_range(letter),
        row_count=narrowed.row_count,
        refs=[r["ref"] for r in out_rows],
        chart_data={
            "type": "bar",
            "x": [f"row {r['row']}" for r in out_rows],
            "y": [r["sort_value"] for r in out_rows],
            "x_label": "row",
            "y_label": narrowed.header_label(letter),
        },
    )


def group_aggregate(
    wb: WorkbookModel,
    sheet: str,
    group_by: str,
    value_col: str,
    agg: str = "sum",
    where: list[dict] | None = None,
    top: int = 20,
) -> dict:
    """Group rows by one column, aggregate another. Pivot-table semantics
    for a single value aggregation."""
    view = DataView.for_sheet(wb, sheet)
    if view is None:
        return error(f"sheet not found: {sheet}")
    narrowed = view.filter(where) if where else view
    gcol = narrowed.resolve_column(group_by)
    vcol = narrowed.resolve_column(value_col)
    if gcol is None:
        return error(f"group_by column not found: {group_by}")
    if vcol is None:
        return error(f"value column not found: {value_col}")
    agg_key = agg.lower().strip()
    if agg_key not in _AGGS:
        return error(f"unknown aggregation '{agg}'")
    fn = _AGGS[agg_key]

    groups: dict[Any, list[float]] = {}
    for row in narrowed.data_rows:
        k = narrowed.value(row, gcol)
        v = narrowed.value(row, vcol)
        if k is None or k == "" or not _is_numeric(v):
            continue
        groups.setdefault(_hashable(k), []).append(_num(v))

    results = [
        {"group": k, "value": fn(vs), "n": len(vs)}
        for k, vs in groups.items()
    ]
    # Sort by aggregate descending (or ascending for min) for a sensible display
    results.sort(key=lambda r: (r["value"] is None, -(r["value"] or 0)))
    truncated = len(results) > top
    results = results[:top]

    return build_envelope(
        {
            "group_by": narrowed.header_label(gcol),
            "value_col": narrowed.header_label(vcol),
            "aggregation": agg_key,
            "groups": results,
            "group_count": len(groups),
            "truncated": truncated,
        },
        evidence_range=narrowed.evidence_range(),
        row_count=narrowed.row_count,
        chart_data={
            "type": "bar",
            "x": [str(r["group"]) for r in results],
            "y": [r["value"] for r in results],
            "x_label": narrowed.header_label(gcol),
            "y_label": f"{agg_key}({narrowed.header_label(vcol)})",
        },
    )


def histogram(
    wb: WorkbookModel,
    sheet: str,
    column: str,
    bins: int = 10,
    where: list[dict] | None = None,
) -> dict:
    """Return a histogram of a numeric column — equal-width bins."""
    view = DataView.for_sheet(wb, sheet)
    if view is None:
        return error(f"sheet not found: {sheet}")
    narrowed = view.filter(where) if where else view
    letter = narrowed.resolve_column(column)
    if letter is None:
        return error(f"column not found: {column}")
    nums = [_num(v) for _, v in narrowed.column_values(letter) if _is_numeric(v)]
    if not nums:
        return build_envelope(
            {"bins": [], "column": narrowed.header_label(letter)},
            evidence_range=narrowed.evidence_range(letter),
            row_count=narrowed.row_count,
            warnings=["no numeric values"],
        )
    bins = max(2, min(bins, 50))
    lo, hi = min(nums), max(nums)
    if lo == hi:
        return build_envelope(
            {
                "column": narrowed.header_label(letter),
                "bins": [{"lo": lo, "hi": hi, "count": len(nums)}],
                "n": len(nums),
            },
            evidence_range=narrowed.evidence_range(letter),
            row_count=narrowed.row_count,
        )
    width = (hi - lo) / bins
    counts = [0] * bins
    for v in nums:
        idx = min(int((v - lo) / width), bins - 1)
        counts[idx] += 1
    bin_list = [
        {"lo": lo + i * width, "hi": lo + (i + 1) * width, "count": c}
        for i, c in enumerate(counts)
    ]
    return build_envelope(
        {"column": narrowed.header_label(letter), "bins": bin_list, "n": len(nums)},
        evidence_range=narrowed.evidence_range(letter),
        row_count=narrowed.row_count,
        chart_data={
            "type": "bar",
            "x": [f"{b['lo']:.1f}–{b['hi']:.1f}" for b in bin_list],
            "y": [b["count"] for b in bin_list],
            "x_label": narrowed.header_label(letter),
            "y_label": "count",
        },
    )


# --- tool schemas --------------------------------------------------------

TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "name": "aggregate_column",
        "description": (
            "Compute an aggregate (sum / mean / median / min / max / count / stddev) "
            "over one column. Optional 'where' filters rows first. Use for 'what is "
            "the average X?', 'how many rows?', 'total of Y' questions."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "sheet": {"type": "string"},
                "column": {"type": "string", "description": "Column letter or header label."},
                "agg": {"type": "string", "description": "sum | mean | median | min | max | count | stddev"},
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
            },
            "required": ["sheet", "column", "agg"],
        },
    },
    {
        "name": "unique_values",
        "description": (
            "Return distinct values of a column with counts. Use for "
            "'which stations / categories / months appear?'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "sheet": {"type": "string"},
                "column": {"type": "string"},
                "limit": {"type": "integer", "default": 50},
                "where": {"type": "array", "items": {"type": "object"}},
            },
            "required": ["sheet", "column"],
        },
    },
    {
        "name": "top_n",
        "description": (
            "Return the top (or bottom) N rows ranked by a numeric column. "
            "Use for 'top 5 highest X', 'lowest 3 by Y'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "sheet": {"type": "string"},
                "column": {"type": "string", "description": "Ranking column"},
                "n": {"type": "integer", "default": 5},
                "order": {"type": "string", "description": "desc (top) or asc (bottom)", "default": "desc"},
                "include": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Extra columns to include in each returned row",
                },
                "where": {"type": "array", "items": {"type": "object"}},
            },
            "required": ["sheet", "column"],
        },
    },
    {
        "name": "group_aggregate",
        "description": (
            "Pivot-style grouping: group by one column, aggregate another. "
            "Use for 'average X by Y', 'total revenue by region'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "sheet": {"type": "string"},
                "group_by": {"type": "string"},
                "value_col": {"type": "string"},
                "agg": {"type": "string", "default": "sum"},
                "top": {"type": "integer", "default": 20},
                "where": {"type": "array", "items": {"type": "object"}},
            },
            "required": ["sheet", "group_by", "value_col"],
        },
    },
    {
        "name": "histogram",
        "description": "Compute an equal-width histogram for a numeric column.",
        "input_schema": {
            "type": "object",
            "properties": {
                "sheet": {"type": "string"},
                "column": {"type": "string"},
                "bins": {"type": "integer", "default": 10},
                "where": {"type": "array", "items": {"type": "object"}},
            },
            "required": ["sheet", "column"],
        },
    },
]


# --- helpers -------------------------------------------------------------


def _is_numeric(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _num(v: Any) -> float:
    return float(v) if _is_numeric(v) else 0.0


def _hashable(v: Any) -> Any:
    """Make a value safe for use as a dict key / Counter key."""
    if v is None:
        return None
    if isinstance(v, (str, int, float, bool)):
        return v
    if hasattr(v, "isoformat"):
        return v.isoformat()
    return str(v)


def _median(xs: list[float]) -> float | None:
    if not xs:
        return None
    s = sorted(xs)
    n = len(s)
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2


def _variance(xs: list[float]) -> float | None:
    if len(xs) < 2:
        return None
    m = sum(xs) / len(xs)
    return sum((x - m) ** 2 for x in xs) / (len(xs) - 1)


def _stddev(xs: list[float]) -> float | None:
    v = _variance(xs)
    return math.sqrt(v) if v is not None else None
