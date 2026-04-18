"""Reasoning trace — the structured defensibility payload returned with every answer.

Drives two UI surfaces:
  • The live "ReasoningTheater" shown while Claude is reasoning (stages light up
    one by one).
  • The post-hoc "ReasoningModal" opened from the "View reasoning →" link under
    every answer. Carries the narrative, pipeline state, tool-call log and the
    four headline KPI cards.

Design principles
-----------------
Deterministic. The narrative is generated from the tool-call log, the audit
result, and the active entity — not from a second LLM call. Two identical
runs produce byte-identical reasoning traces; that's exactly what a
defensibility artefact must guarantee.

Cheap. Everything here is computed from state we already have. No new tool
calls, no new model calls.

Stable. The stage list (UNDERSTAND → LOCATE → COMPUTE → SIMULATE → VERIFY)
is fixed. Individual stages can be "skipped" (dashed grey in the UI) if no
tool activated them, but the stage set itself never changes so the pipeline
graphic has consistent geometry across every question.
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field

from .conversation import ToolCall


# ---------------------------------------------------------------------------
# Stage taxonomy
# ---------------------------------------------------------------------------
#
# Stages mirror the 3001 design (Planner / Data Agent / Insight / Simulation /
# Validator) but renamed for Rosetta's graph-based workbook reasoning.
#
# Each tool is mapped to exactly one stage. Tools the coordinator invokes
# that aren't listed here fall into COMPUTE by default — we'd rather surface
# them than hide them.
#
# The ordering of STAGES is the left-to-right pipeline order shown in the UI.

STAGE_UNDERSTAND = "understand"
STAGE_LOCATE = "locate"
STAGE_COMPUTE = "compute"
STAGE_SIMULATE = "simulate"
STAGE_VERIFY = "verify"

STAGES: list[dict[str, str]] = [
    {
        "id": STAGE_UNDERSTAND,
        "symbol": "U",
        "label": "Understand",
        "role": "Parse the question · resolve follow-up references.",
    },
    {
        "id": STAGE_LOCATE,
        "symbol": "L",
        "label": "Locate",
        "role": "Find the cells, named ranges, or tables at issue.",
    },
    {
        "id": STAGE_COMPUTE,
        "symbol": "C",
        "label": "Compute",
        "role": "Read values · trace formulas · run analytics.",
    },
    {
        "id": STAGE_SIMULATE,
        "symbol": "S",
        "label": "Simulate",
        "role": "Recompute the workbook under counterfactual inputs.",
    },
    {
        "id": STAGE_VERIFY,
        "symbol": "V",
        "label": "Verify",
        "role": "Cross-check every cited number against the workbook.",
    },
]

# Tool → stage map. Tools not listed here default to COMPUTE.
TOOL_STAGE: dict[str, str] = {
    # Locate — which cells / ranges are we talking about?
    "find_cells": STAGE_LOCATE,
    "resolve_named_range": STAGE_LOCATE,
    "list_named_ranges": STAGE_LOCATE,
    "list_sheets": STAGE_LOCATE,
    "get_workbook_summary": STAGE_LOCATE,
    "sql_schema": STAGE_LOCATE,
    "list_pivot_tables": STAGE_LOCATE,
    # Compute — read or trace the answer.
    "get_cell": STAGE_COMPUTE,
    "backward_trace": STAGE_COMPUTE,
    "forward_impact": STAGE_COMPUTE,
    "explain_circular": STAGE_COMPUTE,
    "compare_regions": STAGE_COMPUTE,
    "join_on_key": STAGE_COMPUTE,
    "get_pivot_table": STAGE_COMPUTE,
    "aggregate_column": STAGE_COMPUTE,
    "filter_rows": STAGE_COMPUTE,
    "group_aggregate": STAGE_COMPUTE,
    "top_n": STAGE_COMPUTE,
    "lookup_row": STAGE_COMPUTE,
    "time_bucket_aggregate": STAGE_COMPUTE,
    "trend_summary": STAGE_COMPUTE,
    "describe": STAGE_COMPUTE,
    "correlate": STAGE_COMPUTE,
    "detect_outliers": STAGE_COMPUTE,
    "unique_values": STAGE_COMPUTE,
    "histogram": STAGE_COMPUTE,
    "count_missing": STAGE_COMPUTE,
    "find_duplicates": STAGE_COMPUTE,
    "sql_query": STAGE_COMPUTE,
    "list_findings": STAGE_COMPUTE,
    # Simulate — counterfactual math.
    "what_if": STAGE_SIMULATE,
    "scenario_recalc": STAGE_SIMULATE,
    "scenario_filter": STAGE_SIMULATE,
    "compare_scenarios": STAGE_SIMULATE,
    "goal_seek": STAGE_SIMULATE,
    "sensitivity": STAGE_SIMULATE,
    "elasticity": STAGE_SIMULATE,
}


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class NarrativeStep(BaseModel):
    """One paragraph in the 'How it works' tab."""

    title: str
    body: str


class StageState(BaseModel):
    """Whether a pipeline stage ran, was skipped, or failed."""

    id: str
    symbol: str
    label: str
    role: str
    status: str = "skipped"  # "ok" | "skipped" | "failed"
    tool_count: int = 0
    total_ms: int = 0


class ToolCallSummary(BaseModel):
    """One tool invocation, for the (hidden) tool-log tail."""

    stage: str
    tool_name: str
    args_preview: str
    result_preview: str
    latency_ms: int


class ReasoningTrace(BaseModel):
    """Complete defensibility payload for a single answer."""

    # Intent classification (very light — feeds the first narrative step).
    intent: str  # "formula-trace" | "lookup" | "analytics" | "what-if" | "audit" | "general"
    active_entity: Optional[str] = None
    inherited_entity: bool = False  # carried over from prior turn

    # Pipeline state (one entry per stage, in fixed order).
    stages: list[StageState] = Field(default_factory=list)

    # Compact tool log for the (internal) trace panel.
    tool_calls: list[ToolCallSummary] = Field(default_factory=list)

    # KPI card values.
    verdict: str  # "Verified" | "Partial" | "Needs review"
    verdict_tone: str  # "emerald" | "amber" | "red"
    latency_ms: int
    cells_referenced: int
    steps: int

    # Narrative for the "How it works" tab.
    narrative: list[NarrativeStep] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Intent classification (regex-grade; matches existing qa.py router tone)
# ---------------------------------------------------------------------------


def classify_intent(question: str) -> str:
    q = question.lower()
    if any(kw in q for kw in ("what if", "what-if", "if we ", "if i ", "suppose ", "assuming ")):
        return "what-if"
    if any(kw in q for kw in ("how is", "how does", "how are", "explain", "calculated", "formula")):
        return "formula-trace"
    if any(kw in q for kw in ("stale", "circular", "hidden", "issue", "anomaly", "warning", "audit", "findings")):
        return "audit"
    if any(kw in q for kw in ("average", "mean", "median", "total ", "sum of", "distribution", "correlation",
                              "top ", "bottom ", "trend", "group by", "count of", "filter")):
        return "analytics"
    if any(kw in q for kw in ("what is", "what's", "value of", "show me", "lookup")):
        return "lookup"
    return "general"


# ---------------------------------------------------------------------------
# Verdict mapping
# ---------------------------------------------------------------------------


def _verdict_for(audit_status: str) -> tuple[str, str]:
    """Map audit_status → (label, tone) for the UI stat card."""
    if audit_status == "passed":
        return ("Verified", "emerald")
    if audit_status == "partial":
        return ("Partial", "amber")
    # "unknown" / anything else
    return ("Needs review", "red")


# ---------------------------------------------------------------------------
# Stage derivation
# ---------------------------------------------------------------------------


def _build_stages(
    tool_calls: list[ToolCall],
    audit_status: str,
) -> list[StageState]:
    """Derive per-stage state from the tool-call log + audit result.

    Every stage in STAGES gets an entry (so the UI can render a fixed-width
    stepper). Stages with no activity are `skipped`. UNDERSTAND is always
    `ok` — every answer involves parsing the question. VERIFY mirrors the
    audit result.
    """
    # Bucket tool calls by stage.
    by_stage: dict[str, list[ToolCall]] = {s["id"]: [] for s in STAGES}
    for tc in tool_calls:
        stage_id = TOOL_STAGE.get(tc.tool_name, STAGE_COMPUTE)
        by_stage[stage_id].append(tc)

    verify_status = "ok" if audit_status == "passed" else ("failed" if audit_status == "unknown" else "ok")

    states: list[StageState] = []
    for s in STAGES:
        sid = s["id"]
        calls = by_stage.get(sid, [])
        if sid == STAGE_UNDERSTAND:
            status = "ok"
        elif sid == STAGE_VERIFY:
            status = verify_status
        else:
            status = "ok" if calls else "skipped"
        states.append(
            StageState(
                id=sid,
                symbol=s["symbol"],
                label=s["label"],
                role=s["role"],
                status=status,
                tool_count=len(calls),
                total_ms=sum(tc.latency_ms for tc in calls),
            )
        )
    return states


# ---------------------------------------------------------------------------
# Tool-call summaries (readable one-liners)
# ---------------------------------------------------------------------------


def _preview(obj: Any, limit: int = 140) -> str:
    """Render a short, single-line preview of a tool arg/result dict."""
    if obj is None:
        return "—"
    if isinstance(obj, str):
        s = obj
    elif isinstance(obj, dict):
        parts = []
        for k, v in list(obj.items())[:5]:
            vs = v if isinstance(v, (str, int, float, bool)) else type(v).__name__
            parts.append(f"{k}={vs}")
        s = ", ".join(parts)
    elif isinstance(obj, list):
        s = f"[{len(obj)} items]"
    else:
        s = str(obj)
    if len(s) > limit:
        s = s[: limit - 1] + "…"
    return s


def _tool_call_summaries(tool_calls: list[ToolCall]) -> list[ToolCallSummary]:
    out: list[ToolCallSummary] = []
    for tc in tool_calls:
        out.append(
            ToolCallSummary(
                stage=TOOL_STAGE.get(tc.tool_name, STAGE_COMPUTE),
                tool_name=tc.tool_name,
                args_preview=_preview(tc.input),
                result_preview=_preview(tc.output),
                latency_ms=tc.latency_ms,
            )
        )
    return out


# ---------------------------------------------------------------------------
# Narrative generator (deterministic)
# ---------------------------------------------------------------------------
#
# Second-person voice ("You asked…", "Rosetta looked up…"), concise, one
# paragraph per active stage. Skipped stages are omitted; the final step is
# always a terse restatement of the answer's headline.


def _step_understand(
    question: str,
    intent: str,
    inherited_entity: bool,
    active_entity: Optional[str],
) -> NarrativeStep:
    intent_phrase = {
        "formula-trace": "a formula-explanation question",
        "lookup": "a direct value lookup",
        "analytics": "an analytical aggregation",
        "what-if": "a what-if / scenario question",
        "audit": "an audit / diagnostics question",
        "general": "a question about this workbook",
    }.get(intent, "a question about this workbook")
    body = f'You asked: "{question.strip()}". Rosetta read this as {intent_phrase}.'
    if inherited_entity and active_entity:
        body += f' Context from your previous turn was carried forward — the active entity is {active_entity}.'
    return NarrativeStep(title="Understanding your question", body=body)


def _step_locate(stage: StageState, tool_calls: list[ToolCall]) -> Optional[NarrativeStep]:
    if stage.status == "skipped":
        return None
    # Look for the most informative Locate call: prefer find_cells, then
    # resolve_named_range, then the first one.
    relevant = [tc for tc in tool_calls if TOOL_STAGE.get(tc.tool_name) == STAGE_LOCATE]
    if not relevant:
        return None
    preferred = next((tc for tc in relevant if tc.tool_name == "find_cells"), None)
    tc = preferred or relevant[0]

    body_parts: list[str] = []
    if tc.tool_name == "find_cells":
        keyword = tc.input.get("keyword") or tc.input.get("query") or "the term in your question"
        matches = tc.output.get("matches", []) if isinstance(tc.output, dict) else []
        if matches:
            top = matches[0]
            ref = top.get("ref") if isinstance(top, dict) else None
            label = top.get("label") if isinstance(top, dict) else None
            if ref and label:
                body_parts.append(
                    f"Rosetta searched the workbook for \"{keyword}\" and matched {len(matches)} candidate(s); the best fit was {ref} (\"{label}\")."
                )
            elif ref:
                body_parts.append(
                    f"Rosetta searched the workbook for \"{keyword}\" and matched {len(matches)} candidate(s); the best fit was {ref}."
                )
            else:
                body_parts.append(f"Rosetta searched the workbook for \"{keyword}\" and returned {len(matches)} candidate(s).")
        else:
            body_parts.append(f"Rosetta searched the workbook for \"{keyword}\".")
    elif tc.tool_name == "resolve_named_range":
        name = tc.input.get("name") or "the named range"
        resolved = tc.output.get("resolved") if isinstance(tc.output, dict) else None
        if resolved:
            body_parts.append(f"Rosetta resolved the named range `{name}` to {resolved}.")
        else:
            body_parts.append(f"Rosetta resolved the named range `{name}`.")
    elif tc.tool_name == "get_workbook_summary":
        body_parts.append("Rosetta oriented itself with a full workbook summary (sheets, modes, findings) before drilling in.")
    elif tc.tool_name == "list_named_ranges":
        body_parts.append("Rosetta listed the workbook's named ranges to find the right anchor for your question.")
    elif tc.tool_name == "list_sheets":
        body_parts.append("Rosetta listed the workbook's sheets to orient itself.")
    else:
        body_parts.append(f"Rosetta used `{tc.tool_name}` to locate the relevant region.")

    if stage.tool_count > 1:
        body_parts.append(f"In total {stage.tool_count} locator call(s) ran in {stage.total_ms} ms.")
    return NarrativeStep(title="Finding the right cells", body=" ".join(body_parts))


def _step_compute(stage: StageState, tool_calls: list[ToolCall]) -> Optional[NarrativeStep]:
    if stage.status == "skipped":
        return None
    relevant = [tc for tc in tool_calls if TOOL_STAGE.get(tc.tool_name, STAGE_COMPUTE) == STAGE_COMPUTE]
    if not relevant:
        return None

    # Prefer the richest call: backward_trace, then get_cell, then forward_impact.
    prio = ["backward_trace", "forward_impact", "get_cell", "explain_circular", "list_findings", "sql_query"]
    preferred = None
    for name in prio:
        preferred = next((tc for tc in relevant if tc.tool_name == name), None)
        if preferred:
            break
    tc = preferred or relevant[0]

    body_parts: list[str] = []
    if tc.tool_name == "backward_trace":
        ref = tc.input.get("ref") if isinstance(tc.input, dict) else None
        out = tc.output if isinstance(tc.output, dict) else {}
        trace = out.get("trace") or {}
        formula = (trace or {}).get("formula") if isinstance(trace, dict) else None
        children = (trace or {}).get("children") or [] if isinstance(trace, dict) else []
        if ref and formula:
            body_parts.append(f"Rosetta pulled the backward trace for {ref}. The formula is `={formula}`.")
        elif ref:
            body_parts.append(f"Rosetta pulled the backward trace for {ref}.")
        if children:
            body_parts.append(f"It has {len(children)} direct precedent(s).")
    elif tc.tool_name == "get_cell":
        ref = tc.input.get("ref") if isinstance(tc.input, dict) else None
        out = tc.output if isinstance(tc.output, dict) else {}
        val = out.get("value")
        formula = out.get("formula")
        if ref and formula:
            body_parts.append(f"Rosetta read {ref} — formula `={formula}`.")
        elif ref and val is not None:
            body_parts.append(f"Rosetta read {ref} — value {val}.")
        elif ref:
            body_parts.append(f"Rosetta read {ref}.")
    elif tc.tool_name == "forward_impact":
        ref = tc.input.get("ref") if isinstance(tc.input, dict) else None
        out = tc.output if isinstance(tc.output, dict) else {}
        impacted = out.get("impacted") or []
        if ref:
            body_parts.append(f"Rosetta computed the forward impact of {ref}: {len(impacted)} downstream cell(s) would be affected.")
        else:
            body_parts.append(f"Rosetta computed a forward-impact analysis ({len(impacted)} downstream cell(s)).")
    elif tc.tool_name == "explain_circular":
        body_parts.append("Rosetta examined the circular-reference chain, including any author comments and iterative-calc evidence.")
    elif tc.tool_name == "list_findings":
        out = tc.output if isinstance(tc.output, dict) else {}
        findings = out.get("findings") or []
        body_parts.append(f"Rosetta pulled the audit findings — {len(findings)} flagged item(s).")
    elif tc.tool_name in ("aggregate_column", "group_aggregate", "top_n", "filter_rows", "time_bucket_aggregate",
                          "describe", "correlate", "histogram"):
        body_parts.append(f"Rosetta ran `{tc.tool_name}` over the source rows to compute the answer.")
    elif tc.tool_name == "sql_query":
        body_parts.append("Rosetta ran a SQL query directly against the workbook tables.")
    else:
        body_parts.append(f"Rosetta invoked `{tc.tool_name}` to produce the result.")

    if stage.tool_count > 1:
        body_parts.append(f"In total {stage.tool_count} compute call(s) ran in {stage.total_ms} ms.")
    return NarrativeStep(title="How the answer was computed", body=" ".join(body_parts))


def _step_simulate(stage: StageState, tool_calls: list[ToolCall]) -> Optional[NarrativeStep]:
    if stage.status == "skipped":
        return None
    relevant = [tc for tc in tool_calls if TOOL_STAGE.get(tc.tool_name) == STAGE_SIMULATE]
    if not relevant:
        return None

    tc = relevant[0]
    body_parts: list[str] = []
    if tc.tool_name in ("what_if", "scenario_recalc"):
        overrides = tc.input.get("overrides") if isinstance(tc.input, dict) else None
        if isinstance(overrides, dict) and overrides:
            first_k, first_v = next(iter(overrides.items()))
            body_parts.append(
                f"Rosetta re-evaluated the workbook with `{first_k}` overridden to {first_v}"
                + (f" (+ {len(overrides) - 1} more)" if len(overrides) > 1 else "")
                + "."
            )
        else:
            body_parts.append(f"Rosetta ran a scenario recalculation via `{tc.tool_name}`.")
    elif tc.tool_name == "goal_seek":
        target = tc.input.get("target_ref") if isinstance(tc.input, dict) else None
        tv = tc.input.get("target_value") if isinstance(tc.input, dict) else None
        input_ref = tc.input.get("input_ref") if isinstance(tc.input, dict) else None
        if target and input_ref and tv is not None:
            body_parts.append(f"Rosetta ran goal-seek: what value of `{input_ref}` drives {target} to {tv}?")
        else:
            body_parts.append("Rosetta ran a goal-seek simulation.")
    elif tc.tool_name == "sensitivity":
        target = tc.input.get("target_ref") if isinstance(tc.input, dict) else None
        if target:
            body_parts.append(f"Rosetta ran a sensitivity analysis around {target} to rank the input drivers.")
        else:
            body_parts.append("Rosetta ran a sensitivity analysis.")
    elif tc.tool_name == "compare_scenarios":
        body_parts.append("Rosetta compared two scenarios side-by-side.")
    else:
        body_parts.append(f"Rosetta used `{tc.tool_name}` to simulate the what-if.")

    return NarrativeStep(title="Simulating the scenario", body=" ".join(body_parts))


def _step_verify(
    stage: StageState,
    audit_status: str,
    cells_referenced: int,
) -> NarrativeStep:
    if audit_status == "passed":
        if cells_referenced:
            body = (
                f"Before answering, Rosetta's citation auditor cross-checked every number in the response "
                f"against the workbook — {cells_referenced} cell reference(s) passed verification."
            )
        else:
            body = "Before answering, Rosetta's citation auditor verified every claim against the workbook."
    elif audit_status == "partial":
        body = (
            "The citation auditor could verify some of the answer but not all of it — the response was "
            "narrowed to only the facts Rosetta could defend."
        )
    else:
        body = (
            "The citation auditor could not verify this answer against the workbook. Rosetta prefers to "
            "say \"I don't know\" over guessing."
        )
    return NarrativeStep(title="Verifying the answer", body=body)


def _step_final(short_answer: Optional[str], detailed_answer: str) -> NarrativeStep:
    # Use the short answer if we have one; otherwise the first line of detail.
    text = (short_answer or detailed_answer or "").strip()
    if not text:
        text = "Rosetta has responded."
    # Clip to a reasonable single-paragraph length for the narrative.
    if len(text) > 280:
        text = text[:279].rstrip() + "…"
    return NarrativeStep(title="Final answer", body=text)


def _build_narrative(
    question: str,
    intent: str,
    inherited_entity: bool,
    active_entity: Optional[str],
    stages: list[StageState],
    tool_calls: list[ToolCall],
    audit_status: str,
    cells_referenced: int,
    short_answer: Optional[str],
    detailed_answer: str,
) -> list[NarrativeStep]:
    steps: list[NarrativeStep] = []
    stage_by_id = {s.id: s for s in stages}

    steps.append(_step_understand(question, intent, inherited_entity, active_entity))

    locate_step = _step_locate(stage_by_id[STAGE_LOCATE], tool_calls)
    if locate_step:
        steps.append(locate_step)

    compute_step = _step_compute(stage_by_id[STAGE_COMPUTE], tool_calls)
    if compute_step:
        steps.append(compute_step)

    simulate_step = _step_simulate(stage_by_id[STAGE_SIMULATE], tool_calls)
    if simulate_step:
        steps.append(simulate_step)

    steps.append(_step_verify(stage_by_id[STAGE_VERIFY], audit_status, cells_referenced))

    steps.append(_step_final(short_answer, detailed_answer))
    return steps


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def build_reasoning_trace(
    *,
    question: str,
    tool_calls: list[ToolCall],
    audit_status: str,
    latency_ms: int,
    cells_referenced: int,
    short_answer: Optional[str],
    detailed_answer: str,
    active_entity: Optional[str],
    inherited_entity: bool,
) -> ReasoningTrace:
    """Assemble the full ReasoningTrace returned to the UI.

    All inputs are already computed elsewhere; this function is pure
    translation + narrative generation. No side-effects, no LLM calls.
    """
    intent = classify_intent(question)
    stages = _build_stages(tool_calls, audit_status)
    verdict_label, verdict_tone = _verdict_for(audit_status)
    narrative = _build_narrative(
        question=question,
        intent=intent,
        inherited_entity=inherited_entity,
        active_entity=active_entity,
        stages=stages,
        tool_calls=tool_calls,
        audit_status=audit_status,
        cells_referenced=cells_referenced,
        short_answer=short_answer,
        detailed_answer=detailed_answer,
    )
    return ReasoningTrace(
        intent=intent,
        active_entity=active_entity,
        inherited_entity=inherited_entity,
        stages=stages,
        tool_calls=_tool_call_summaries(tool_calls),
        verdict=verdict_label,
        verdict_tone=verdict_tone,
        latency_ms=latency_ms,
        cells_referenced=cells_referenced,
        steps=len(tool_calls),
        narrative=narrative,
    )


# ---------------------------------------------------------------------------
# Short / detailed answer marker parsing
# ---------------------------------------------------------------------------
#
# The coordinator asks Claude to wrap its output in markers:
#
#     <SHORT>One-sentence headline for the bubble.</SHORT>
#     <DETAILED>
#     The full, verbose, citation-heavy answer as today.
#     </DETAILED>
#
# If the markers are missing (cached answer, model drift, etc.) we fall back
# to heuristics so the UI always has something to render. Never raise.


import re as _re

_SHORT_RE = _re.compile(r"<SHORT>\s*(.*?)\s*</SHORT>", _re.DOTALL | _re.IGNORECASE)
_DETAILED_RE = _re.compile(r"<DETAILED>\s*(.*?)\s*</DETAILED>", _re.DOTALL | _re.IGNORECASE)


def split_short_detailed(text: str) -> tuple[str, str]:
    """Return (short_answer, detailed_answer) from a coordinator output.

    Strategy:
      1. If both <SHORT>…</SHORT> and <DETAILED>…</DETAILED> are present,
         extract them directly.
      2. Otherwise, fall back:
         - short = the first sentence of `text`, capped at 180 chars.
         - detailed = the full `text`.
    """
    if not text:
        return ("", "")
    short_m = _SHORT_RE.search(text)
    detailed_m = _DETAILED_RE.search(text)
    if short_m and detailed_m:
        return (short_m.group(1).strip(), detailed_m.group(1).strip())
    if short_m and not detailed_m:
        short = short_m.group(1).strip()
        # strip the short tag out of the remaining text to use as detailed
        detailed = _SHORT_RE.sub("", text).strip() or short
        return (short, detailed)

    # No markers — derive a headline from the full text.
    detailed = text.strip()
    first_line = _first_sentence(detailed)
    if len(first_line) > 180:
        first_line = first_line[:179].rstrip() + "…"
    return (first_line, detailed)


def _first_sentence(text: str) -> str:
    """Best-effort first-sentence extraction. Strips leading bullets / markdown."""
    clean = text.strip()
    # Drop a leading markdown header or bullet prefix so the headline reads naturally.
    clean = _re.sub(r"^[#>\-*\s]+", "", clean)
    # End at the first sentence-terminator followed by space or newline.
    m = _re.search(r"[.!?](?:\s|$)", clean)
    if not m:
        # Fall back to first newline, then whole text.
        nl = clean.find("\n")
        return clean[:nl].strip() if nl > 0 else clean
    return clean[: m.end()].strip()


# ---------------------------------------------------------------------------
# Cell-ref extraction for the "cells referenced" KPI
# ---------------------------------------------------------------------------


_CELL_REF_RE = _re.compile(r"[A-Za-z_][\w &\-\.]*?!\$?[A-Z]{1,3}\$?\d+")


def count_cells_referenced(
    detailed_answer: str,
    tool_calls: list[ToolCall],
    evidence_refs: list[str],
) -> int:
    """Union of refs mentioned in the answer, touched by tools, or cited as evidence."""
    refs: set[str] = set()
    if detailed_answer:
        refs.update(m.group(0) for m in _CELL_REF_RE.finditer(detailed_answer))
    refs.update(evidence_refs or [])

    def _walk(obj: Any) -> None:
        if isinstance(obj, dict):
            for k, v in obj.items():
                if k == "ref" and isinstance(v, str) and "!" in v:
                    refs.add(v)
                _walk(v)
        elif isinstance(obj, list):
            for x in obj:
                _walk(x)

    for tc in tool_calls:
        _walk(tc.output)
    return len(refs)


# ---------------------------------------------------------------------------
# Note on the no-narrative fallback
# ---------------------------------------------------------------------------
#
# When the coordinator runs but produces no tool calls (e.g. a cache hit or
# the no-API-key fallback), `build_reasoning_trace` still returns a valid
# ReasoningTrace. Only UNDERSTAND + VERIFY will be marked `ok`; the others
# stay `skipped`. The narrative gracefully omits the missing stages. The UI
# handles an empty narrative by showing a neutral empty-state instead of a
# broken modal.
