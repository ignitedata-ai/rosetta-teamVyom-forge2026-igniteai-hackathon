"""Adapter: map our QA coordinator result into the service layer's answer dict.

The coordinator returns:
    {
      "answer": str,
      "trace": Optional[dict],
      "evidence": list[{"ref": str}],
      "audit_status": "passed" | "partial" | "unknown",
      "confidence": float,
      "escalated": bool,
      "tool_calls_made": int,
      "active_entity": Optional[str],
      "scenario_overrides": dict,
      ...
    }

Akash's ExcelAgentService.ask_question returns a dict shaped for
AskQuestionResponse with:
    {success, answer, code_used, iterations, error, execution_time_ms,
     query_id, conversation_id, input_tokens, output_tokens, cost_usd}

This bridge produces the shared subset; the caller (service layer) wraps
with query_id / conversation_id / execution_time_ms which require context
outside our coordinator.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from .graph_viz import trace_to_graph


def coordinator_to_service_result(
    coord_result: dict,
    *,
    input_tokens: int,
    output_tokens: int,
    total_cost_usd: Decimal,
) -> dict[str, Any]:
    """Convert our coordinator dict into the partial shape the service uses.

    Caller overlays query_id, conversation_id, execution_time_ms before
    returning to the API.
    """
    audit_status = coord_result.get("audit_status", "unknown")
    success = audit_status != "unknown"

    return {
        "success": success,
        "answer": coord_result.get("answer"),
        # Rosetta doesn't generate code. Fill code_used with a short tool-call
        # trail if the answer was tool-calling, otherwise None. This gives
        # Akash's UI something readable in the "View Code" panel without
        # ever producing ungrounded code.
        "code_used": _tool_trail_from_result(coord_result),
        "iterations": coord_result.get("tool_calls_made"),
        "error": None if success else _extract_error(coord_result),
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cost_usd": float(total_cost_usd),
        # --- Extension fields (optional in AskQuestionResponse) ---
        "trace": coord_result.get("trace"),
        # Graph-ready payload derived from the trace tree. Returns None when
        # the trace is absent or too small to be worth rendering (<2 cells),
        # so the UI naturally skips rendering for trivial answers.
        "graph_data": trace_to_graph(coord_result.get("trace")),
        # Analytics chart payload — surfaced directly from the last tool
        # that returned one (sensitivity tornado / goal-seek convergence /
        # group-aggregate bar / time-bucket line). None when the question
        # didn't produce a chartable result.
        "chart_data": coord_result.get("chart_data"),
        "audit_status": audit_status,
        "evidence_refs": [e.get("ref") for e in coord_result.get("evidence", []) if e.get("ref")],
        "active_entity": coord_result.get("active_entity"),
        "scenario_overrides": coord_result.get("scenario_overrides", {}),
    }


def _tool_trail_from_result(coord_result: dict) -> str | None:
    """Produce a lightweight pseudocode trail from the tool_call_log if attached.

    Returns None if no tool activity (which happens for cached responses
    or no-API-key fallback).
    """
    trail = coord_result.get("_tool_trail")
    if not trail:
        return None
    lines: list[str] = []
    for tc in trail:
        name = tc.get("tool_name", "?")
        args = tc.get("input", {}) or {}
        args_str = ", ".join(f"{k}={v!r}" for k, v in list(args.items())[:3])
        lines.append(f"# {name}({args_str})")
    return "\n".join(lines) or None


def _extract_error(coord_result: dict) -> str:
    """Compose an error message for partial/unknown audit results."""
    audit = coord_result.get("audit_status", "unknown")
    if audit == "partial":
        return "Answer was only partially verifiable; see message for details."
    return coord_result.get("answer") or "No grounded answer available."
