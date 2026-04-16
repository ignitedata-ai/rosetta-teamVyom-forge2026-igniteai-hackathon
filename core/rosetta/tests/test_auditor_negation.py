"""Unit tests for the negation-handling fix in the citation auditor.

Regression test for Q4 behavior: 'Are there any stale assumptions? No.' should
PASS audit, because 'stale' appears in a negation / interrogative context.
"""

from core.rosetta.auditor import _is_non_assertive, audit
from core.rosetta.models import (
    AuditFinding,
    DependencyGraphSummary,
    NamedRangeModel,
    SheetModel,
    WorkbookModel,
)


def _empty_wb() -> WorkbookModel:
    return WorkbookModel(
        workbook_id="wb_neg",
        filename="test.xlsx",
        sheets=[SheetModel(name="P&L Summary")],
        named_ranges=[],
        cells={},
        graph_summary=DependencyGraphSummary(total_formula_cells=0, max_depth=0, cross_sheet_edges=0),
        findings=[],  # NO stale findings — the tricky case
    )


# --- Helper unit tests ---


def test_is_non_assertive_negation():
    assert _is_non_assertive("there are no stale assumptions in this workbook")
    assert _is_non_assertive("this workbook doesn't have any hardcoded cells")
    assert _is_non_assertive("the file is not stale")
    assert _is_non_assertive("none of the formulas are circular")
    assert _is_non_assertive("the workbook is clean and has no hidden sheets")


def test_is_non_assertive_interrogative():
    assert _is_non_assertive("are there any stale assumptions?")
    assert _is_non_assertive("is the model using volatile functions?")
    assert _is_non_assertive("do any of the formulas contain circular references")


def test_is_non_assertive_rejects_assertive():
    assert not _is_non_assertive("the floorplanrate is stale")
    assert not _is_non_assertive("this assumption is hardcoded")
    assert not _is_non_assertive("the formula contains volatile functions")


# --- Full audit tests ---


def test_no_stale_answer_passes_audit():
    """Regression: 'No, there are no stale assumptions' must pass."""
    wb = _empty_wb()
    answer = "No, there are no stale assumptions in this workbook."
    result = audit(answer, [], wb)
    assert result.status == "passed", f"Got violations: {result.violations}"


def test_interrogative_echo_passes_audit():
    """LLM echoing the question 'Are there any stale...' must pass."""
    wb = _empty_wb()
    answer = "Are there any stale assumptions? I did not find any."
    result = audit(answer, [], wb)
    assert result.status == "passed", f"Got violations: {result.violations}"


def test_assertive_stale_still_blocked():
    """'The FloorPlanRate is stale' with no finding should still fail."""
    wb = _empty_wb()
    answer = "The FloorPlanRate is stale and was last updated in 2023."
    result = audit(answer, [], wb)
    assert result.status == "failed"
    assert any("stale" in v.lower() for v in result.violations)


def test_assertive_stale_with_finding_passes():
    """'The FloorPlanRate is stale' WITH a matching finding should pass."""
    wb = _empty_wb()
    wb.named_ranges = [
        NamedRangeModel(
            name="FloorPlanRate",
            scope="workbook",
            raw_value="Assumptions!$B$2",
            resolved_refs=["Assumptions!B2"],
            current_value=0.058,
        ),
    ]
    wb.findings = [
        AuditFinding(
            severity="warning",
            category="stale_assumption",
            message="FloorPlanRate last updated 2023",
        )
    ]
    answer = "The FloorPlanRate is stale."
    result = audit(answer, [], wb)
    assert result.status == "passed", f"Got violations: {result.violations}"


def test_compound_identifier_not_flagged_as_claim():
    """'stale' inside 'stale_assumption' (category name) is NOT a claim."""
    wb = _empty_wb()
    answer = "The audit returned 0 findings in the stale_assumption category."
    result = audit(answer, [], wb)
    assert result.status == "passed", f"Got violations: {result.violations}"


def test_zero_findings_reads_as_negation():
    """'returned 0 findings' should be treated as negation."""
    wb = _empty_wb()
    answer = "We found 0 stale assumptions in the workbook."
    result = audit(answer, [], wb)
    assert result.status == "passed", f"Got violations: {result.violations}"


def test_mixed_negation_and_assertion():
    """If one sentence is negated and another is an unbacked assertion,
    the assertion still fails.
    """
    wb = _empty_wb()
    answer = "There are no hidden sheets in this workbook. However, the FloorPlanRate is stale."
    result = audit(answer, [], wb)
    assert result.status == "failed"
    # "hidden" should be OK (negated); "stale" should fail (assertive, no finding)
    stale_violation = any("stale" in v.lower() for v in result.violations)
    hidden_violation = any("hidden" in v.lower() for v in result.violations)
    assert stale_violation, "Expected 'stale' violation"
    assert not hidden_violation, "'hidden' should have passed (negated)"


if __name__ == "__main__":
    import sys

    passed = 0
    failed = 0
    for name in list(globals()):
        if name.startswith("test_"):
            try:
                globals()[name]()
                print(f"  ✓ {name}")
                passed += 1
            except AssertionError as e:
                print(f"  ✗ {name}: {e}")
                failed += 1
            except Exception as e:
                print(f"  ✗ {name}: {type(e).__name__}: {e}")
                failed += 1
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(0 if failed == 0 else 1)
