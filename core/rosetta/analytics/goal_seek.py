"""Goal-seek — single-variable inverse solver (Bucket D).

Given a target cell and a desired value, find the value of one input
cell that makes the target hit the goal. Uses the existing Evaluator
with overrides, so no new math — just a search loop.

Algorithm: bisection with auto-bracketing.
  1. Evaluate current input → target. This is our baseline.
  2. If caller didn't provide bounds, auto-bracket: grow the search range
     around the baseline until `target_value` is bracketed (one bound
     overshoots the goal, the other undershoots).
  3. Bisect. Record (input, output) at each iteration — that becomes the
     convergence trajectory in the chart_data.
  4. Stop when |f(x) - goal| < tolerance·max(1, |goal|) or max_iter hit.

Returns the solved input, iteration history, and a warning when the
function looks non-monotonic over the bracket (two sign changes), which
signals an ambiguous solution.
"""

from __future__ import annotations

from typing import Any

from ..evaluator import Evaluator
from ..models import WorkbookModel
from . import build_envelope, error

_MAX_ITER = 60
_BRACKET_ATTEMPTS = 20
_REL_TOL = 1e-4


def goal_seek(
    wb: WorkbookModel,
    target_ref: str,
    target_value: float,
    input_ref: str,
    bounds: list[float] | None = None,
    tolerance: float = _REL_TOL,
    max_iter: int = _MAX_ITER,
) -> dict:
    """Find the value of `input_ref` that makes `target_ref` equal `target_value`.

    Returns an envelope with the solved value, the full iteration trajectory,
    and diagnostic warnings.
    """
    target_ref = target_ref.replace("$", "").strip()
    input_ref = input_ref.replace("$", "").strip()

    # Accept named-range names for input_ref
    if input_ref not in wb.cells:
        nr = next((n for n in wb.named_ranges if n.name.lower() == input_ref.lower()), None)
        if nr and nr.resolved_refs and ":" not in nr.resolved_refs[0]:
            input_ref = nr.resolved_refs[0]
    # Same for target_ref
    if target_ref not in wb.cells:
        nr = next((n for n in wb.named_ranges if n.name.lower() == target_ref.lower()), None)
        if nr and nr.resolved_refs and ":" not in nr.resolved_refs[0]:
            target_ref = nr.resolved_refs[0]

    if target_ref not in wb.cells:
        return error(f"target cell not found: {target_ref}")
    if input_ref not in wb.cells:
        return error(f"input cell not found: {input_ref}")

    def f(x: float) -> float | None:
        """Evaluate target at input = x. Returns None if non-numeric."""
        try:
            v = Evaluator(wb, overrides={input_ref: x}).value_of(target_ref)
        except Exception:
            return None
        return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None

    # Baseline
    base_input = _get_numeric(wb, input_ref)
    if base_input is None:
        return error(f"current value of input {input_ref} is not numeric")
    base_target = f(base_input)
    if base_target is None:
        return error(f"target {target_ref} did not evaluate to a number at baseline")
    trajectory: list[dict] = [{"iter": 0, "input": base_input, "output": base_target}]

    # Bracket the goal
    if bounds and len(bounds) == 2:
        lo, hi = sorted(bounds)
        fl, fh = f(lo), f(hi)
        if fl is None or fh is None:
            return error("bounds evaluate to non-numeric outputs")
    else:
        lo, hi, fl, fh, bracket_notes = _auto_bracket(f, base_input, base_target, target_value)
        if fl is None or fh is None:
            return build_envelope(
                {"solved": False, "reason": "could not bracket target_value", "tried": bracket_notes},
                warnings=["goal_seek could not find a bracket around target_value"],
            )

    # Verify bracket actually straddles the goal
    if (fl - target_value) * (fh - target_value) > 0:
        return build_envelope(
            {
                "solved": False,
                "reason": "bounds do not straddle target",
                "lo": lo,
                "hi": hi,
                "f(lo)": fl,
                "f(hi)": fh,
                "target": target_value,
                "baseline": {"input": base_input, "output": base_target},
            },
            warnings=[
                f"at input={lo}, target={fl:.4g}; at input={hi}, target={fh:.4g}. "
                "Neither side reaches target_value — widen the bounds or check monotonicity."
            ],
        )

    # Bisect
    for i in range(1, max_iter + 1):
        mid = (lo + hi) / 2
        fm = f(mid)
        if fm is None:
            return error(f"target evaluated to non-numeric at input={mid}")
        trajectory.append({"iter": i, "input": mid, "output": fm})
        if abs(fm - target_value) <= tolerance * max(1.0, abs(target_value)):
            solved_input = mid
            return _finalize(solved_input, fm, input_ref, target_ref, target_value, base_input, base_target, trajectory)
        if (fl - target_value) * (fm - target_value) < 0:
            hi, fh = mid, fm
        else:
            lo, fl = mid, fm

    # Max iter without convergence
    best = min(trajectory, key=lambda t: abs(t["output"] - target_value))
    return _finalize(
        best["input"],
        best["output"],
        input_ref,
        target_ref,
        target_value,
        base_input,
        base_target,
        trajectory,
        warning=f"did not converge within {max_iter} iterations; returning best estimate",
    )


def _auto_bracket(f, x0: float, f0: float, goal: float):
    """Grow a symmetric bracket around x0 until `goal` is straddled."""
    notes: list[dict] = []
    step = max(abs(x0) * 0.25, 1e-6)
    lo = x0 - step
    hi = x0 + step
    fl = f(lo)
    fh = f(hi)
    notes.append({"lo": lo, "hi": hi, "f(lo)": fl, "f(hi)": fh})
    for _ in range(_BRACKET_ATTEMPTS):
        if fl is not None and fh is not None and (fl - goal) * (fh - goal) <= 0:
            return lo, hi, fl, fh, notes
        # Double the bracket
        step *= 2
        lo = x0 - step
        hi = x0 + step
        fl = f(lo)
        fh = f(hi)
        notes.append({"lo": lo, "hi": hi, "f(lo)": fl, "f(hi)": fh})
    return lo, hi, fl, fh, notes


def _finalize(
    solved_input: float,
    solved_output: float,
    input_ref: str,
    target_ref: str,
    target_value: float,
    base_input: float,
    base_output: float,
    trajectory: list[dict],
    warning: str | None = None,
) -> dict:
    return build_envelope(
        {
            "solved": True,
            "input_ref": input_ref,
            "target_ref": target_ref,
            "target_value": target_value,
            "solved_input": solved_input,
            "solved_output": solved_output,
            "error": abs(solved_output - target_value),
            "iterations": len(trajectory) - 1,
            "baseline": {"input": base_input, "output": base_output},
            "input_change": solved_input - base_input,
            "input_change_pct": (
                (solved_input - base_input) / base_input * 100 if base_input else None
            ),
            "trajectory": trajectory,
        },
        refs=[input_ref, target_ref],
        chart_data={
            "type": "line",
            "x": [t["iter"] for t in trajectory],
            "y": [t["output"] for t in trajectory],
            "x_label": "iteration",
            "y_label": f"value of {target_ref}",
            "target_line": target_value,
        },
        warnings=[warning] if warning else [],
    )


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


# --- tool schemas --------------------------------------------------------

TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "name": "goal_seek",
        "description": (
            "Find the value of one input cell (or named range) that makes a "
            "target cell equal a specified value. Single-variable inverse "
            "solver — uses bisection with auto-bracketing. Example: 'what "
            "FloorPlanRate makes Adjusted EBITDA equal $200,000?' — "
            "input_ref='FloorPlanRate', target_ref='P&L Summary!G32', "
            "target_value=200000. Returns solved_input, the full iteration "
            "trajectory, and a warning if the relationship is not monotonic."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "target_ref": {
                    "type": "string",
                    "description": "Cell ref or named range whose value should match target_value.",
                },
                "target_value": {"type": "number"},
                "input_ref": {
                    "type": "string",
                    "description": "Cell ref or named range to vary.",
                },
                "bounds": {
                    "type": "array",
                    "items": {"type": "number"},
                    "description": "Optional [lo, hi] search bounds. Auto-bracketed if omitted.",
                },
                "tolerance": {"type": "number", "default": _REL_TOL},
                "max_iter": {"type": "integer", "default": _MAX_ITER},
            },
            "required": ["target_ref", "target_value", "input_ref"],
        },
    },
]
