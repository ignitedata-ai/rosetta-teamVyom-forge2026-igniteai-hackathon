"""Rosetta — grounded Excel Q&A coordinator.

This package was integrated from a standalone project. Public entry points:
  - coordinator.answer(wb, state, message) -> dict
  - parser.parse_workbook(path) -> WorkbookModel
  - audit.audit_workbook(wb) -> list[AuditFinding]
  - tools.execute_tool(wb, name, args) -> dict
  - bridge.to_ask_question_response(result, ...) -> his response shape
"""
