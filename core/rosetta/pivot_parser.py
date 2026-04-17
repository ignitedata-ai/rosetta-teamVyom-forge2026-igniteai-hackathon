"""Pivot-table XML parser.

openpyxl exposes pivot tables but reads them shallowly — fields, aggregations,
calculated-field formulas are often lost. For reliability we parse the raw
`xl/pivotTables/*.xml` and `xl/pivotCache/pivotCacheDefinition*.xml` entries
inside the `.xlsx` zip directly.

The result: for each pivot, we extract
  - location (sheet + range the pivot is rendered in)
  - source range (where the raw data lives)
  - every field classified as row / column / value / filter
  - each value field's aggregation function (sum / average / count / ...)
  - calculated-field names + formulas
  - refresh-on-load flag + last refresh date

We deliberately skip external (OLAP / Power Query) sources — those require a
different resolver.
"""

from __future__ import annotations

import logging
import re
import zipfile
from pathlib import Path
from typing import Any

from lxml import etree

from .models import PivotFieldModel, PivotTableModel

log = logging.getLogger("rosetta.pivot_parser")

_NS = {
    "x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
}


def parse_pivot_tables(source_path: str | Path) -> dict[str, list[PivotTableModel]]:
    """Return a mapping {sheet_name → [PivotTableModel, ...]}.

    Any sheet not appearing in the map has no pivots. Returns an empty dict
    if the workbook contains no pivots at all, or if parsing fails.
    """
    out: dict[str, list[PivotTableModel]] = {}
    try:
        with zipfile.ZipFile(source_path) as z:
            namelist = z.namelist()
            pivot_entries = [n for n in namelist if _is_pivot_table_entry(n)]
            if not pivot_entries:
                return {}

            # Map each pivot to its cache definition
            cache_defs = _load_cache_definitions(z, namelist)

            # Map each pivot to the sheet it's placed on via workbook rels
            pivot_to_sheet = _map_pivots_to_sheets(z, namelist)

            for entry in pivot_entries:
                try:
                    pivot = _parse_pivot_table(z, entry, cache_defs)
                except Exception as e:
                    log.warning("pivot parse failed for %s: %s", entry, e)
                    continue
                sheet_name = pivot_to_sheet.get(entry)
                if not sheet_name:
                    continue
                out.setdefault(sheet_name, []).append(pivot)
    except Exception as e:
        log.warning("pivot-table parsing failed for %s: %s", source_path, e)
        return {}
    return out


# --- Internals ---


def _is_pivot_table_entry(name: str) -> bool:
    return name.startswith("xl/pivotTables/pivotTable") and name.endswith(".xml")


def _load_cache_definitions(z: zipfile.ZipFile, namelist: list[str]) -> dict[str, dict[str, Any]]:
    """Return {cache_path → {source_range, field_names[]}}."""
    cache_map: dict[str, dict[str, Any]] = {}
    for n in namelist:
        if not (n.startswith("xl/pivotCache/pivotCacheDefinition") and n.endswith(".xml")):
            continue
        try:
            root = etree.fromstring(z.read(n))
        except Exception:
            continue
        cache: dict[str, Any] = {"field_names": []}
        # Source range
        src = root.find("x:cacheSource/x:worksheetSource", _NS)
        if src is not None:
            sheet = src.get("sheet")
            ref = src.get("ref")
            if sheet and ref:
                cache["source_range"] = f"{sheet}!{ref}"
            name_attr = src.get("name")
            if name_attr and "source_range" not in cache:
                cache["source_range"] = name_attr  # named range fallback
        # Field names (positional — pivotTable references them by index)
        for f in root.findall("x:cacheFields/x:cacheField", _NS):
            cache["field_names"].append(f.get("name") or f"field_{len(cache['field_names'])}")
        cache_map[n] = cache
    return cache_map


def _map_pivots_to_sheets(z: zipfile.ZipFile, namelist: list[str]) -> dict[str, str]:
    """For each pivotTable XML path, determine which sheet hosts it.

    We read each sheet's rels file and look for Relationships whose Type
    ends in `/pivotTable` — the Target points at the pivot XML.
    Then we map sheet file paths to sheet names via `xl/workbook.xml`.
    """
    # sheet filepath → sheet name
    sheet_name_by_path: dict[str, str] = {}
    try:
        wb_root = etree.fromstring(z.read("xl/workbook.xml"))
        wb_rels_root = etree.fromstring(z.read("xl/_rels/workbook.xml.rels"))
    except Exception:
        return {}
    rels_by_rid: dict[str, str] = {}
    for rel in wb_rels_root.findall("{http://schemas.openxmlformats.org/package/2006/relationships}Relationship"):
        rels_by_rid[rel.get("Id")] = rel.get("Target")
    for sheet_el in wb_root.findall("x:sheets/x:sheet", _NS):
        rid = sheet_el.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id")
        target = rels_by_rid.get(rid)
        if target:
            # Normalize "worksheets/sheet1.xml" → "xl/worksheets/sheet1.xml"
            path = target if target.startswith("xl/") else f"xl/{target.lstrip('/')}"
            sheet_name_by_path[path] = sheet_el.get("name")

    # Now for each sheet rels, map pivotTable targets
    pivot_to_sheet: dict[str, str] = {}
    for sheet_path, sheet_name in sheet_name_by_path.items():
        rels_path = sheet_path.replace("worksheets/", "worksheets/_rels/") + ".rels"
        if rels_path not in z.namelist():
            continue
        try:
            rels_root = etree.fromstring(z.read(rels_path))
        except Exception:
            continue
        for rel in rels_root.findall("{http://schemas.openxmlformats.org/package/2006/relationships}Relationship"):
            rtype = rel.get("Type", "")
            if not rtype.endswith("/pivotTable"):
                continue
            target = rel.get("Target", "")
            # Normalize relative path → absolute zip path
            pivot_path = _resolve_rel_target(sheet_path, target)
            pivot_to_sheet[pivot_path] = sheet_name
    return pivot_to_sheet


def _resolve_rel_target(from_path: str, target: str) -> str:
    """Resolve a relative relationship target against the file it appears in."""
    if target.startswith("/"):
        return target.lstrip("/")
    from_parts = from_path.split("/")[:-1]
    tgt = target
    while tgt.startswith("../"):
        tgt = tgt[3:]
        from_parts.pop() if from_parts else None
    return "/".join(from_parts + [tgt])


def _parse_pivot_table(
    z: zipfile.ZipFile, path: str, cache_defs: dict[str, dict[str, Any]]
) -> PivotTableModel:
    """Parse one pivotTable*.xml entry into a PivotTableModel."""
    root = etree.fromstring(z.read(path))
    name = root.get("name") or path.rsplit("/", 1)[-1]
    location = root.find("x:location", _NS)
    loc_ref = location.get("ref") if location is not None else "?"
    refresh_on_load = root.get("refreshOnLoad") == "1"
    last_refreshed = root.get("refreshedDate")

    # Resolve cache definition via this pivot's rels file
    cache_def_path = _resolve_cache_def(z, path)
    cache = cache_defs.get(cache_def_path) or {}
    source_range = cache.get("source_range")
    field_names: list[str] = list(cache.get("field_names", []))

    fields: list[PivotFieldModel] = []

    # pivotFields — positional, matches cache field_names by index
    pivot_fields_el = root.find("x:pivotFields", _NS)
    field_defs: list[tuple[str, str | None]] = []  # (name, axis)
    if pivot_fields_el is not None:
        for i, pf in enumerate(pivot_fields_el.findall("x:pivotField", _NS)):
            axis = pf.get("axis")  # axisRow, axisCol, axisPage — or None for values/hidden
            name_i = field_names[i] if i < len(field_names) else f"field_{i}"
            field_defs.append((name_i, axis))

    # Row fields: <rowFields><field x="N"/></rowFields>
    for rf in root.findall("x:rowFields/x:field", _NS):
        idx = int(rf.get("x", "-1"))
        if 0 <= idx < len(field_defs):
            fields.append(PivotFieldModel(name=field_defs[idx][0], axis="row"))
    for cf in root.findall("x:colFields/x:field", _NS):
        idx = int(cf.get("x", "-1"))
        if 0 <= idx < len(field_defs):
            fields.append(PivotFieldModel(name=field_defs[idx][0], axis="column"))
    for pf in root.findall("x:pageFields/x:pageField", _NS):
        idx = int(pf.get("fld", "-1"))
        if 0 <= idx < len(field_defs):
            fields.append(PivotFieldModel(name=field_defs[idx][0], axis="filter"))
    # Value fields (dataFields) — carry an aggregation function
    for df in root.findall("x:dataFields/x:dataField", _NS):
        idx = int(df.get("fld", "-1"))
        subtotal = df.get("subtotal") or "sum"
        if 0 <= idx < len(field_defs):
            fields.append(
                PivotFieldModel(
                    name=field_defs[idx][0],
                    axis="value",
                    aggregation=subtotal,
                )
            )
    # Calculated fields — names + formulas live on pivotField children via .calculatedFields
    for cf in root.findall("x:calculatedFields/x:calculatedField", _NS):
        fields.append(
            PivotFieldModel(
                name=cf.get("name") or "calculated",
                axis="value",
                aggregation="calculated",
                formula=cf.get("formula"),
            )
        )

    # Canonicalize location
    canonical_loc = loc_ref or "?"

    return PivotTableModel(
        name=name,
        location=canonical_loc,
        source_range=source_range,
        fields=fields,
        refresh_on_load=refresh_on_load,
        last_refreshed=last_refreshed,
    )


def _resolve_cache_def(z: zipfile.ZipFile, pivot_path: str) -> str | None:
    """Follow the pivot's rels to find the cacheDefinition XML path."""
    rels_dir, fname = pivot_path.rsplit("/", 1)
    rels_path = f"{rels_dir}/_rels/{fname}.rels"
    if rels_path not in z.namelist():
        return None
    try:
        rels_root = etree.fromstring(z.read(rels_path))
    except Exception:
        return None
    for rel in rels_root.findall("{http://schemas.openxmlformats.org/package/2006/relationships}Relationship"):
        rtype = rel.get("Type", "")
        if rtype.endswith("/pivotCacheDefinition"):
            return _resolve_rel_target(pivot_path, rel.get("Target", ""))
    return None
