"""Descriptive stats + correlation (Bucket G)."""

from __future__ import annotations

import math
import statistics
from typing import Any

from ..models import WorkbookModel
from . import build_envelope, error
from .aggregators import _is_numeric, _num
from .view import DataView


def describe(wb: WorkbookModel, sheet: str, column: str) -> dict:
    """Five-number summary + mean / stdev / missing counts for one column."""
    view = DataView.for_sheet(wb, sheet)
    if view is None:
        return error(f"sheet not found: {sheet}")
    letter = view.resolve_column(column)
    if letter is None:
        return error(f"column not found: {column}")
    rows = view.column_values(letter, skip_none=False)
    nums = [_num(v) for _, v in rows if _is_numeric(v)]
    non_numeric = sum(1 for _, v in rows if v is not None and v != "" and not _is_numeric(v))
    missing = sum(1 for _, v in rows if v is None or v == "")
    if not nums:
        return build_envelope(
            {"column": view.header_label(letter), "n": 0, "missing": missing, "non_numeric": non_numeric},
            evidence_range=view.evidence_range(letter),
            row_count=view.row_count,
        )
    s = sorted(nums)
    n = len(s)
    return build_envelope(
        {
            "column": view.header_label(letter),
            "n": n,
            "mean": statistics.fmean(nums),
            "stdev": statistics.pstdev(nums) if n > 1 else 0.0,
            "min": s[0],
            "p25": s[n // 4],
            "median": s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2,
            "p75": s[(3 * n) // 4],
            "max": s[-1],
            "missing": missing,
            "non_numeric": non_numeric,
        },
        evidence_range=view.evidence_range(letter),
        row_count=view.row_count,
    )


def correlate(wb: WorkbookModel, sheet: str, column_a: str, column_b: str) -> dict:
    """Pearson correlation between two numeric columns (paired per row)."""
    view = DataView.for_sheet(wb, sheet)
    if view is None:
        return error(f"sheet not found: {sheet}")
    la = view.resolve_column(column_a)
    lb = view.resolve_column(column_b)
    if la is None or lb is None:
        return error(f"columns not found: {column_a if la is None else column_b}")

    pairs: list[tuple[float, float]] = []
    for row in view.data_rows:
        va = view.value(row, la)
        vb = view.value(row, lb)
        if _is_numeric(va) and _is_numeric(vb):
            pairs.append((_num(va), _num(vb)))
    if len(pairs) < 3:
        return build_envelope(
            {"r": None, "n": len(pairs), "reason": "need ≥3 paired observations"},
            evidence_range=view.evidence_range(),
            row_count=view.row_count,
        )
    r = _pearson(pairs)
    return build_envelope(
        {
            "column_a": view.header_label(la),
            "column_b": view.header_label(lb),
            "n": len(pairs),
            "r": r,
            "r_squared": r * r,
            "strength": _describe_r(r),
            "direction": "positive" if r > 0 else "negative" if r < 0 else "none",
        },
        evidence_range=view.evidence_range(),
        row_count=view.row_count,
    )


# --- helpers -------------------------------------------------------------


def _pearson(pairs: list[tuple[float, float]]) -> float:
    n = len(pairs)
    sx = sum(p[0] for p in pairs)
    sy = sum(p[1] for p in pairs)
    sxx = sum(p[0] * p[0] for p in pairs)
    syy = sum(p[1] * p[1] for p in pairs)
    sxy = sum(p[0] * p[1] for p in pairs)
    den = math.sqrt((n * sxx - sx * sx) * (n * syy - sy * sy))
    return (n * sxy - sx * sy) / den if den else 0.0


def _describe_r(r: float) -> str:
    a = abs(r)
    if a >= 0.9:
        return "very strong"
    if a >= 0.7:
        return "strong"
    if a >= 0.4:
        return "moderate"
    if a >= 0.2:
        return "weak"
    return "negligible"


# --- tool schemas --------------------------------------------------------

TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "name": "describe",
        "description": (
            "Return a statistical summary of one numeric column: n, mean, "
            "stdev, min, p25, median, p75, max, missing count, non-numeric count."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"sheet": {"type": "string"}, "column": {"type": "string"}},
            "required": ["sheet", "column"],
        },
    },
    {
        "name": "correlate",
        "description": (
            "Compute Pearson correlation between two numeric columns "
            "(paired per row). Returns r, r², strength label, direction."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "sheet": {"type": "string"},
                "column_a": {"type": "string"},
                "column_b": {"type": "string"},
            },
            "required": ["sheet", "column_a", "column_b"],
        },
    },
]
