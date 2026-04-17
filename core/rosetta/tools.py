"""Claude tool-calling interface over the parsed WorkbookModel.

Every tool is a pure function that reads from the parsed workbook. The LLM
calls these tools to ground its answer — it never invents formulas or refs.
"""

from __future__ import annotations

import re
from typing import Any

from .evaluator import Evaluator
from .graph import backward_trace, forward_impacted, forward_impacted_for_named_range
from .models import CellModel, TraceNode, WorkbookModel

# Analytics toolset — each module contributes TOOL_SCHEMAS + implementation fns.
# Merged into TOOLS / execute_tool below.
from .analytics import aggregators as _aggregators
from .analytics import data_quality as _data_quality
from .analytics import filters as _filters
from .analytics import goal_seek as _goal_seek
from .analytics import sensitivity as _sensitivity
from .analytics import sql as _sql
from .analytics import stats as _stats
from .analytics import time_series as _time_series

_COORD_RE = re.compile(r"^([A-Z]+)(\d+)$")


def _coord_to_rc(coord: str) -> tuple[int, int] | None:
    """Convert e.g. 'B12' → (12, 2). Returns None for malformed coords."""
    m = _COORD_RE.match(coord)
    if not m:
        return None
    letters, row = m.group(1), int(m.group(2))
    col = 0
    for ch in letters:
        col = col * 26 + (ord(ch) - ord("A") + 1)
    return row, col


def _resolved_value(cell: CellModel, ev: Evaluator | None) -> Any:
    """Return the cell's cached value, or compute it via the evaluator if the
    cached value is missing.

    Many workbooks (especially ones generated programmatically and never
    opened in Excel) have no cached values stored — every formula cell reads
    as None via openpyxl's data_only mode. Without this helper the LLM would
    either omit numbers (degraded answers) or invent them (auditor blocks).
    """
    v = cell.value
    if v is not None or not cell.formula or ev is None:
        return v
    try:
        return ev.value_of(cell.ref)
    except Exception:
        return None


def _fill_trace_values(node: TraceNode, ev: Evaluator) -> None:
    """Recursively populate `value` on TraceNode-s where the cached value is
    None but a formula exists. Reuses one Evaluator so memoization amortizes
    the cost across the whole tree."""
    if node.value is None and node.formula and node.ref:
        try:
            node.value = ev.value_of(node.ref)
        except Exception:
            pass
    for child in node.children:
        _fill_trace_values(child, ev)

TOOLS: list[dict[str, Any]] = [
    {
        "name": "list_sheets",
        "description": "List every sheet in the workbook with row/column counts, formula counts, hidden status, and structural regions. Call this first to orient yourself.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "list_named_ranges",
        "description": "List every named range (workbook- or sheet-scoped) with its resolved cell reference and current value. Named ranges carry business meaning (e.g. FloorPlanRate).",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "get_cell",
        "description": "Get the value, formula, dependencies, and semantic label of a specific cell. Use canonical form 'Sheet!A1' (no dollar signs).",
        "input_schema": {
            "type": "object",
            "properties": {"ref": {"type": "string", "description": "Canonical cell ref like 'P&L Summary!G32'"}},
            "required": ["ref"],
        },
    },
    {
        "name": "find_cells",
        "description": "Search for cells by semantic label keyword or canonical ref. 3-tier lookup: 'exact' (canonical ref or named range name), 'keyword' (substring match on labels), 'semantic' (embedding similarity — only available if v2 is deployed; otherwise returns empty). 'auto' tries exact → keyword → semantic in order.",
        "input_schema": {
            "type": "object",
            "properties": {
                "keyword": {
                    "type": "string",
                    "description": "The search query (e.g. 'EBITDA', 'P&L Summary!G32', 'floor plan rate').",
                },
                "has_formula": {
                    "type": "boolean",
                    "description": "If true, only return cells that have a formula.",
                    "default": False,
                },
                "tier": {
                    "type": "string",
                    "description": "One of: 'auto' (default), 'exact', 'keyword', 'semantic'.",
                    "default": "auto",
                },
            },
            "required": ["keyword"],
        },
    },
    {
        "name": "backward_trace",
        "description": "Return the full backward dependency tree for a cell — everything that feeds into it, recursively. Use this to answer 'how is X calculated?' questions.",
        "input_schema": {
            "type": "object",
            "properties": {
                "ref": {"type": "string", "description": "Canonical cell ref like 'P&L Summary!G32'"},
                "max_depth": {"type": "integer", "description": "How deep to traverse. Default 6.", "default": 6},
            },
            "required": ["ref"],
        },
    },
    {
        "name": "forward_impact",
        "description": "Return every cell downstream of the given cell (what would change if this cell changed). Use for dependency/impact questions.",
        "input_schema": {
            "type": "object",
            "properties": {
                "ref": {"type": "string", "description": "Canonical cell ref."},
                "max_results": {"type": "integer", "default": 100},
            },
            "required": ["ref"],
        },
    },
    {
        "name": "resolve_named_range",
        "description": "Look up a single named range by name. Returns the target ref, current value, and whether it's dynamic (OFFSET/INDIRECT).",
        "input_schema": {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        },
    },
    {
        "name": "list_findings",
        "description": "Return audit findings: stale assumptions, hardcoded anomalies, circular references, volatile formulas, hidden dependencies, broken refs. Optionally filter by category.",
        "input_schema": {
            "type": "object",
            "properties": {
                "category": {
                    "type": "string",
                    "description": "Optional filter: stale_assumption | hardcoded_anomaly | circular | volatile | hidden_dependency | broken_ref | inconsistency",
                }
            },
            "required": [],
        },
    },
    {
        "name": "what_if",
        "description": "Recompute the workbook with a single input changed. Pass either a named range name OR a cell ref as 'target'. Returns the list of cells whose value changed and by how much.",
        "input_schema": {
            "type": "object",
            "properties": {
                "target": {
                    "type": "string",
                    "description": "Named range name (e.g. 'FloorPlanRate') or cell ref (e.g. 'Assumptions!B2').",
                },
                "new_value": {"type": "number"},
                "max_results": {"type": "integer", "default": 30},
            },
            "required": ["target", "new_value"],
        },
    },
    {
        "name": "get_workbook_summary",
        "description": "Return a high-level summary of the workbook: sheet names, named range count, circular refs, audit finding counts. Call this once at the start of a new question to orient yourself if you haven't already.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "list_pivot_tables",
        "description": (
            "List every pivot table in the workbook with its host sheet, "
            "location, source data range, and field count. Use first when "
            "asked about a pivot, then call get_pivot_table for the details."
        ),
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "get_pivot_table",
        "description": (
            "Return the full layout of one pivot table: all row/column/value/filter "
            "fields, value aggregations (sum/average/count), calculated-field "
            "formulas, source data range, and refresh status. Use for "
            "'what is this pivot showing?' / 'how is the pivot calculated?' questions."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "sheet": {"type": "string", "description": "Sheet name the pivot is on."},
                "index": {"type": "integer", "description": "Zero-based index among pivots on that sheet. Default 0.", "default": 0},
            },
            "required": ["sheet"],
        },
    },
    {
        "name": "join_on_key",
        "description": (
            "Inner-join two sheets on a shared key. Use for questions that need "
            "to combine row-level data across sheets — e.g., 'What are the F&I "
            "products sold for Deal #1047?' (joins New Vehicle on Deal# with "
            "F&I Detail on Deal#). Keys can be specified by column letter ('A') "
            "or header label ('Deal#'). Selected columns can likewise be letters "
            "or labels. Returns formula-resolved values, not raw strings."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "sheet_a": {"type": "string"},
                "key_column_a": {"type": "string", "description": "Column letter or header label on sheet_a."},
                "sheet_b": {"type": "string"},
                "key_column_b": {"type": "string", "description": "Column letter or header label on sheet_b."},
                "select_a": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Columns to return from sheet_a (letters or labels). Omit for all.",
                },
                "select_b": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Columns to return from sheet_b. Omit for all.",
                },
                "filter_key": {
                    "type": "string",
                    "description": "If provided, only return rows whose key equals this value.",
                },
                "max_rows": {"type": "integer", "default": 50},
            },
            "required": ["sheet_a", "key_column_a", "sheet_b", "key_column_b"],
        },
    },
    {
        "name": "compare_regions",
        "description": (
            "Structurally compare two ranges of cells. Returns: overall "
            "formula-shape match percentage, functions that appear only on "
            "side A or only on side B, named ranges unique to each side, and "
            "a list of cell-level shape-mismatches (hardcoded vs formula, "
            "different function call sequence). Use for 'how does gross profit "
            "differ between New and Used Vehicle?' class of questions."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "ref_a": {"type": "string", "description": "Canonical range, e.g. 'New Vehicle!G4:G43'."},
                "ref_b": {"type": "string", "description": "Canonical range, e.g. 'Used Vehicle!G4:G43'."},
            },
            "required": ["ref_a", "ref_b"],
        },
    },
    {
        "name": "explain_circular",
        "description": (
            "Explain a circular (iterative) dependency in the workbook. "
            "Returns the cycle chain, each cell's formula, whether Excel "
            "iterative-calc is enabled, and any author comment found on a "
            "cell in the chain (authoritative for intentionality). Use for "
            "'why is this circular?' / 'is this cycle a bug?' questions. "
            "Call `list_findings(category='circular')` first if you don't know "
            "which cycle to explain."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "chain_index": {
                    "type": "integer",
                    "description": "Zero-based index into graph_summary.circular_references. Default 0 (first cycle).",
                    "default": 0,
                }
            },
            "required": [],
        },
    },
    # --- Analytics (Buckets A-G + three fixes) ---
    # Each analytics submodule exports TOOL_SCHEMAS; concatenated here so the
    # coordinator's system prompt routing lines can reference them by name.
    *_aggregators.TOOL_SCHEMAS,
    *_filters.TOOL_SCHEMAS,
    *_sql.TOOL_SCHEMAS,
    *_data_quality.TOOL_SCHEMAS,
    *_time_series.TOOL_SCHEMAS,
    *_stats.TOOL_SCHEMAS,
    *_goal_seek.TOOL_SCHEMAS,
    *_sensitivity.TOOL_SCHEMAS,
    {
        "name": "scenario_recalc",
        "description": "Recompute one or more target cells with multiple input overrides applied. Unlike what_if (single target), this supports composing scenarios (e.g. FloorPlanRate=7% AND ReconCostCap=3000). Returns new values for cells that changed.",
        "input_schema": {
            "type": "object",
            "properties": {
                "overrides": {
                    "type": "object",
                    "description": 'Dict mapping cell_ref_or_named_range to new value. Example: {"FloorPlanRate": 0.07, "ReconCostCap": 3000}.',
                },
                "target_refs": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional specific cells to recompute. If omitted, recomputes all cells impacted by the overrides.",
                },
            },
            "required": ["overrides"],
        },
    },
]


# --- Executor ---
#
# async because `find_cells` semantic tier calls Akash's async
# KnowledgeBaseService. All other tools are pure-sync CPU work.


async def execute_tool(
    wb: WorkbookModel,
    name: str,
    args: dict[str, Any],
    *,
    user_id: str | None = None,
    data_source_id: str | None = None,
) -> dict[str, Any]:
    try:
        if name == "list_sheets":
            return _list_sheets(wb)
        if name == "list_named_ranges":
            return _list_named_ranges(wb)
        if name == "get_cell":
            return _get_cell(wb, args["ref"])
        if name == "find_cells":
            return await _find_cells(
                wb,
                args["keyword"],
                args.get("has_formula", False),
                args.get("tier", "auto"),
                user_id=user_id,
                data_source_id=data_source_id,
            )
        if name == "backward_trace":
            return _backward_trace(wb, args["ref"], int(args.get("max_depth", 6)))
        if name == "forward_impact":
            return _forward_impact(wb, args["ref"], int(args.get("max_results", 100)))
        if name == "resolve_named_range":
            return _resolve_named_range(wb, args["name"])
        if name == "list_findings":
            return _list_findings(wb, args.get("category"))
        if name == "what_if":
            return _what_if(wb, args["target"], float(args["new_value"]), int(args.get("max_results", 30)))
        if name == "get_workbook_summary":
            return _get_workbook_summary(wb)
        if name == "scenario_recalc":
            return _scenario_recalc(wb, args["overrides"], args.get("target_refs"))
        if name == "explain_circular":
            return _explain_circular(wb, int(args.get("chain_index", 0)))
        if name == "list_pivot_tables":
            return _list_pivot_tables(wb)
        if name == "get_pivot_table":
            return _get_pivot_table(wb, args["sheet"], int(args.get("index", 0)))
        if name == "join_on_key":
            return _join_on_key(
                wb,
                args["sheet_a"],
                args["key_column_a"],
                args["sheet_b"],
                args["key_column_b"],
                args.get("select_a"),
                args.get("select_b"),
                args.get("filter_key"),
                int(args.get("max_rows", 50)),
            )
        if name == "compare_regions":
            return _compare_regions(wb, args["ref_a"], args["ref_b"])
        # --- Analytics dispatch ---
        # Bucket A
        if name == "aggregate_column":
            return _aggregators.aggregate_column(wb, args["sheet"], args["column"], args["agg"], args.get("where"))
        if name == "unique_values":
            return _aggregators.unique_values(wb, args["sheet"], args["column"], int(args.get("limit", 50)), args.get("where"))
        if name == "top_n":
            return _aggregators.top_n(
                wb, args["sheet"], args["column"], int(args.get("n", 5)),
                args.get("order", "desc"), args.get("include"), args.get("where"),
            )
        if name == "group_aggregate":
            return _aggregators.group_aggregate(
                wb, args["sheet"], args["group_by"], args["value_col"],
                args.get("agg", "sum"), args.get("where"), int(args.get("top", 20)),
            )
        if name == "histogram":
            return _aggregators.histogram(wb, args["sheet"], args["column"], int(args.get("bins", 10)), args.get("where"))
        # Filters / three fixes
        if name == "filter_rows":
            return _filters.filter_rows(
                wb, args["sheet"], args["where"], args.get("select"), int(args.get("max_rows", 50)),
            )
        if name == "lookup_row":
            return _filters.lookup_row(
                wb, args["sheet"], args["match_column"], args["match_value"], args.get("return_columns"),
            )
        if name == "scenario_filter":
            return _filters.scenario_filter(wb, args["sheet"], args["where"], args["aggregation"])
        if name == "compare_scenarios":
            return _filters.compare_scenarios(
                wb, args["sheet"], args.get("base_where"), args["alt_where"], args["aggregation"],
            )
        # SQL
        if name == "sql_schema":
            return _sql.sql_schema(wb)
        if name == "sql_query":
            return _sql.sql_query(wb, args["query"], int(args.get("limit", _sql.DEFAULT_LIMIT)))
        # Data quality
        if name == "count_missing":
            return _data_quality.count_missing(wb, args["sheet"], args.get("columns"))
        if name == "find_duplicates":
            return _data_quality.find_duplicates(wb, args["sheet"], args["columns"], int(args.get("max_groups", 20)))
        if name == "detect_outliers":
            return _data_quality.detect_outliers(
                wb, args["sheet"], args["column"], args.get("method", "iqr"), int(args.get("max_outliers", 25)),
            )
        # Time-series
        if name == "date_range_aggregate":
            return _time_series.date_range_aggregate(
                wb, args["sheet"], args["date_column"], args["start"], args["end"],
                args["value_column"], args.get("agg", "sum"),
            )
        if name == "time_bucket_aggregate":
            return _time_series.time_bucket_aggregate(
                wb, args["sheet"], args["date_column"], args["value_column"],
                args.get("bucket", "month"), args.get("agg", "sum"), int(args.get("limit", 24)),
            )
        if name == "trend_summary":
            return _time_series.trend_summary(
                wb, args["sheet"], args["date_column"], args["value_column"], args.get("bucket", "month"),
            )
        # Stats
        if name == "describe":
            return _stats.describe(wb, args["sheet"], args["column"])
        if name == "correlate":
            return _stats.correlate(wb, args["sheet"], args["column_a"], args["column_b"])
        # Goal-seek / sensitivity
        if name == "goal_seek":
            return _goal_seek.goal_seek(
                wb, args["target_ref"], float(args["target_value"]), args["input_ref"],
                args.get("bounds"), float(args.get("tolerance", 1e-4)), int(args.get("max_iter", 60)),
            )
        if name == "sensitivity":
            return _sensitivity.sensitivity(
                wb, args["target_ref"], args.get("input_refs"),
                float(args.get("delta", 0.10)), int(args.get("top", 20)),
            )
        if name == "elasticity":
            return _sensitivity.elasticity(
                wb, args["target_ref"], args["input_ref"], float(args.get("delta", 0.01)),
            )
        return {"error": f"unknown tool: {name}"}
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}


def _list_sheets(wb: WorkbookModel) -> dict:
    return {
        "sheets": [
            {
                "name": s.name,
                "hidden": s.hidden,
                "rows": s.max_row,
                "cols": s.max_col,
                "formulas": s.formula_count,
                "regions": [{"type": r.type, "rows": list(r.rows)} for r in s.regions[:10]],
                "hidden_rows": s.hidden_rows,
                "hidden_cols": s.hidden_cols,
            }
            for s in wb.sheets
        ]
    }


def _list_named_ranges(wb: WorkbookModel) -> dict:
    ev = Evaluator(wb)
    out = []
    for nr in wb.named_ranges:
        cv = nr.current_value
        if cv is None and len(nr.resolved_refs) == 1 and ":" not in nr.resolved_refs[0]:
            cell = wb.cells.get(nr.resolved_refs[0])
            if cell:
                cv = _resolved_value(cell, ev)
        out.append(
            {
                "name": nr.name,
                "scope": nr.scope,
                "resolves_to": nr.resolved_refs,
                "current_value": cv,
                "is_dynamic": nr.is_dynamic,
            }
        )
    return {"named_ranges": out}


def _get_cell(wb: WorkbookModel, ref: str) -> dict:
    ref = ref.replace("$", "").strip()
    cell = wb.cells.get(ref)
    if not cell:
        return {"error": f"cell not found: {ref}"}
    ev = Evaluator(wb)
    return {
        "ref": cell.ref,
        "sheet": cell.sheet,
        "coord": cell.coord,
        "value": _resolved_value(cell, ev),
        "formula": cell.formula,
        "formula_type": cell.formula_type,
        "semantic_label": cell.semantic_label,
        "depends_on": cell.depends_on[:50],
        "depended_by": cell.depended_by[:50],
        "named_ranges_used": cell.named_ranges_used,
        "is_hardcoded": cell.is_hardcoded,
        "is_volatile": cell.is_volatile,
    }


async def _find_cells(
    wb: WorkbookModel,
    keyword: str,
    has_formula: bool = False,
    tier: str = "auto",
    *,
    user_id: str | None = None,
    data_source_id: str | None = None,
) -> dict:
    """Three-tier cell lookup.

    Tiers:
      - exact: canonical cell ref like 'Sheet!A1', or exact named range name
      - keyword: substring match on cell.semantic_label (case-insensitive)
      - semantic: Akash's KnowledgeBaseService (OpenAI + Qdrant, filtered by user + data_source)
      - auto: try exact → keyword → semantic until non-empty
    """
    tier = tier.lower()
    if tier not in ("auto", "exact", "keyword", "semantic"):
        return {"error": f"invalid tier: {tier}"}

    results: list[dict] = []
    tier_used: str = tier

    # One evaluator shared across exact + keyword paths so memoization
    # amortizes the cost of resolving cached-None formula cells.
    ev = Evaluator(wb)

    def _run_exact() -> list[dict]:
        out: list[dict] = []
        q = keyword.strip().replace("$", "")
        # Direct cell ref
        if q in wb.cells:
            cell = wb.cells[q]
            out.append(
                {
                    "ref": cell.ref,
                    "label": cell.semantic_label,
                    "value": _resolved_value(cell, ev),
                    "has_formula": cell.formula is not None,
                    "formula": cell.formula,
                    "score": 1.0,
                    "tier_used": "exact",
                }
            )
            return out
        # Named range name
        nr = next((n for n in wb.named_ranges if n.name.lower() == q.lower()), None)
        if nr and nr.resolved_refs:
            for r in nr.resolved_refs:
                if ":" in r:
                    continue
                cell = wb.cells.get(r)
                if cell:
                    out.append(
                        {
                            "ref": cell.ref,
                            "label": cell.semantic_label,
                            "value": _resolved_value(cell, ev),
                            "has_formula": cell.formula is not None,
                            "formula": cell.formula,
                            "score": 1.0,
                            "tier_used": "exact",
                            "named_range": nr.name,
                        }
                    )
        return out

    def _run_keyword() -> list[dict]:
        out: list[dict] = []
        kw = keyword.lower().strip()
        if not kw:
            return out
        for ref, cell in wb.cells.items():
            if has_formula and not cell.formula:
                continue
            label = (cell.semantic_label or "").lower()
            if not label:
                continue
            if kw in label:
                score = 0.7 + (0.2 if cell.formula else 0)
                out.append(
                    {
                        "ref": ref,
                        "label": cell.semantic_label,
                        "value": _resolved_value(cell, ev),
                        "has_formula": cell.formula is not None,
                        "formula": cell.formula,
                        "score": score,
                        "tier_used": "keyword",
                    }
                )
            if len(out) >= 20:
                break
        # Rank: formulas first, then by label specificity
        out.sort(key=lambda m: (-m["score"], len(m["label"] or "")))
        return out

    async def _run_semantic() -> list[dict]:
        """Semantic similarity via Akash's KnowledgeBaseService (OpenAI + Qdrant).

        Opt-out: set ROSETTA_SEMANTIC_DISABLED=1.
        Requires `user_id` and `data_source_id` to filter the shared
        `excel_knowledge` collection to this user's workbook.
        """
        import os

        if os.environ.get("ROSETTA_SEMANTIC_DISABLED") == "1":
            return []
        if not (user_id and data_source_id):
            return []
        try:
            from core.vector.knowledge_base import KnowledgeBaseService

            kb = KnowledgeBaseService()
            hits = await kb.search(
                query=keyword,
                user_id=user_id,
                data_source_id=data_source_id,
                limit=10,
                score_threshold=0.5,
            )
        except Exception as e:
            import logging

            logging.getLogger("core.rosetta.tools").warning("semantic tier failed: %s", e)
            return []
        # Two chunk granularities live in Qdrant:
        #   - "cell" chunks: one per labeled cell, payload has `cell_ref`,
        #     `cell_label`, `section_header`. Map directly to our cell shape
        #     and (when the ref exists in this workbook) populate the live
        #     value so the coordinator can cite it without a follow-up call.
        #   - column/statistics chunks: descriptive only. Surface as context
        #     so Claude can reason about which sheet to inspect next.
        ev = Evaluator(wb)
        out: list[dict] = []
        for h in hits:
            md = h.metadata or {}
            ref = md.get("cell_ref")
            if ref and ref in wb.cells:
                cell = wb.cells[ref]
                out.append(
                    {
                        "ref": ref,
                        "label": md.get("cell_label") or cell.semantic_label,
                        "value": _resolved_value(cell, ev),
                        "has_formula": cell.formula is not None,
                        "formula": cell.formula,
                        "score": h.score,
                        "tier_used": "semantic",
                        "section": md.get("section_header"),
                    }
                )
            else:
                out.append(
                    {
                        "ref": None,
                        "label": md.get("chunk_type") or md.get("sheet_name"),
                        "value": None,
                        "has_formula": None,
                        "formula": None,
                        "score": h.score,
                        "tier_used": "semantic",
                        "context": h.content[:400] if h.content else None,
                        "chunk_metadata": md,
                    }
                )
        return out

    if tier == "exact":
        results = _run_exact()
    elif tier == "keyword":
        results = _run_keyword()
    elif tier == "semantic":
        results = await _run_semantic()
    else:  # auto — exact → keyword → (semantic if both empty)
        results = _run_exact()
        if results:
            tier_used = "exact"
        else:
            results = _run_keyword()
            if results:
                tier_used = "keyword"
            else:
                results = await _run_semantic()
                tier_used = "semantic" if results else "none"

    return {"matches": results, "count": len(results), "keyword": keyword, "tier_used": tier_used}


def _backward_trace(wb: WorkbookModel, ref: str, max_depth: int) -> dict:
    ref = ref.replace("$", "").strip()
    if ref not in wb.cells:
        return {"error": f"cell not found: {ref}"}
    trace = backward_trace(wb, ref, max_depth=max_depth)
    # Fill in computed values for nodes whose cached value is None.
    _fill_trace_values(trace, Evaluator(wb))
    return {"trace": trace.model_dump()}


def _forward_impact(wb: WorkbookModel, ref: str, max_results: int) -> dict:
    ref = ref.replace("$", "").strip()
    if ref not in wb.cells:
        return {"error": f"cell not found: {ref}"}
    impacted = forward_impacted(wb, ref)
    by_sheet: dict[str, list[dict]] = {}
    for r, depth in impacted[:max_results]:
        cell = wb.cells.get(r)
        sheet = r.split("!", 1)[0]
        by_sheet.setdefault(sheet, []).append(
            {
                "ref": r,
                "depth": depth,
                "label": cell.semantic_label if cell else None,
                "value": cell.value if cell else None,
            }
        )
    return {
        "total_impacted": len(impacted),
        "returned": min(len(impacted), max_results),
        "by_sheet": by_sheet,
    }


def _resolve_named_range(wb: WorkbookModel, name: str) -> dict:
    nr = next((n for n in wb.named_ranges if n.name.lower() == name.lower()), None)
    if not nr:
        return {"error": f"named range not found: {name}"}
    cv = nr.current_value
    if cv is None and len(nr.resolved_refs) == 1 and ":" not in nr.resolved_refs[0]:
        cell = wb.cells.get(nr.resolved_refs[0])
        if cell:
            cv = _resolved_value(cell, Evaluator(wb))
    return {
        "name": nr.name,
        "scope": nr.scope,
        "resolves_to": nr.resolved_refs,
        "current_value": cv,
        "is_dynamic": nr.is_dynamic,
        "raw": nr.raw_value,
    }


def _list_findings(wb: WorkbookModel, category: str | None) -> dict:
    findings = wb.findings or []
    if category:
        findings = [f for f in findings if f.category == category]
    return {
        "count": len(findings),
        "findings": [
            {
                "severity": f.severity,
                "category": f.category,
                "location": f.location,
                "message": f.message,
                "confidence": f.confidence,
                "detail": f.detail,
            }
            for f in findings[:50]
        ],
    }


def _what_if(wb: WorkbookModel, target: str, new_value: float, max_results: int) -> dict:
    # Resolve target to a cell ref
    target_clean = target.replace("$", "").strip()
    target_ref: str | None = None
    nr_name: str | None = None
    if target_clean in wb.cells:
        target_ref = target_clean
    else:
        nr = next((n for n in wb.named_ranges if n.name.lower() == target.lower()), None)
        if nr and nr.resolved_refs and ":" not in nr.resolved_refs[0]:
            target_ref = nr.resolved_refs[0]
            nr_name = nr.name
    if not target_ref:
        return {"error": f"could not resolve target '{target}' to a scalar cell or named range"}
    # Baseline evaluator (no overrides) for computing "old" values of formula
    # cells whose cached value is None.
    ev_base = Evaluator(wb)
    old_val = _resolved_value(wb.cells[target_ref], ev_base)
    ev = Evaluator(wb, overrides={target_ref: new_value})
    if nr_name:
        impacted = [r for r, _ in forward_impacted_for_named_range(wb, nr_name)]
    else:
        impacted = [r for r, _ in forward_impacted(wb, target_ref)]
    changes: list[dict] = []
    for r in impacted:
        cell = wb.cells.get(r)
        if not cell:
            continue
        new_v = ev.value_of(r)
        old_v = _resolved_value(cell, ev_base)
        if new_v != old_v:
            delta = None
            try:
                if isinstance(new_v, (int, float)) and isinstance(old_v, (int, float)):
                    delta = new_v - old_v
            except Exception:
                pass
            changes.append(
                {
                    "ref": r,
                    "label": cell.semantic_label,
                    "old": old_v,
                    "new": new_v,
                    "delta": delta,
                }
            )

    # Sort: cells with business labels first, then by absolute delta
    def sort_key(c):
        has_label = 1 if c.get("label") else 0
        d = abs(c["delta"]) if isinstance(c.get("delta"), (int, float)) else 0
        return (-has_label, -d)

    changes.sort(key=sort_key)
    return {
        "target": target_ref,
        "named_range": nr_name,
        "old_value": old_val,
        "new_value": new_value,
        "total_changed": len(changes),
        "unsupported_formulas": len(ev.unsupported),
        "changes": changes[:max_results],
    }


def _get_workbook_summary(wb: WorkbookModel) -> dict:
    from collections import Counter

    from .analytics.view import DataView

    finding_counts = Counter(f.category for f in (wb.findings or []))
    # Per-sheet mode classification + data-shape hints for tabular sheets.
    # A sheet is "tabular" when it has 0 formulas and >= 20 data rows — this
    # signals the coordinator to prefer analytics tools (aggregate_column /
    # filter_rows / sql_query) over trace tools.
    sheets_info: list[dict] = []
    for s in wb.sheets:
        mode = "formula" if s.formula_count > 0 else ("tabular" if s.max_row >= 20 else "other")
        info: dict = {
            "name": s.name,
            "rows": s.max_row,
            "cols": s.max_col,
            "formulas": s.formula_count,
            "hidden": s.hidden,
            "pivots": len(s.pivot_tables or []),
            "mode": mode,
        }
        if mode == "tabular":
            view = DataView.for_sheet(wb, s.name)
            if view is not None:
                headers = view.header_map
                # Infer a column's dominant type from its first 20 data cells
                col_summaries = []
                for letter in view.populated_columns[:20]:  # cap breadth for prompt size
                    sample = [
                        view.value(r, letter) for r in view.data_rows[:20]
                    ]
                    col_summaries.append(
                        {
                            "letter": letter,
                            "label": headers.get(letter, letter),
                            "inferred_type": _infer_dominant_type(sample),
                        }
                    )
                info["data_shape"] = {
                    "row_count": view.row_count,
                    "column_count": len(view.populated_columns),
                    "columns": col_summaries,
                    "columns_truncated": len(view.populated_columns) > 20,
                }
        sheets_info.append(info)
    return {
        "workbook_id": wb.workbook_id,
        "filename": wb.filename,
        "sheet_count": len(wb.sheets),
        "sheets": sheets_info,
        "named_range_count": len(wb.named_ranges),
        "named_ranges_sample": [n.name for n in wb.named_ranges[:30]],
        "has_circular_refs": len(wb.graph_summary.circular_references) > 0,
        "circular_ref_count": len(wb.graph_summary.circular_references),
        "total_formula_cells": wb.graph_summary.total_formula_cells,
        "cross_sheet_edges": wb.graph_summary.cross_sheet_edges,
        "finding_counts": dict(finding_counts),
    }


def _infer_dominant_type(sample: list[Any]) -> str:
    """Return the dominant cell-value type in a small sample.

    Used to give Claude a type hint per column so it can choose the right
    predicate operator and aggregation without a second probe call.
    """
    from datetime import date, datetime

    counts: dict[str, int] = {}
    for v in sample:
        if v is None or v == "":
            t = "empty"
        elif isinstance(v, bool):
            t = "bool"
        elif isinstance(v, (datetime, date)):
            t = "date"
        elif isinstance(v, (int, float)):
            t = "number"
        elif isinstance(v, str):
            t = "string"
        else:
            t = "other"
        counts[t] = counts.get(t, 0) + 1
    # Prefer non-empty types
    non_empty = {t: c for t, c in counts.items() if t != "empty"}
    if not non_empty:
        return "empty"
    return max(non_empty, key=non_empty.get)



def _list_pivot_tables(wb: WorkbookModel) -> dict:
    """List every pivot table across all sheets with a short summary per pivot."""
    pivots_out: list[dict] = []
    for sheet in wb.sheets:
        for i, pv in enumerate(sheet.pivot_tables or []):
            pivots_out.append(
                {
                    "sheet": sheet.name,
                    "index": i,
                    "name": pv.name,
                    "location": pv.location,
                    "source_range": pv.source_range,
                    "field_count": len(pv.fields),
                    "axes": {
                        "row": [f.name for f in pv.fields if f.axis == "row"],
                        "column": [f.name for f in pv.fields if f.axis == "column"],
                        "value": [f.name for f in pv.fields if f.axis == "value"],
                        "filter": [f.name for f in pv.fields if f.axis == "filter"],
                    },
                }
            )
    return {"count": len(pivots_out), "pivot_tables": pivots_out}


def _get_pivot_table(wb: WorkbookModel, sheet: str, index: int) -> dict:
    """Return the full layout for one pivot table."""
    sheet_model = next((s for s in wb.sheets if s.name == sheet), None)
    if sheet_model is None:
        return {"error": f"sheet not found: {sheet}"}
    pivots = sheet_model.pivot_tables or []
    if not pivots:
        return {"error": f"no pivot tables on sheet {sheet}"}
    if index < 0 or index >= len(pivots):
        return {"error": f"index {index} out of range (0..{len(pivots) - 1})"}
    pv = pivots[index]
    return {
        "sheet": sheet,
        "name": pv.name,
        "location": pv.location,
        "source_range": pv.source_range,
        "refresh_on_load": pv.refresh_on_load,
        "last_refreshed": pv.last_refreshed,
        "fields": [f.model_dump() for f in pv.fields],
    }


# --- join_on_key ---

_COL_LETTER_RE = re.compile(r"^[A-Z]+$")


def _resolve_column(wb: WorkbookModel, sheet: str, col_spec: str) -> str | None:
    """Resolve `col_spec` (either a column letter like 'A' or a header label
    like 'Deal#') to a column letter. Returns None if no match.

    For header-label resolution we scan the first 3 rows on the target sheet.
    """
    spec = col_spec.strip()
    if _COL_LETTER_RE.match(spec.upper()):
        return spec.upper()
    low = spec.lower()
    # Scan header cells in rows 1-3 for an exact match on label
    for ref, cell in wb.cells.items():
        if cell.sheet != sheet:
            continue
        row_m = "".join(ch for ch in cell.coord if ch.isdigit())
        if not row_m or int(row_m) > 3:
            continue
        if isinstance(cell.value, str) and cell.value.strip().lower() == low:
            # col letter from the coord
            return "".join(ch for ch in cell.coord if ch.isalpha())
    return None


def _rows_with_data(wb: WorkbookModel, sheet: str) -> list[int]:
    """Return sorted list of row numbers that have at least one populated cell."""
    rows: set[int] = set()
    for _, cell in wb.cells.items():
        if cell.sheet != sheet:
            continue
        row_m = "".join(ch for ch in cell.coord if ch.isdigit())
        if row_m:
            rows.add(int(row_m))
    return sorted(rows)


def _header_label_for_column(wb: WorkbookModel, sheet: str, col: str) -> str:
    """Return the header label for a column (first non-empty cell in rows 1-3)."""
    for r in (1, 2, 3):
        cell = wb.cells.get(f"{sheet}!{col}{r}")
        if cell and isinstance(cell.value, str) and cell.value.strip():
            return cell.value.strip()
    return col


def _join_on_key(
    wb: WorkbookModel,
    sheet_a: str,
    key_col_a: str,
    sheet_b: str,
    key_col_b: str,
    select_a: list[str] | None,
    select_b: list[str] | None,
    filter_key: str | None,
    max_rows: int,
) -> dict:
    # Resolve key columns
    ka = _resolve_column(wb, sheet_a, key_col_a)
    if ka is None:
        return {"error": f"could not resolve key column '{key_col_a}' on sheet '{sheet_a}'"}
    kb = _resolve_column(wb, sheet_b, key_col_b)
    if kb is None:
        return {"error": f"could not resolve key column '{key_col_b}' on sheet '{sheet_b}'"}

    # Resolve select columns (if omitted, grab everything populated on row 1-3)
    def _resolve_selects(sheet: str, select: list[str] | None) -> list[str]:
        if select:
            out: list[str] = []
            for s in select:
                r = _resolve_column(wb, sheet, s)
                if r and r not in out:
                    out.append(r)
            return out
        # All columns that have any data on this sheet
        cols: set[str] = set()
        for _, cell in wb.cells.items():
            if cell.sheet != sheet:
                continue
            col_l = "".join(ch for ch in cell.coord if ch.isalpha())
            if col_l:
                cols.add(col_l)
        return sorted(cols, key=lambda c: (len(c), c))

    cols_a = _resolve_selects(sheet_a, select_a)
    cols_b = _resolve_selects(sheet_b, select_b)

    ev = Evaluator(wb)

    def _build_row_dict(sheet: str, row: int, cols: list[str]) -> dict:
        d: dict[str, Any] = {}
        for col in cols:
            ref = f"{sheet}!{col}{row}"
            cell = wb.cells.get(ref)
            header = _header_label_for_column(wb, sheet, col)
            d[header] = _resolved_value(cell, ev) if cell else None
        return d

    # Build {key → row#} for each sheet (skip rows 1-3 as headers)
    def _index_by_key(sheet: str, key_col: str) -> dict[Any, int]:
        out: dict[Any, int] = {}
        for r in _rows_with_data(wb, sheet):
            if r <= 3:
                continue
            cell = wb.cells.get(f"{sheet}!{key_col}{r}")
            if cell is None:
                continue
            v = _resolved_value(cell, ev)
            if v is None:
                continue
            out[v] = r
        return out

    index_a = _index_by_key(sheet_a, ka)
    index_b = _index_by_key(sheet_b, kb)

    common_keys = set(index_a.keys()) & set(index_b.keys())
    if filter_key is not None:
        # Allow both exact match and string-coerced match
        key_candidates = {filter_key}
        try:
            key_candidates.add(int(filter_key))
        except (TypeError, ValueError):
            pass
        try:
            key_candidates.add(float(filter_key))
        except (TypeError, ValueError):
            pass
        common_keys = {k for k in common_keys if k in key_candidates or str(k) == str(filter_key)}

    rows: list[dict] = []
    for key in list(common_keys)[:max_rows]:
        rows.append(
            {
                "key": key,
                "a": _build_row_dict(sheet_a, index_a[key], cols_a),
                "b": _build_row_dict(sheet_b, index_b[key], cols_b),
            }
        )

    return {
        "sheet_a": sheet_a,
        "key_column_a": ka,
        "sheet_b": sheet_b,
        "key_column_b": kb,
        "total_matches": len(common_keys),
        "returned": len(rows),
        "rows": rows,
        "columns_a": [_header_label_for_column(wb, sheet_a, c) for c in cols_a],
        "columns_b": [_header_label_for_column(wb, sheet_b, c) for c in cols_b],
    }


# --- compare_regions ---

_RANGE_RE = re.compile(r"^(?:'([^']+)'|([A-Za-z_][\w ]*))!\$?([A-Z]+)\$?(\d+)(?::\$?([A-Z]+)\$?(\d+))?$")


def _parse_region(ref: str) -> tuple[str, str, int, str, int] | None:
    """Return (sheet, start_col, start_row, end_col, end_row) from 'Sheet!A1:B3'."""
    m = _RANGE_RE.match(ref.strip())
    if not m:
        return None
    sheet = m.group(1) or m.group(2)
    c1, r1 = m.group(3).upper(), int(m.group(4))
    c2 = (m.group(5) or c1).upper()
    r2 = int(m.group(6) or r1)
    return sheet, c1, r1, c2, r2


def _col_letter_to_index(col: str) -> int:
    n = 0
    for ch in col:
        n = n * 26 + (ord(ch) - ord("A") + 1)
    return n


def _col_index_to_letter(idx: int) -> str:
    s = ""
    while idx > 0:
        idx, rem = divmod(idx - 1, 26)
        s = chr(ord("A") + rem) + s
    return s


def _iterate_region(region: tuple[str, str, int, str, int]):
    """Yield every (sheet, coord) inside the region, top-to-bottom, left-to-right."""
    sheet, c1, r1, c2, r2 = region
    c1i, c2i = sorted([_col_letter_to_index(c1), _col_letter_to_index(c2)])
    r1i, r2i = sorted([r1, r2])
    for row in range(r1i, r2i + 1):
        for ci in range(c1i, c2i + 1):
            yield sheet, f"{_col_index_to_letter(ci)}{row}"


def _formula_token_sequence(formula: str) -> list[str]:
    """Outer-level sequence of function names + operator tokens, ignoring
    literal arg values. Used to judge whether two formulas have the same
    "shape" regardless of which specific cells they reference.
    """
    if not formula:
        return []
    tokens: list[str] = []
    for m in re.finditer(r"[A-Z]+\s*\(|[+\-*/^,&=<>]", formula.upper()):
        t = m.group(0).replace(" ", "")
        if t.endswith("("):
            tokens.append(t[:-1])  # function name
        else:
            tokens.append(t)
    return tokens


def _functions_in_formula(formula: str) -> set[str]:
    if not formula:
        return set()
    return {m.group(1) for m in re.finditer(r"([A-Z]+)\s*\(", formula.upper())}


def _compare_regions(wb: WorkbookModel, ref_a: str, ref_b: str) -> dict:
    reg_a = _parse_region(ref_a)
    reg_b = _parse_region(ref_b)
    if reg_a is None:
        return {"error": f"invalid range: {ref_a}"}
    if reg_b is None:
        return {"error": f"invalid range: {ref_b}"}

    cells_a = list(_iterate_region(reg_a))
    cells_b = list(_iterate_region(reg_b))
    # Compare on the intersection length — note extras on either side
    n = min(len(cells_a), len(cells_b))
    extras_a = len(cells_a) - n
    extras_b = len(cells_b) - n

    diffs: list[dict] = []
    identical = 0
    compared = 0
    funcs_a: set[str] = set()
    funcs_b: set[str] = set()
    names_a: set[str] = set()
    names_b: set[str] = set()

    for i in range(n):
        sa, coord_a = cells_a[i]
        sb, coord_b = cells_b[i]
        ca = wb.cells.get(f"{sa}!{coord_a}")
        cb = wb.cells.get(f"{sb}!{coord_b}")
        # Skip positions where both sides are empty
        if (ca is None or (ca.formula is None and ca.value is None)) and (
            cb is None or (cb.formula is None and cb.value is None)
        ):
            continue
        compared += 1
        fa = ca.formula if ca else None
        fb = cb.formula if cb else None
        if fa:
            funcs_a |= _functions_in_formula(fa)
            names_a |= set(ca.named_ranges_used or [])
        if fb:
            funcs_b |= _functions_in_formula(fb)
            names_b |= set(cb.named_ranges_used or [])
        # Case 1: both hardcoded — no formula comparison
        if not fa and not fb:
            continue
        # Case 2: one hardcoded, one formula → shape mismatch
        if bool(fa) != bool(fb):
            diffs.append(
                {
                    "kind": "shape_mismatch",
                    "a_ref": f"{sa}!{coord_a}",
                    "b_ref": f"{sb}!{coord_b}",
                    "a_formula": fa,
                    "b_formula": fb,
                    "note": "one side is hardcoded while the other uses a formula",
                }
            )
            continue
        # Both formulas — compare outer token sequence
        seq_a = _formula_token_sequence(fa)
        seq_b = _formula_token_sequence(fb)
        if seq_a == seq_b:
            identical += 1
        else:
            diffs.append(
                {
                    "kind": "different_shape",
                    "a_ref": f"{sa}!{coord_a}",
                    "b_ref": f"{sb}!{coord_b}",
                    "a_formula": fa,
                    "b_formula": fb,
                    "a_tokens": seq_a,
                    "b_tokens": seq_b,
                }
            )

    match_pct = round((identical / compared) * 100, 1) if compared else 0.0

    return {
        "ref_a": ref_a,
        "ref_b": ref_b,
        "compared_cells": compared,
        "shape_match_count": identical,
        "shape_match_pct": match_pct,
        "shape_diffs": diffs[:40],
        "extras_a": extras_a,
        "extras_b": extras_b,
        "functions_only_a": sorted(funcs_a - funcs_b),
        "functions_only_b": sorted(funcs_b - funcs_a),
        "functions_both": sorted(funcs_a & funcs_b),
        "named_ranges_only_a": sorted(names_a - names_b),
        "named_ranges_only_b": sorted(names_b - names_a),
    }


def _explain_circular(wb: WorkbookModel, chain_index: int) -> dict:
    """Return a structured explanation of the N-th detected cycle.

    Surfaces:
      - The cycle's cells with formula, semantic label, current value
      - Whether it's marked intentional and the evidence backing that
        (author comment vs. iterative-calc flag vs. neither)
      - A short prose template the coordinator can splice into its answer
    """
    cycles = wb.graph_summary.circular_references or []
    if not cycles:
        return {"error": "No circular references detected in this workbook."}
    if chain_index < 0 or chain_index >= len(cycles):
        return {
            "error": f"chain_index {chain_index} out of range (0..{len(cycles) - 1})",
            "available_cycles": len(cycles),
        }
    cr = cycles[chain_index]
    ev = Evaluator(wb)

    steps: list[dict] = []
    for ref in cr.chain:
        cell = wb.cells.get(ref)
        steps.append(
            {
                "ref": ref,
                "label": cell.semantic_label if cell else None,
                "formula": cell.formula if cell else None,
                "value": _resolved_value(cell, ev) if cell else None,
            }
        )

    # Evidence summary
    evidence = {}
    if cr.author_comment:
        evidence["source"] = "author_comment"
        evidence["comment_on"] = cr.commented_ref
        evidence["comment_author"] = cr.comment_author
        evidence["comment_text"] = cr.author_comment
    elif cr.intentional and cr.note and "iterative calculation" in cr.note.lower():
        evidence["source"] = "iterative_calc_setting"
        evidence["detail"] = cr.note
    elif cr.intentional:
        evidence["source"] = "heuristic"
        evidence["detail"] = cr.note
    else:
        evidence["source"] = "none"
        evidence["detail"] = (
            "No author comment and iterative calculation is not enabled. "
            "The cycle may still be intentional in the author's mental model — "
            "but there is no explicit evidence to confirm."
        )

    # Prose template — the coordinator can use this as-is or paraphrase.
    chain_prose = " → ".join(cr.chain)
    if cr.author_comment and cr.commented_ref:
        reason = (
            f"The author left a comment on {cr.commented_ref} stating: "
            f'"{cr.author_comment}". This confirms the cycle is intentional.'
        )
    elif cr.intentional:
        reason = cr.note or "The cycle appears intentional based on workbook settings."
    else:
        reason = (
            "There is no author comment on any cell in the chain, and iterative "
            "calculation is not enabled. The cycle may be a bug, or intentional "
            "but undocumented — the workbook doesn't say."
        )
    prose = (
        f"This is a circular dependency: {chain_prose}. {reason} "
        f"The cycle involves {len(steps)} cells; the formulas are shown above."
    )

    return {
        "chain_index": chain_index,
        "chain": cr.chain,
        "intentional": cr.intentional,
        "steps": steps,
        "evidence": evidence,
        "prose": prose,
    }


def _scenario_recalc(wb: WorkbookModel, overrides: dict[str, Any], target_refs: list[str] | None) -> dict:
    """Recompute target_refs (or all impacted) with multi-override scenario.

    overrides keys can be cell refs or named range names.
    """
    # Resolve each override key to a cell ref
    resolved: dict[str, Any] = {}
    unresolved: list[str] = []
    for key, val in overrides.items():
        ref = key.replace("$", "").strip()
        if ref in wb.cells:
            resolved[ref] = val
            continue
        # Try named range
        nr = next((n for n in wb.named_ranges if n.name.lower() == key.lower()), None)
        if nr and nr.resolved_refs and ":" not in nr.resolved_refs[0]:
            resolved[nr.resolved_refs[0]] = val
            continue
        unresolved.append(key)

    if not resolved:
        return {"error": "No overrides could be resolved to cells", "unresolved": unresolved}

    ev = Evaluator(wb, overrides=resolved)
    ev_base = Evaluator(wb)  # baseline, no overrides — for "old" value of formula cells

    # Determine targets
    if target_refs:
        target_list = [t.replace("$", "").strip() for t in target_refs]
    else:
        # All cells impacted by any override
        impacted: set[str] = set()
        for override_ref in resolved:
            for r, _ in forward_impacted(wb, override_ref):
                impacted.add(r)
        target_list = list(impacted)

    recalculated: dict[str, Any] = {}
    unchanged_count = 0
    for r in target_list:
        cell = wb.cells.get(r)
        if not cell:
            continue
        new_v = ev.value_of(r)
        old_v = _resolved_value(cell, ev_base)
        if new_v != old_v:
            recalculated[r] = {
                "label": cell.semantic_label,
                "old": old_v,
                "new": new_v,
            }
        else:
            unchanged_count += 1

    return {
        "overrides_applied": resolved,
        "overrides_unresolved": unresolved,
        "total_targets": len(target_list),
        "changed_count": len(recalculated),
        "unchanged_count": unchanged_count,
        "unsupported_formulas": list(ev.unsupported)[:30],
        "recalculated": recalculated,
    }
