"""Analytics toolset for Rosetta.

This package extends the coordinator's tool surface from formula-centric
operations (trace / forward_impact / what_if) to data-centric operations
(aggregate / filter / group / goal-seek / sensitivity / SQL / time-series).

Every analytics tool shares the same result envelope:

    {
      "result":     <scalar | list | dict>,
      "evidence":   {"range": "Sheet!A2:K773", "row_count": 772, "refs": [...]},
      "chart_data": {"type": "bar"|"line"|"tornado", "x": [...], "y": [...]} | None,
      "warnings":   [...],
    }

The auditor consumes `evidence.range` to verify range-citation claims the
coordinator makes in prose. `chart_data` drives the UI's chart cards.

Tools are implemented as pure functions over `WorkbookModel`; their JSON
schemas live alongside. `TOOL_SCHEMAS` aggregates every schema from every
submodule; `execute_analytics_tool` dispatches by name. `core.rosetta.tools`
imports both and merges them with the existing formula-centric registry.
"""

from __future__ import annotations

from typing import Any

from ..models import WorkbookModel


def build_envelope(
    result: Any,
    *,
    evidence_range: str | None = None,
    row_count: int | None = None,
    refs: list[str] | None = None,
    chart_data: dict | None = None,
    warnings: list[str] | None = None,
) -> dict:
    """Construct the standard analytics-tool result envelope.

    All fields except `result` are optional — missing evidence or chart data
    is represented as `None` rather than omitted so downstream consumers
    don't have to branch on key presence.
    """
    return {
        "result": result,
        "evidence": {
            "range": evidence_range,
            "row_count": row_count,
            "refs": refs or [],
        },
        "chart_data": chart_data,
        "warnings": warnings or [],
    }


def error(message: str, **kwargs: Any) -> dict:
    """Uniform error envelope. `kwargs` are included for context without
    polluting the `result` field."""
    return {"error": message, **kwargs}
