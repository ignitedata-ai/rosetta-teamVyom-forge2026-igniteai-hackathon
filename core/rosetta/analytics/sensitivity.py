"""Sensitivity analysis + elasticity (Bucket E).

For a target cell, perturb each candidate input by ±delta and measure
how much the target moves. The ranked list feeds a tornado chart, which
is the classic visual for sensitivity analysis.

When `input_refs` is omitted, auto-discover candidates: every named range
whose current value is numeric. This is the common case for financial
models where the named ranges on an Assumptions sheet are exactly the
assumptions a sensitivity analysis should rank.
"""

from __future__ import annotations

from typing import Any

from ..evaluator import Evaluator
from ..models import WorkbookModel
from . import build_envelope, error

_DEFAULT_DELTA = 0.10  # ±10 % perturbation


def sensitivity(
    wb: WorkbookModel,
    target_ref: str,
    input_refs: list[str] | None = None,
    delta: float = _DEFAULT_DELTA,
    top: int = 20,
) -> dict:
    """Rank inputs by absolute impact on the target cell.

    For each input, apply `±delta` relative override and measure the
    resulting change in the target. Returns a tornado-ready structure:
    positive and negative deltas per input, sorted by max |delta|.
    """
    target_ref = _resolve_ref(wb, target_ref)
    if target_ref is None:
        return error("target_ref not found")

    # Baseline
    base_target = _evaluate(wb, target_ref)
    if base_target is None:
        return error(f"target {target_ref} did not evaluate to a number at baseline")

    # Auto-discover candidates if not provided
    candidates: list[tuple[str, str, float]] = []  # (label, ref, base_input)
    if input_refs:
        for raw in input_refs:
            ref = _resolve_ref(wb, raw)
            if ref is None:
                continue
            v = _get_numeric(wb, ref)
            if v is not None:
                candidates.append((raw, ref, v))
    else:
        for nr in wb.named_ranges:
            if not nr.resolved_refs or ":" in nr.resolved_refs[0]:
                continue
            ref = nr.resolved_refs[0]
            v = _get_numeric(wb, ref)
            if v is not None:
                candidates.append((nr.name, ref, v))

    if not candidates:
        return build_envelope(
            {"target_ref": target_ref, "baseline": base_target, "rows": []},
            warnings=["no numeric input candidates found — pass input_refs explicitly"],
        )

    rows: list[dict] = []
    for label, ref, base_input in candidates:
        if base_input == 0:
            # Use absolute delta around zero to avoid zero-multiplier collapse
            up_val, dn_val = base_input + delta, base_input - delta
        else:
            up_val, dn_val = base_input * (1 + delta), base_input * (1 - delta)
        up_target = _evaluate(wb, target_ref, overrides={ref: up_val})
        dn_target = _evaluate(wb, target_ref, overrides={ref: dn_val})
        delta_up = (up_target - base_target) if up_target is not None else None
        delta_dn = (dn_target - base_target) if dn_target is not None else None
        max_abs = max(
            abs(delta_up) if delta_up is not None else 0,
            abs(delta_dn) if delta_dn is not None else 0,
        )
        rows.append(
            {
                "input_label": label,
                "input_ref": ref,
                "baseline_input": base_input,
                "high_input": up_val,
                "high_target": up_target,
                "high_delta": delta_up,
                "low_input": dn_val,
                "low_target": dn_target,
                "low_delta": delta_dn,
                "max_abs_delta": max_abs,
            }
        )
    rows.sort(key=lambda r: -r["max_abs_delta"])
    rows = rows[:top]

    return build_envelope(
        {
            "target_ref": target_ref,
            "baseline": base_target,
            "delta_pct": delta * 100,
            "rows": rows,
        },
        evidence_range=None,
        refs=[r["input_ref"] for r in rows],
        chart_data={
            "type": "tornado",
            "labels": [r["input_label"] for r in rows],
            "high": [r["high_delta"] or 0 for r in rows],
            "low": [r["low_delta"] or 0 for r in rows],
            "baseline": base_target,
            "y_label": target_ref,
        },
    )


def elasticity(
    wb: WorkbookModel,
    target_ref: str,
    input_ref: str,
    delta: float = 0.01,
) -> dict:
    """Point elasticity: %Δ target / %Δ input, at the current operating point."""
    target_ref = _resolve_ref(wb, target_ref)
    input_ref = _resolve_ref(wb, input_ref)
    if target_ref is None or input_ref is None:
        return error("target_ref or input_ref not found")
    base_input = _get_numeric(wb, input_ref)
    base_target = _evaluate(wb, target_ref)
    if base_input is None or base_target is None or base_input == 0 or base_target == 0:
        return build_envelope(
            {"elasticity": None, "reason": "baseline input or target is zero / non-numeric"},
            warnings=["elasticity undefined at zero baseline"],
        )
    new_input = base_input * (1 + delta)
    new_target = _evaluate(wb, target_ref, overrides={input_ref: new_input})
    if new_target is None:
        return error("new target value was non-numeric")
    pct_target = (new_target - base_target) / base_target
    pct_input = delta
    e = pct_target / pct_input if pct_input else 0
    return build_envelope(
        {
            "target_ref": target_ref,
            "input_ref": input_ref,
            "baseline_input": base_input,
            "baseline_target": base_target,
            "delta": delta,
            "elasticity": e,
            "direction": "positive" if e > 0 else ("negative" if e < 0 else "zero"),
            "interpretation": _describe_elasticity(e),
        },
        refs=[input_ref, target_ref],
    )


# --- helpers -------------------------------------------------------------


def _resolve_ref(wb: WorkbookModel, raw: str) -> str | None:
    ref = raw.replace("$", "").strip()
    if ref in wb.cells:
        return ref
    nr = next((n for n in wb.named_ranges if n.name.lower() == raw.lower()), None)
    if nr and nr.resolved_refs and ":" not in nr.resolved_refs[0]:
        return nr.resolved_refs[0]
    return None


def _get_numeric(wb: WorkbookModel, ref: str) -> float | None:
    cell = wb.cells.get(ref)
    if cell is None:
        return None
    v = cell.value
    if v is None and cell.formula:
        try:
            v = Evaluator(wb).value_of(ref)
        except Exception:
            return None
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _evaluate(wb: WorkbookModel, ref: str, overrides: dict[str, float] | None = None) -> float | None:
    try:
        v = Evaluator(wb, overrides=overrides or {}).value_of(ref)
    except Exception:
        return None
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _describe_elasticity(e: float) -> str:
    a = abs(e)
    if a >= 1.5:
        return "highly elastic — large output movement per unit input change"
    if a >= 0.5:
        return "moderately elastic"
    if a >= 0.1:
        return "weakly elastic"
    return "near-inelastic — target barely responds"


# --- tool schemas --------------------------------------------------------

TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "name": "sensitivity",
        "description": (
            "Rank candidate inputs by their impact on a target cell. For "
            "each input, perturbs by ±delta (default 10%) and records the "
            "resulting change in the target. Returns a tornado-chart payload. "
            "When input_refs is omitted, every named range with a numeric "
            "current value is used as a candidate — ideal for ranking "
            "Assumption-sheet inputs. Example: 'which input most affects "
            "Adjusted EBITDA?' — target_ref='P&L Summary!G32'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "target_ref": {"type": "string"},
                "input_refs": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Cells or named ranges to vary. Omit for auto-discovery.",
                },
                "delta": {"type": "number", "default": _DEFAULT_DELTA, "description": "Relative perturbation (±)."},
                "top": {"type": "integer", "default": 20},
            },
            "required": ["target_ref"],
        },
    },
    {
        "name": "elasticity",
        "description": (
            "Compute point elasticity (%Δtarget / %Δinput) between one "
            "input and one target, at the current operating point."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "target_ref": {"type": "string"},
                "input_ref": {"type": "string"},
                "delta": {"type": "number", "default": 0.01},
            },
            "required": ["target_ref", "input_ref"],
        },
    },
]
