"""Time-series analytics (Bucket F).

Date-aware slicing: range filter + aggregate, bucket-and-aggregate by
week/month/quarter/year, simple trend summary (linear regression slope,
R²). Reuses DataView for column resolution and evidence.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from ..models import WorkbookModel
from . import build_envelope, error
from .aggregators import _AGGS, _is_numeric, _num
from .view import DataView

_BUCKET_CHOICES = {"day", "week", "month", "quarter", "year"}


def date_range_aggregate(
    wb: WorkbookModel,
    sheet: str,
    date_column: str,
    start: str,
    end: str,
    value_column: str,
    agg: str = "sum",
) -> dict:
    """Aggregate a value column over rows whose date falls in [start, end]."""
    view = DataView.for_sheet(wb, sheet)
    if view is None:
        return error(f"sheet not found: {sheet}")
    dcol = view.resolve_column(date_column)
    vcol = view.resolve_column(value_column)
    if dcol is None:
        return error(f"date column not found: {date_column}")
    if vcol is None:
        return error(f"value column not found: {value_column}")
    start_d = _parse_date(start)
    end_d = _parse_date(end)
    if start_d is None or end_d is None:
        return error(f"invalid date range: start={start!r}, end={end!r} (use ISO YYYY-MM-DD)")
    if agg.lower() not in _AGGS:
        return error(f"unknown aggregation '{agg}'")

    matched_rows: list[int] = []
    values: list[float] = []
    for row in view.data_rows:
        d = _to_date(view.value(row, dcol))
        if d is None or d < start_d or d > end_d:
            continue
        v = view.value(row, vcol)
        if _is_numeric(v):
            values.append(_num(v))
            matched_rows.append(row)
    fn = _AGGS[agg.lower()]
    result_val = fn(values)
    return build_envelope(
        {
            "sheet": sheet,
            "date_column": view.header_label(dcol),
            "value_column": view.header_label(vcol),
            "aggregation": agg,
            "start": start_d.isoformat(),
            "end": end_d.isoformat(),
            "matched_rows": len(matched_rows),
            "value": result_val,
        },
        evidence_range=(
            f"{sheet}!{vcol}{matched_rows[0]}:{vcol}{matched_rows[-1]}" if matched_rows else view.evidence_range(vcol)
        ),
        row_count=len(matched_rows),
    )


def time_bucket_aggregate(
    wb: WorkbookModel,
    sheet: str,
    date_column: str,
    value_column: str,
    bucket: str = "month",
    agg: str = "sum",
    limit: int = 24,
) -> dict:
    """Group rows by date bucket (day/week/month/quarter/year) and aggregate."""
    b = bucket.lower()
    if b not in _BUCKET_CHOICES:
        return error(f"invalid bucket '{bucket}'; use one of {sorted(_BUCKET_CHOICES)}")
    view = DataView.for_sheet(wb, sheet)
    if view is None:
        return error(f"sheet not found: {sheet}")
    dcol = view.resolve_column(date_column)
    vcol = view.resolve_column(value_column)
    if dcol is None:
        return error(f"date column not found: {date_column}")
    if vcol is None:
        return error(f"value column not found: {value_column}")
    if agg.lower() not in _AGGS:
        return error(f"unknown aggregation '{agg}'")
    fn = _AGGS[agg.lower()]

    buckets: dict[str, list[float]] = {}
    for row in view.data_rows:
        d = _to_date(view.value(row, dcol))
        v = view.value(row, vcol)
        if d is None or not _is_numeric(v):
            continue
        key = _bucket_key(d, b)
        buckets.setdefault(key, []).append(_num(v))

    series = [{"bucket": k, "value": fn(v), "n": len(v)} for k, v in sorted(buckets.items())]
    truncated = len(series) > limit
    series = series[-limit:]  # most recent N buckets

    return build_envelope(
        {
            "sheet": sheet,
            "date_column": view.header_label(dcol),
            "value_column": view.header_label(vcol),
            "bucket": b,
            "aggregation": agg,
            "series": series,
            "bucket_count": len(buckets),
            "truncated": truncated,
        },
        evidence_range=view.evidence_range(vcol),
        row_count=view.row_count,
        chart_data={
            "type": "line",
            "x": [s["bucket"] for s in series],
            "y": [s["value"] for s in series],
            "x_label": b,
            "y_label": f"{agg}({view.header_label(vcol)})",
        },
    )


def trend_summary(
    wb: WorkbookModel,
    sheet: str,
    date_column: str,
    value_column: str,
    bucket: str = "month",
) -> dict:
    """Fit a linear trend over bucketed values. Returns slope, R², start/end."""
    bucketed = time_bucket_aggregate(wb, sheet, date_column, value_column, bucket, agg="mean", limit=1000)
    if "error" in bucketed:
        return bucketed
    series = bucketed["result"]["series"]
    if len(series) < 3:
        return build_envelope(
            {"trend": "insufficient data", "series_length": len(series)},
            evidence_range=bucketed["evidence"].get("range"),
            row_count=bucketed["evidence"].get("row_count"),
            warnings=["need at least 3 buckets to fit a trend"],
        )
    # x = index of bucket (0..n-1); y = aggregated value
    xs = list(range(len(series)))
    ys = [s["value"] for s in series if s["value"] is not None]
    if len(ys) != len(xs):
        xs = list(range(len(ys)))
    slope, intercept, r2 = _linear_fit(xs, ys)
    first = ys[0] if ys else None
    last = ys[-1] if ys else None
    direction = _describe_slope(slope, first)
    return build_envelope(
        {
            "sheet": sheet,
            "bucket": bucket,
            "value_column": bucketed["result"]["value_column"],
            "slope": slope,
            "intercept": intercept,
            "r_squared": r2,
            "first_bucket": series[0]["bucket"],
            "last_bucket": series[-1]["bucket"],
            "first_value": first,
            "last_value": last,
            "total_change": (last - first) if (first is not None and last is not None) else None,
            "direction": direction,
            "buckets": len(series),
        },
        evidence_range=bucketed["evidence"].get("range"),
        row_count=bucketed["evidence"].get("row_count"),
        chart_data=bucketed["chart_data"],
    )


# --- helpers -------------------------------------------------------------


def _parse_date(s: str) -> date | None:
    if isinstance(s, (datetime, date)):
        return s if isinstance(s, date) else s.date()
    if not isinstance(s, str):
        return None
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%m/%d/%Y", "%d/%m/%Y", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(s.strip(), fmt).date()
        except ValueError:
            continue
    return None


def _to_date(v: Any) -> date | None:
    if v is None:
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    if isinstance(v, str):
        return _parse_date(v)
    return None


def _bucket_key(d: date, bucket: str) -> str:
    if bucket == "day":
        return d.isoformat()
    if bucket == "week":
        iso = d.isocalendar()
        return f"{iso[0]}-W{iso[1]:02d}"
    if bucket == "month":
        return f"{d.year:04d}-{d.month:02d}"
    if bucket == "quarter":
        q = (d.month - 1) // 3 + 1
        return f"{d.year:04d}-Q{q}"
    return f"{d.year:04d}"


def _linear_fit(xs: list[float], ys: list[float]) -> tuple[float, float, float]:
    """Ordinary least squares. Returns (slope, intercept, R²)."""
    n = len(xs)
    if n < 2:
        return 0.0, (ys[0] if ys else 0.0), 0.0
    mx = sum(xs) / n
    my = sum(ys) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    den = sum((x - mx) ** 2 for x in xs)
    slope = num / den if den else 0.0
    intercept = my - slope * mx
    ss_tot = sum((y - my) ** 2 for y in ys)
    ss_res = sum((y - (slope * x + intercept)) ** 2 for x, y in zip(xs, ys))
    r2 = 1 - (ss_res / ss_tot) if ss_tot else 0.0
    return slope, intercept, r2


def _describe_slope(slope: float, first: float | None) -> str:
    if first in (None, 0):
        return "rising" if slope > 0 else ("falling" if slope < 0 else "flat")
    pct = slope / abs(first) * 100
    if abs(pct) < 0.5:
        return "flat"
    return "rising" if slope > 0 else "falling"


# --- tool schemas --------------------------------------------------------

TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "name": "date_range_aggregate",
        "description": (
            "Aggregate a numeric column over rows whose date column falls "
            "in [start, end]. Use for 'average X between date A and B'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "sheet": {"type": "string"},
                "date_column": {"type": "string"},
                "start": {"type": "string", "description": "ISO date YYYY-MM-DD"},
                "end": {"type": "string", "description": "ISO date YYYY-MM-DD"},
                "value_column": {"type": "string"},
                "agg": {"type": "string", "default": "sum"},
            },
            "required": ["sheet", "date_column", "start", "end", "value_column"],
        },
    },
    {
        "name": "time_bucket_aggregate",
        "description": (
            "Group rows by date bucket (day/week/month/quarter/year) and "
            "aggregate a value column. Use for 'monthly revenue', 'daily "
            "average temperature'. Returns time-series data for charts."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "sheet": {"type": "string"},
                "date_column": {"type": "string"},
                "value_column": {"type": "string"},
                "bucket": {"type": "string", "description": "day | week | month | quarter | year"},
                "agg": {"type": "string", "default": "sum"},
                "limit": {"type": "integer", "default": 24},
            },
            "required": ["sheet", "date_column", "value_column"],
        },
    },
    {
        "name": "trend_summary",
        "description": (
            "Fit a linear trend (OLS) to a bucketed time series and return "
            "slope, R², first/last values, and direction. Use for 'is X "
            "trending up?' / 'month-over-month growth'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "sheet": {"type": "string"},
                "date_column": {"type": "string"},
                "value_column": {"type": "string"},
                "bucket": {"type": "string", "default": "month"},
            },
            "required": ["sheet", "date_column", "value_column"],
        },
    },
]
