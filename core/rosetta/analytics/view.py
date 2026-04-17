"""DataView — the single shared abstraction for all analytics tools.

Every aggregator, filter, stats, time-series, and SQL bridge in this
package builds on DataView. It owns:

  - column resolution (letter vs header label)
  - header-row detection
  - row iteration (with header rows skipped)
  - value resolution via the existing Evaluator (so formula cells return
    computed values, not formula strings)
  - filter application with a compact predicate language
  - evidence-range serialisation for the citation auditor

Every tool in core/rosetta/analytics/ operates on a DataView rather than
reaching into WorkbookModel directly. This means column resolution,
filtering, and evidence generation are implemented exactly once.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterator, Sequence

from ..evaluator import Evaluator
from ..models import CellModel, WorkbookModel

# Excel column letters are 1-3 characters (A..XFD). Longer uppercase strings
# are labels that happen to be all-caps (e.g. "LATITUDE", "HOURLYWETBULBTEMPERATUREF").
_COL_LETTER_RE = re.compile(r"^[A-Z]{1,3}$")
_COORD_SPLIT_RE = re.compile(r"([A-Z]+)(\d+)")


# --- Filter predicates ---------------------------------------------------

# Operators accepted by `DataView.filter`. `in` expects a list on the rhs.
# All numeric comparisons coerce to float; string comparisons are
# case-insensitive unless `contains_cs` is specified (rare).
_VALID_OPS = {"=", "==", "!=", ">", ">=", "<", "<=", "in", "not_in", "contains", "startswith", "endswith"}


@dataclass(frozen=True)
class Predicate:
    """Parsed filter predicate. Use `Predicate.parse` to validate input."""

    column: str  # letter (already resolved)
    op: str
    value: Any

    @staticmethod
    def parse(raw: dict, view: "DataView") -> "Predicate":
        col_spec = raw.get("column")
        op = (raw.get("operator") or raw.get("op") or "=").strip()
        if op == "==":
            op = "="
        if op not in _VALID_OPS:
            raise ValueError(f"invalid operator '{op}'; expected one of {sorted(_VALID_OPS)}")
        if not col_spec:
            raise ValueError("predicate missing 'column'")
        letter = view.resolve_column(col_spec)
        if letter is None:
            raise ValueError(f"could not resolve column '{col_spec}' on sheet '{view.sheet}'")
        return Predicate(column=letter, op=op, value=raw.get("value"))


# --- DataView ------------------------------------------------------------


class DataView:
    """A narrowed projection of one sheet suitable for analytical queries.

    Construction scans the sheet once to build:
      - A header map (column letter → label) covering the first header row
      - A sorted list of data rows (rows with at least one populated cell
        below the header)

    `filter()` returns a new DataView with narrowed `data_rows`; no work
    is repeated on the underlying workbook. The shared `Evaluator` is
    retained across derived views to preserve memoisation.
    """

    def __init__(
        self,
        wb: WorkbookModel,
        sheet: str,
        *,
        header_rows: int = 1,
        _evaluator: Evaluator | None = None,
        _data_rows: list[int] | None = None,
        _header_map: dict[str, str] | None = None,
        _populated_cols: list[str] | None = None,
    ):
        self.wb = wb
        self.sheet = sheet
        self.header_rows = header_rows
        self.evaluator = _evaluator or Evaluator(wb)
        if _header_map is None or _data_rows is None or _populated_cols is None:
            self._header_map, self._data_rows, self._populated_cols = self._scan()
        else:
            self._header_map = _header_map
            self._data_rows = _data_rows
            self._populated_cols = _populated_cols

    # -- construction / scanning -----------------------------------------

    @classmethod
    def for_sheet(cls, wb: WorkbookModel, sheet: str, header_rows: int = 1) -> "DataView | None":
        """Factory that returns None if the sheet doesn't exist."""
        if not any(s.name == sheet for s in wb.sheets):
            return None
        return cls(wb, sheet, header_rows=header_rows)

    def _scan(self) -> tuple[dict[str, str], list[int], list[str]]:
        """One-pass scan of the sheet to find headers, data rows, populated cols.

        Header map uses row 1 by default; labels from row 2+ are used as
        fallbacks when row 1 is empty for a given column (common for
        sheets with a banner / title row).
        """
        header_map: dict[str, str] = {}
        populated_cols: set[str] = set()
        data_rows: set[int] = set()

        for ref, cell in self.wb.cells.items():
            if cell.sheet != self.sheet:
                continue
            m = _COORD_SPLIT_RE.match(cell.coord)
            if not m:
                continue
            col, row_s = m.group(1), int(m.group(2))
            populated_cols.add(col)

            # Header: within the header-rows band — prefer row 1, else use
            # the first populated row's label as a fallback per column.
            if row_s <= self.header_rows:
                if col not in header_map and isinstance(cell.value, str) and cell.value.strip():
                    header_map[col] = cell.value.strip()
                continue
            data_rows.add(row_s)

        return header_map, sorted(data_rows), sorted(populated_cols, key=_col_index)

    # -- column resolution -----------------------------------------------

    def resolve_column(self, spec: str | None) -> str | None:
        """Resolve a column spec (letter like 'A' or label like 'STATION_NAME')
        to a column letter. Returns None if no match.

        Resolution order:
          1. Exact header-label match (case-insensitive) — highest priority
             so that a label like 'LAT' wins over the column letter 'LAT'
             in the unlikely collision.
          2. Column letter (1-3 upper-case chars, matching Excel's XFD cap).
          3. Loose substring match against header labels.
        """
        if not spec:
            return None
        s = spec.strip()
        low = s.lower()
        # 1. Exact label match
        for letter, label in self._header_map.items():
            if label.lower() == low:
                return letter
        # 2. Column letter
        up = s.upper()
        if _COL_LETTER_RE.match(up):
            return up
        # 3. Loose substring match
        for letter, label in self._header_map.items():
            if low in label.lower():
                return letter
        return None

    def header_label(self, column: str) -> str:
        """Return the header label for a column, or the letter if absent."""
        return self._header_map.get(column, column)

    # -- data access ------------------------------------------------------

    @property
    def data_rows(self) -> list[int]:
        return self._data_rows

    @property
    def populated_columns(self) -> list[str]:
        return self._populated_cols

    @property
    def header_map(self) -> dict[str, str]:
        return dict(self._header_map)

    @property
    def row_count(self) -> int:
        return len(self._data_rows)

    def cell(self, row: int, column: str) -> CellModel | None:
        return self.wb.cells.get(f"{self.sheet}!{column}{row}")

    def value(self, row: int, column: str) -> Any:
        """Resolved cell value — formula cells return computed values via the
        shared Evaluator."""
        cell = self.cell(row, column)
        if cell is None:
            return None
        if cell.value is not None or cell.formula is None:
            return cell.value
        try:
            return self.evaluator.value_of(cell.ref)
        except Exception:
            return None

    def column_values(self, column: str, *, skip_none: bool = True) -> list[tuple[int, Any]]:
        """Yield `(row, value)` tuples for a column across this view's data rows."""
        letter = self.resolve_column(column) or column
        out: list[tuple[int, Any]] = []
        for row in self._data_rows:
            v = self.value(row, letter)
            if skip_none and (v is None or v == ""):
                continue
            out.append((row, v))
        return out

    def iter_rows(self, columns: Sequence[str] | None = None) -> Iterator[dict[str, Any]]:
        """Iterate rows as dicts keyed by header label (or column letter when
        no label). If `columns` is given, restrict to those (resolved)."""
        cols = (
            [self.resolve_column(c) or c for c in columns]
            if columns
            else self._populated_cols
        )
        for row in self._data_rows:
            out: dict[str, Any] = {"__row__": row}
            for col in cols:
                out[self.header_label(col)] = self.value(row, col)
            yield out

    # -- filtering --------------------------------------------------------

    def filter(self, predicates: list[dict] | None) -> "DataView":
        """Return a narrowed view with only rows satisfying all predicates.

        Predicates form: `[{"column": "ELEVATION", "op": ">", "value": 100}, ...]`
        All predicates are AND-combined.
        """
        if not predicates:
            return self
        parsed = [Predicate.parse(p, self) for p in predicates]
        kept: list[int] = []
        for row in self._data_rows:
            if all(_matches(self.value(row, p.column), p) for p in parsed):
                kept.append(row)
        return DataView(
            self.wb,
            self.sheet,
            header_rows=self.header_rows,
            _evaluator=self.evaluator,
            _data_rows=kept,
            _header_map=self._header_map,
            _populated_cols=self._populated_cols,
        )

    # -- evidence ---------------------------------------------------------

    def evidence_range(self, column: str | None = None) -> str | None:
        """Canonical evidence range covering this view's data rows.

        If `column` is given, returns `Sheet!<col><first>:<col><last>`.
        Without column, returns the bounding rectangle over populated
        columns: `Sheet!<first_col><first_row>:<last_col><last_row>`.
        Returns None if the view is empty.
        """
        if not self._data_rows:
            return None
        first, last = self._data_rows[0], self._data_rows[-1]
        if column is not None:
            letter = self.resolve_column(column) or column
            return f"{self.sheet}!{letter}{first}:{letter}{last}"
        if not self._populated_cols:
            return None
        c1, c2 = self._populated_cols[0], self._populated_cols[-1]
        return f"{self.sheet}!{c1}{first}:{c2}{last}"

    def evidence_refs(self, column: str | None = None, limit: int = 20) -> list[str]:
        """First `limit` cell refs relevant to a column (or row prefixes).
        Used by tools that want to cite a handful of concrete cells
        alongside the range."""
        if column is None:
            return [f"{self.sheet}!A{r}" for r in self._data_rows[:limit]]
        letter = self.resolve_column(column) or column
        return [f"{self.sheet}!{letter}{r}" for r in self._data_rows[:limit]]


# --- helpers -------------------------------------------------------------


def _col_index(col: str) -> int:
    n = 0
    for ch in col.upper():
        n = n * 26 + (ord(ch) - ord("A") + 1)
    return n


def _matches(v: Any, p: Predicate) -> bool:
    """Evaluate a predicate against a cell value. Missing values never match
    anything (even `!=`) — filters are positive assertions about data that
    must exist."""
    if v is None or v == "":
        return False
    op, rhs = p.op, p.value
    if op == "in":
        return v in (rhs or [])
    if op == "not_in":
        return v not in (rhs or [])
    if op == "contains":
        return isinstance(v, str) and isinstance(rhs, str) and rhs.lower() in v.lower()
    if op == "startswith":
        return isinstance(v, str) and isinstance(rhs, str) and v.lower().startswith(rhs.lower())
    if op == "endswith":
        return isinstance(v, str) and isinstance(rhs, str) and v.lower().endswith(rhs.lower())
    # Numeric / equality comparisons
    if op == "=":
        if isinstance(v, str) and isinstance(rhs, str):
            return v.lower() == rhs.lower()
        return _coerce(v) == _coerce(rhs)
    if op == "!=":
        if isinstance(v, str) and isinstance(rhs, str):
            return v.lower() != rhs.lower()
        return _coerce(v) != _coerce(rhs)
    a, b = _coerce(v), _coerce(rhs)
    if a is None or b is None:
        return False
    if op == ">":
        return a > b
    if op == ">=":
        return a >= b
    if op == "<":
        return a < b
    if op == "<=":
        return a <= b
    return False


def _coerce(v: Any) -> float | str | None:
    """Coerce to float for numeric comparison; fall through to string."""
    if v is None:
        return None
    if isinstance(v, bool):
        return 1.0 if v else 0.0
    if isinstance(v, (int, float)):
        return float(v)
    if hasattr(v, "toordinal"):
        return float(v.toordinal())
    if isinstance(v, str):
        try:
            return float(v.replace(",", ""))
        except ValueError:
            return v
    return None
