"""Data-quality primitives (Bucket B).

Mirrors the rubric's "structural audit" capability for flat-table data:
missing values, duplicates, outliers. Also exports `scan_flat_table` —
run at workbook audit time for any sheet with zero formulas — so these
findings show up in `list_findings` automatically.
"""

from __future__ import annotations

import statistics
from collections import Counter
from typing import Any

from ..models import AuditFinding, WorkbookModel
from . import build_envelope, error
from .view import DataView


def count_missing(wb: WorkbookModel, sheet: str, columns: list[str] | None = None) -> dict:
    """Count missing (None / empty string) values per column."""
    view = DataView.for_sheet(wb, sheet)
    if view is None:
        return error(f"sheet not found: {sheet}")
    target_cols = (
        [view.resolve_column(c) or c for c in columns] if columns else view.populated_columns
    )
    results = []
    for col in target_cols:
        vals = view.column_values(col, skip_none=False)
        missing = sum(1 for _, v in vals if v is None or v == "")
        results.append(
            {
                "column": view.header_label(col),
                "column_letter": col,
                "missing": missing,
                "total": len(vals),
                "missing_pct": round(missing / len(vals) * 100, 2) if vals else 0.0,
            }
        )
    results.sort(key=lambda r: -r["missing"])
    return build_envelope(
        {"sheet": sheet, "columns": results},
        evidence_range=view.evidence_range(),
        row_count=view.row_count,
    )


def find_duplicates(
    wb: WorkbookModel,
    sheet: str,
    columns: list[str],
    max_groups: int = 20,
) -> dict:
    """Find rows that duplicate across the given key columns."""
    view = DataView.for_sheet(wb, sheet)
    if view is None:
        return error(f"sheet not found: {sheet}")
    letters = [view.resolve_column(c) for c in columns]
    if None in letters:
        missing = [c for c, l in zip(columns, letters) if l is None]
        return error(f"columns not found: {missing}")

    keys: dict[tuple, list[int]] = {}
    for row in view.data_rows:
        key = tuple(_hashable(view.value(row, l)) for l in letters)
        if all(k is None for k in key):
            continue
        keys.setdefault(key, []).append(row)

    dups = [{"key": list(k), "rows": rs} for k, rs in keys.items() if len(rs) > 1]
    dups.sort(key=lambda g: -len(g["rows"]))
    total_dup_rows = sum(len(g["rows"]) for g in dups)
    return build_envelope(
        {
            "sheet": sheet,
            "key_columns": [view.header_label(l) for l in letters],
            "duplicate_groups": dups[:max_groups],
            "group_count": len(dups),
            "duplicate_row_count": total_dup_rows,
            "truncated": len(dups) > max_groups,
        },
        evidence_range=view.evidence_range(),
        row_count=view.row_count,
    )


def detect_outliers(
    wb: WorkbookModel,
    sheet: str,
    column: str,
    method: str = "iqr",
    max_outliers: int = 25,
) -> dict:
    """Return outlier rows for a numeric column. Default method: IQR (1.5x)."""
    view = DataView.for_sheet(wb, sheet)
    if view is None:
        return error(f"sheet not found: {sheet}")
    letter = view.resolve_column(column)
    if letter is None:
        return error(f"column not found: {column}")
    nums: list[tuple[int, float]] = [
        (r, float(v)) for r, v in view.column_values(letter)
        if isinstance(v, (int, float)) and not isinstance(v, bool)
    ]
    if len(nums) < 5:
        return build_envelope(
            {"outliers": [], "method": method, "reason": "fewer than 5 numeric values"},
            evidence_range=view.evidence_range(letter),
            row_count=view.row_count,
        )
    values = [v for _, v in nums]
    if method == "iqr":
        lo, hi = _iqr_bounds(values)
    elif method in ("zscore", "z"):
        lo, hi = _zscore_bounds(values)
    else:
        return error(f"unknown method '{method}'; supported: iqr | zscore")
    outliers = [
        {
            "row": r,
            "ref": f"{sheet}!{letter}{r}",
            "value": v,
            "deviation": (v - (lo + hi) / 2),
        }
        for r, v in nums
        if v < lo or v > hi
    ]
    outliers.sort(key=lambda o: -abs(o["deviation"]))
    return build_envelope(
        {
            "sheet": sheet,
            "column": view.header_label(letter),
            "method": method,
            "lower_bound": lo,
            "upper_bound": hi,
            "outlier_count": len(outliers),
            "outliers": outliers[:max_outliers],
        },
        evidence_range=view.evidence_range(letter),
        row_count=view.row_count,
        refs=[o["ref"] for o in outliers[:20]],
    )


# --- integration with audit_workbook -------------------------------------


def scan_flat_table(wb: WorkbookModel) -> list[AuditFinding]:
    """Auto-emit data-quality findings for every flat-table sheet.

    A sheet counts as "flat-table" when it has zero formula cells AND at
    least 20 data rows — heuristic to exclude small lookup panels. For
    each, emit:
      - one `data_missing` finding per column with > 10% missing
      - one `data_duplicate` finding if any group duplicates in the
        column most-likely-to-be-a-key (first string column with mostly
        unique values)
      - one `data_outlier` finding per numeric column with any IQR
        outliers, truncated to the worst one per column
    """
    findings: list[AuditFinding] = []
    for sheet in wb.sheets:
        if sheet.formula_count > 0 or sheet.max_row < 20:
            continue
        view = DataView.for_sheet(wb, sheet.name)
        if view is None or view.row_count < 20:
            continue
        findings.extend(_missing_findings(view))
        findings.extend(_outlier_findings(view))
    return findings


def _missing_findings(view: DataView) -> list[AuditFinding]:
    out: list[AuditFinding] = []
    for col in view.populated_columns:
        vals = view.column_values(col, skip_none=False)
        if not vals:
            continue
        missing = sum(1 for _, v in vals if v is None or v == "")
        pct = missing / len(vals)
        if pct > 0.10 and missing >= 3:
            out.append(
                AuditFinding(
                    severity="info" if pct < 0.30 else "warning",
                    category="data_missing",
                    location=view.evidence_range(col),
                    message=(
                        f"{view.sheet}!{col} ({view.header_label(col)}) has "
                        f"{missing}/{len(vals)} missing values ({pct:.0%})."
                    ),
                    detail={"column": view.header_label(col), "missing": missing, "total": len(vals)},
                    confidence=0.9,
                )
            )
    return out


def _outlier_findings(view: DataView) -> list[AuditFinding]:
    out: list[AuditFinding] = []
    for col in view.populated_columns:
        nums = [(r, float(v)) for r, v in view.column_values(col)
                if isinstance(v, (int, float)) and not isinstance(v, bool)]
        if len(nums) < 10:
            continue
        values = [v for _, v in nums]
        lo, hi = _iqr_bounds(values)
        outliers = [(r, v) for r, v in nums if v < lo or v > hi]
        if outliers:
            # Report the single worst-case outlier per column to avoid noise
            worst = max(outliers, key=lambda t: abs(t[1] - (lo + hi) / 2))
            out.append(
                AuditFinding(
                    severity="info",
                    category="data_outlier",
                    location=f"{view.sheet}!{col}{worst[0]}",
                    message=(
                        f"{view.header_label(col)} at row {worst[0]} is {worst[1]} — "
                        f"outside the IQR band [{lo:.2f}, {hi:.2f}]. "
                        f"{len(outliers)} outlier{'s' if len(outliers) > 1 else ''} total in this column."
                    ),
                    detail={
                        "column": view.header_label(col),
                        "outlier_count": len(outliers),
                        "bounds": [lo, hi],
                    },
                    confidence=0.75,
                )
            )
    return out


# --- helpers -------------------------------------------------------------


def _iqr_bounds(values: list[float], k: float = 1.5) -> tuple[float, float]:
    s = sorted(values)
    n = len(s)
    q1 = s[n // 4]
    q3 = s[(3 * n) // 4]
    iqr = q3 - q1
    return q1 - k * iqr, q3 + k * iqr


def _zscore_bounds(values: list[float], k: float = 3.0) -> tuple[float, float]:
    if len(values) < 2:
        mean = values[0] if values else 0
        return mean, mean
    mean = statistics.fmean(values)
    stdev = statistics.pstdev(values) or 1e-9
    return mean - k * stdev, mean + k * stdev


def _hashable(v: Any) -> Any:
    if v is None or isinstance(v, (str, int, float, bool)):
        return v
    if hasattr(v, "isoformat"):
        return v.isoformat()
    return str(v)


# --- tool schemas --------------------------------------------------------

TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "name": "count_missing",
        "description": "Count missing values per column on a sheet. Use for 'how complete is this data?' diagnostic questions.",
        "input_schema": {
            "type": "object",
            "properties": {
                "sheet": {"type": "string"},
                "columns": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Columns to check (omit for all populated).",
                },
            },
            "required": ["sheet"],
        },
    },
    {
        "name": "find_duplicates",
        "description": (
            "Find rows on a sheet that duplicate across one or more key columns. "
            "Use for 'are there duplicate station ids?' / 'is Deal# unique?'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "sheet": {"type": "string"},
                "columns": {"type": "array", "items": {"type": "string"}, "description": "Key columns."},
                "max_groups": {"type": "integer", "default": 20},
            },
            "required": ["sheet", "columns"],
        },
    },
    {
        "name": "detect_outliers",
        "description": (
            "Return rows whose value in a numeric column is outside the IQR "
            "band (default) or beyond ±3σ. Use for 'any suspicious values?' "
            "/ 'outliers in temperature?'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "sheet": {"type": "string"},
                "column": {"type": "string"},
                "method": {"type": "string", "description": "iqr (default) | zscore"},
                "max_outliers": {"type": "integer", "default": 25},
            },
            "required": ["sheet", "column"],
        },
    },
]
