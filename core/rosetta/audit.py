"""Diagnostic / audit engine — finds issues in the parsed workbook."""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from .models import AuditFinding, WorkbookModel


def _is_date(v: Any) -> bool:
    return hasattr(v, "year") and hasattr(v, "month") and hasattr(v, "day")


def audit_workbook(wb: WorkbookModel, source_path: str | Path | None = None) -> list[AuditFinding]:
    """Run every structural audit detector over the parsed workbook.

    `source_path`, when provided, unlocks detectors that need the raw `.xlsx`
    file (currently: conditional-formatting extraction, which requires
    openpyxl to re-open the file since conditional rules aren't mirrored on
    the in-memory WorkbookModel). Existing callers that don't pass a path
    still get every other detector.

    Flat-table sheets (0 formulas, ≥20 rows) additionally get data-quality
    scans — missing-value and IQR-outlier findings — from the analytics
    subsystem. These surface via list_findings alongside formula-centric
    findings so the coordinator can answer "anything wrong with this data?"
    questions on any sheet shape.
    """
    findings: list[AuditFinding] = []
    findings.extend(_stale_assumptions(wb))
    findings.extend(_hidden_deps(wb))
    findings.extend(_volatile_formulas(wb))
    findings.extend(_hardcoded_anomalies(wb))
    findings.extend(_circular_references(wb))
    findings.extend(_broken_refs(wb))
    if source_path:
        findings.extend(_conditional_formatting_rules(source_path))
    # Analytics-side findings for flat-table sheets
    try:
        from .analytics.data_quality import scan_flat_table

        findings.extend(scan_flat_table(wb))
    except Exception:
        # Analytics scan is enrichment — never break the main audit
        pass
    return findings


def _stale_assumptions(wb: WorkbookModel) -> list[AuditFinding]:
    """Look for rows that look like assumption entries with dates older than 12 months."""
    findings: list[AuditFinding] = []
    cutoff = datetime.utcnow() - timedelta(days=365)
    # Heuristic: for each sheet whose name contains 'assumption', scan rows for date columns
    for sheet in wb.sheets:
        name_lower = sheet.name.lower()
        looks_like_assumptions = "assumption" in name_lower or "settings" in name_lower
        if not looks_like_assumptions:
            continue
        for r in range(1, sheet.max_row + 1):
            label_ref = f"{sheet.name}!A{r}"
            label = wb.cells.get(label_ref)
            if not label or not isinstance(label.value, str):
                continue
            # Scan columns for a date value
            for c_letter in ["B", "C", "D", "E"]:
                ref = f"{sheet.name}!{c_letter}{r}"
                c = wb.cells.get(ref)
                if c and _is_date(c.value):
                    try:
                        dt = datetime(c.value.year, c.value.month, c.value.day)
                    except Exception:
                        continue
                    if dt < cutoff:
                        findings.append(
                            AuditFinding(
                                severity="warning",
                                category="stale_assumption",
                                location=label_ref,
                                message=f"Assumption '{label.value}' last updated {dt.date().isoformat()} — more than 12 months old.",
                                detail={"assumption": label.value, "date": dt.date().isoformat()},
                                confidence=0.9,
                            )
                        )
                    break
    return findings


def _hidden_deps(wb: WorkbookModel) -> list[AuditFinding]:
    """Flag formulas that reference hidden sheets or hidden rows."""
    findings: list[AuditFinding] = []
    hidden_sheets = {s.name for s in wb.sheets if s.hidden}
    hidden_rows_by_sheet: dict[str, set[int]] = {s.name: set(s.hidden_rows) for s in wb.sheets}
    for ref, cell in wb.cells.items():
        if not cell.formula:
            continue
        for d in cell.depends_on:
            if "!" not in d:
                continue
            ds, dc = d.split("!", 1)
            if ds in hidden_sheets:
                findings.append(
                    AuditFinding(
                        severity="warning",
                        category="hidden_dependency",
                        location=ref,
                        message=f"{ref} depends on {d} which is on hidden sheet '{ds}'.",
                        confidence=0.95,
                    )
                )
                continue
            # hidden row
            if ":" in dc:
                continue
            row_m = "".join(ch for ch in dc if ch.isdigit())
            if row_m and int(row_m) in hidden_rows_by_sheet.get(ds, set()):
                findings.append(
                    AuditFinding(
                        severity="info",
                        category="hidden_dependency",
                        location=ref,
                        message=f"{ref} depends on {d} which is in a hidden row.",
                        confidence=0.85,
                    )
                )
    return findings


# Volatile functions split by fragility severity.
#   FRAGILE: behaviour is tied to sheet/range names — can silently break.
#   UNSTABLE: deliberate recalc-on-open functions; usually intentional but
#   worth flagging so they don't surprise downstream consumers.
_FRAGILE_VOLATILE = ("INDIRECT", "OFFSET")
_UNSTABLE_VOLATILE = ("NOW", "TODAY", "RAND", "RANDBETWEEN", "CELL", "INFO")

_VOLATILE_FUNC_RE = re.compile(r"\b([A-Z]+)\s*\(")


def _detect_volatile_funcs(formula: str) -> list[str]:
    if not formula:
        return []
    out: list[str] = []
    for m in _VOLATILE_FUNC_RE.finditer(formula.upper()):
        fn = m.group(1)
        if fn in _FRAGILE_VOLATILE or fn in _UNSTABLE_VOLATILE:
            out.append(fn)
    return out


def _volatile_formulas(wb: WorkbookModel) -> list[AuditFinding]:
    """Emit a finding per volatile cell. Severity is split:
      - INDIRECT / OFFSET → warning (sheet-rename fragility, range drift)
      - NOW / TODAY / RAND / RANDBETWEEN → info (recalc-on-open, usually intentional)
    """
    out: list[AuditFinding] = []
    for ref, cell in wb.cells.items():
        if not cell.is_volatile or not cell.formula:
            continue
        funcs = _detect_volatile_funcs(cell.formula)
        if not funcs:
            # Parser flagged it volatile but we couldn't find the function in
            # the raw formula — fall back to a generic info finding.
            out.append(
                AuditFinding(
                    severity="info",
                    category="volatile",
                    location=ref,
                    message=f"{ref} uses a volatile function. Formula: ={cell.formula}",
                    confidence=0.8,
                )
            )
            continue
        fragile = [f for f in funcs if f in _FRAGILE_VOLATILE]
        unstable = [f for f in funcs if f in _UNSTABLE_VOLATILE]
        if fragile:
            primary = fragile[0]
            note = _fragility_note(primary)
            out.append(
                AuditFinding(
                    severity="warning",
                    category="volatile",
                    location=ref,
                    message=f"{ref} uses {primary} — fragile. {note} Formula: ={cell.formula}",
                    detail={"functions": funcs, "fragility": note, "primary": primary},
                    confidence=0.95,
                )
            )
        else:
            primary = unstable[0]
            out.append(
                AuditFinding(
                    severity="info",
                    category="volatile",
                    location=ref,
                    message=(
                        f"{ref} uses {primary} — recalculates on every workbook "
                        f"open. Usually intentional. Formula: ={cell.formula}"
                    ),
                    detail={"functions": funcs, "primary": primary},
                    confidence=0.95,
                )
            )
    return out


def _fragility_note(func: str) -> str:
    if func == "INDIRECT":
        return (
            "INDIRECT resolves a reference from a string. If a sheet or named "
            "range it points to is renamed, the formula returns #REF!."
        )
    if func == "OFFSET":
        return (
            "OFFSET's range shifts whenever the anchor row/column changes, "
            "which can cause silent off-by-one errors if rows are inserted."
        )
    return "Value can change between recalculations without any input changing."


def _hardcoded_anomalies(wb: WorkbookModel) -> list[AuditFinding]:
    """Find rows where most neighbors have formulas but this cell is hardcoded."""
    findings: list[AuditFinding] = []
    # Group cells by (sheet, column)
    col_cells: dict[tuple[str, str], list[int]] = defaultdict(list)
    for ref, cell in wb.cells.items():
        col = "".join(ch for ch in cell.coord if ch.isalpha())
        row = int("".join(ch for ch in cell.coord if ch.isdigit()))
        col_cells[(cell.sheet, col)].append(row)

    for (sheet, col), rows in col_cells.items():
        rows.sort()
        if len(rows) < 5:
            continue
        formula_rows = []
        hard_rows = []
        for r in rows:
            cell = wb.cells.get(f"{sheet}!{col}{r}")
            if not cell:
                continue
            if cell.formula:
                formula_rows.append(r)
            elif isinstance(cell.value, (int, float)) and not isinstance(cell.value, bool):
                hard_rows.append(r)
        if len(formula_rows) >= 5 and len(hard_rows) > 0 and len(hard_rows) <= len(formula_rows) // 3:
            # Only flag hardcoded rows that are interior (between formula rows)
            f_set = set(formula_rows)
            for hr in hard_rows:
                above = any(fr < hr for fr in f_set)
                below = any(fr > hr for fr in f_set)
                if above and below:
                    findings.append(
                        AuditFinding(
                            severity="warning",
                            category="hardcoded_anomaly",
                            location=f"{sheet}!{col}{hr}",
                            message=f"{sheet}!{col}{hr} is a hardcoded number where {len(formula_rows)} neighboring rows use formulas. Possible manual override.",
                            detail={
                                "value": wb.cells[f"{sheet}!{col}{hr}"].value,
                                "neighboring_formula_sample": wb.cells[f"{sheet}!{col}{formula_rows[0]}"].formula,
                            },
                            confidence=0.75,
                        )
                    )
    return findings


def _circular_references(wb: WorkbookModel) -> list[AuditFinding]:
    out: list[AuditFinding] = []
    for cr in wb.graph_summary.circular_references:
        out.append(
            AuditFinding(
                severity="info" if cr.intentional else "error",
                category="circular",
                location=cr.chain[0] if cr.chain else None,
                message=f"Circular reference detected: {' → '.join(cr.chain)}. {cr.note or ''}",
                detail={"chain": cr.chain, "intentional": cr.intentional},
                confidence=0.95,
            )
        )
    return out


def _broken_refs(wb: WorkbookModel) -> list[AuditFinding]:
    out: list[AuditFinding] = []
    for ref, cell in wb.cells.items():
        if isinstance(cell.value, str) and cell.value.startswith("#REF"):
            out.append(
                AuditFinding(
                    severity="error",
                    category="broken_ref",
                    location=ref,
                    message=f"{ref} contains a broken reference error: {cell.value}.",
                    confidence=1.0,
                )
            )
    return out


def _conditional_formatting_rules(source_path: str | Path) -> list[AuditFinding]:
    """Extract `cellIs` / `expression` conditional formatting rules.

    Each rule encodes a business rule ("turn red when variance > 10%") that
    isn't captured anywhere else in the workbook. We emit one finding per
    rule; the coordinator can surface these when asked about highlighting
    or about structural audits.

    Skips purely aesthetic rules (color scales, data bars, icon sets).
    """
    out: list[AuditFinding] = []
    try:
        import openpyxl

        wb_f = openpyxl.load_workbook(source_path, data_only=False)
    except Exception:
        return out

    for ws in wb_f.worksheets:
        try:
            cf = ws.conditional_formatting
        except Exception:
            continue
        for cf_range, rules in cf._cf_rules.items() if hasattr(cf, "_cf_rules") else []:
            rng_str = _cf_range_to_str(cf_range)
            for rule in rules:
                rtype = getattr(rule, "type", None)
                if rtype not in ("cellIs", "expression"):
                    # Skip colorScale / dataBar / iconSet — pure aesthetics
                    continue
                op = getattr(rule, "operator", None)
                formulas = list(getattr(rule, "formula", []) or [])
                format_hint = _describe_cf_format(rule)
                message = _describe_cf_rule(rtype, op, formulas, format_hint, ws.title, rng_str)
                out.append(
                    AuditFinding(
                        severity="info",
                        category="conditional_rule",
                        location=f"{ws.title}!{rng_str}",
                        message=message,
                        detail={
                            "sheet": ws.title,
                            "range": rng_str,
                            "rule_type": rtype,
                            "operator": op,
                            "formulas": formulas,
                            "format": format_hint,
                        },
                        confidence=0.9,
                    )
                )
    return out


def _cf_range_to_str(cf_range) -> str:
    """openpyxl's conditional_formatting keys are MultiCellRange objects; str
    gives a space-separated list of ranges. For display we keep it compact.
    """
    try:
        s = str(cf_range).strip()
        return s or "?"
    except Exception:
        return "?"


def _describe_cf_format(rule) -> str:
    """Best-effort short summary of the rule's visual effect (fill color)."""
    try:
        dxf = rule.dxf
        if dxf is None:
            return ""
        fill = getattr(dxf, "fill", None)
        if fill is not None:
            fg = getattr(getattr(fill, "fgColor", None), "rgb", None)
            if fg:
                return f"fill {fg}"
        font = getattr(dxf, "font", None)
        if font is not None:
            color = getattr(getattr(font, "color", None), "rgb", None)
            if color:
                return f"font {color}"
    except Exception:
        pass
    return ""


def _describe_cf_rule(
    rtype: str,
    op: str | None,
    formulas: list[str],
    format_hint: str,
    sheet: str,
    rng: str,
) -> str:
    fmt_bit = f" → {format_hint}" if format_hint else ""
    if rtype == "cellIs":
        f_repr = ", ".join(formulas) or "?"
        return f"On {sheet}!{rng}: highlight when value {op or '?'} {f_repr}{fmt_bit}."
    # expression
    expr = formulas[0] if formulas else "?"
    return f"On {sheet}!{rng}: highlight when formula `{expr}` is true{fmt_bit}."
