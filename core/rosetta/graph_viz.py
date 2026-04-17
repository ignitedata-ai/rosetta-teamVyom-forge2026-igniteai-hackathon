"""Convert a backward_trace TraceNode tree into a React-Flow-friendly
{nodes, edges, focal_ref} payload the UI can render.

The coordinator already captures a backward-trace whenever Claude asks
"how is X calculated?" (see coordinator._run_tool_loop, where
trace_seen is set from backward_trace outputs). We reuse that tree —
no new tool call needed — and walk it breadth-first, dedup'd by ref,
producing one node per unique cell and one edge per depends-on relation.

Nodes carry sheet, coord, label, current value, formula, and flags
(is_hardcoded / is_volatile / is_focal) so the client can style them.
Positions are NOT included — the frontend runs dagre for layout.
"""

from __future__ import annotations

from typing import Any


def trace_to_graph(trace: dict | None) -> dict | None:
    """Walk a TraceNode dict tree into {nodes, edges, focal_ref}.

    Returns None if trace is missing or empty. Returns None if the tree
    has fewer than 2 cells (a single-node graph carries no visual value
    and should not be rendered — the coordinator's prose answer already
    contains the one cell's info).
    """
    if not trace or not isinstance(trace, dict):
        return None
    focal_ref = trace.get("ref")
    if not focal_ref:
        return None

    nodes: dict[str, dict] = {}
    edges: list[dict] = []
    edge_seen: set[tuple[str, str]] = set()

    def _add_node(node_dict: dict, is_focal: bool = False) -> None:
        ref = node_dict.get("ref")
        if not ref or ref in nodes:
            if ref in nodes and is_focal:
                nodes[ref]["data"]["is_focal"] = True
            return
        sheet, _, coord = ref.partition("!")
        nodes[ref] = {
            "id": ref,
            "data": {
                "ref": ref,
                "sheet": sheet,
                "coord": coord or ref,
                "label": node_dict.get("label"),
                "value": _format_value(node_dict.get("value")),
                "formula": node_dict.get("formula"),
                "is_hardcoded": bool(node_dict.get("is_hardcoded")),
                "is_volatile": bool(node_dict.get("is_volatile")),
                "named_range": node_dict.get("named_range"),
                "is_focal": is_focal,
                "is_range": ":" in (coord or ""),
            },
        }

    def _walk(node_dict: dict, is_root: bool = False) -> None:
        _add_node(node_dict, is_focal=is_root)
        parent_ref = node_dict.get("ref")
        if not parent_ref:
            return
        for child in node_dict.get("children") or []:
            child_ref = child.get("ref")
            if not child_ref:
                continue
            _walk(child, is_root=False)
            # Edge: parent depends_on child (render left-to-right so inputs
            # flow into outputs; source = child (input), target = parent).
            key = (child_ref, parent_ref)
            if key in edge_seen:
                continue
            edge_seen.add(key)
            edges.append(
                {
                    "id": f"{child_ref}->{parent_ref}",
                    "source": child_ref,
                    "target": parent_ref,
                }
            )

    _walk(trace, is_root=True)

    if len(nodes) < 2:
        return None

    return {
        "nodes": list(nodes.values()),
        "edges": edges,
        "focal_ref": focal_ref,
        "node_count": len(nodes),
        "edge_count": len(edges),
    }


def _format_value(value: Any) -> str | None:
    """Render a cell value for display. Keep it short."""
    if value is None:
        return None
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, (int, float)):
        # Heuristic: currency-ish if abs value >= 1000, otherwise raw
        try:
            f = float(value)
        except (TypeError, ValueError):
            return str(value)
        if abs(f) >= 1000:
            return f"{f:,.2f}" if not float(f).is_integer() else f"{int(f):,}"
        if abs(f) < 1 and f != 0:
            return f"{f:.4f}".rstrip("0").rstrip(".")
        return f"{f:,.2f}" if not float(f).is_integer() else f"{int(f):,}"
    s = str(value)
    return s if len(s) <= 40 else s[:37] + "..."
