# Architecture

## Product principles

1. **No hallucinated numbers.** Every number, percentage, currency value, and cell reference in an answer must be traceable to a tool call in the same turn. Unverifiable claims are stripped or replaced with an honest "I don't know" partial response.
2. **Deterministic where possible, LLM only where reasoning genuinely differs.** Parsing, dependency graph, audit findings, what-if recalculation, and citation verification are code. Planning, formula narration, and cross-sheet comparison are the LLM.
3. **Akash's production wrapper + Rosetta's grounded core.** Auth (JWT + Google OAuth), Postgres persistence, Redis cache, Qdrant embeddings, upload pipeline, and UI are Akash's. Query→answer logic is Rosetta's.

## Request lifecycle

### Upload path (one-time per workbook)

```
POST /api/v1/data-sources/upload  (multipart .xlsx)
  → DataSourceService.upload()  — save file, create DataSource row
  → Background task:
      orchestrator.process_workbook()
        → extractor:  parse cells + colors + merged regions
        → mapper:     build semantic schema (sheet purposes, columns, formulas)
        → enricher:   workbook purpose, domain, suggested questions
      KnowledgeBaseService.index_data_source()
        → chunk_generator: 50–100 semantic chunks per workbook
        → OpenAI text-embedding-3-small → Qdrant `excel_knowledge` collection
      ExcelSchema row written to Postgres
```

### Q&A path (every question)

```
POST /api/v1/excel-agent/data-sources/{id}/ask
  → ExcelAgentService.ask_question()
      • Authn → authorized user
      • Load existing Conversation or create new
      • Persist user ConversationMessage
      • Create QueryHistory row

      ┌── Rosetta integration point ───────────────────────┐
      │                                                     │
      │  wb = parse_workbook(data_source.stored_file_path)  │
      │  wb.findings = audit_workbook(wb)                   │
      │  state = load_state(conversation)  # from Postgres  │
      │                                                     │
      │  result = await coordinator.answer(                 │
      │      wb, state, question,                           │
      │      user_id=..., data_source_id=...,               │
      │  )                                                   │
      │                                                     │
      │  persist_state(state, conversation) # back to Postgres
      │                                                     │
      │  adapted = bridge.coordinator_to_service_result(    │
      │      result,                                         │
      │      input_tokens, output_tokens, total_cost,       │
      │  )                                                   │
      │                                                     │
      └─────────────────────────────────────────────────────┘

      • Record LLMUsage row (provider=anthropic, real tokens, real cost)
      • Persist assistant ConversationMessage
      • Update QueryHistory (success, answer, iterations)
      • Return AskQuestionResponse (+ trace/audit_status/evidence_refs)
```

## Rosetta coordinator

### Control flow

```
coordinator.answer(wb, state, message):
  1. Append user message to state
  2. Check answer_cache (scenario-aware). Hit → return cached.
  3. Build Claude messages: prior turns + context line (active_entity + scenario_overrides)
  4. Start tool-calling loop (max 10 turns):
       Claude.messages.create(tools=[...], temperature=0)
         ↓
       stop_reason == "tool_use"?
         yes → for each tool_use block:
                  await execute_tool(wb, name, input, user_id, data_source_id)
                  log tool call to state.tool_call_log
                append tool_result, loop
         no  → extract final text answer, break
  5. Run citation auditor over final text
       audit failed:
         first failure  → append violation list as user message, retry (max 1)
         second failure → build partial "I don't know" response
  6. Extract active_entity from final text, update state
  7. Cache successful answers
  8. Return { answer, trace, evidence, audit_status, tokens, ... }
```

### Tools (deterministic)

All tools are pure Python, called via `execute_tool()`. 11 tools total:

| Tool | Purpose |
|---|---|
| `get_workbook_summary` | Sheet counts, named range count, finding counts, circular ref flag |
| `list_sheets` | Per-sheet row/col counts + structural regions + hidden status |
| `list_named_ranges` | All named ranges with resolved refs + current values |
| `get_cell` | Value, formula, dependencies, semantic label of a specific cell |
| `find_cells` | Three-tier search: exact → keyword → semantic (Qdrant) |
| `backward_trace` | Recursive calculation tree from a target cell |
| `forward_impact` | What-depends-on-this list, grouped by sheet |
| `resolve_named_range` | Named range → target cells + current value |
| `list_findings` | Audit results (stale, circular, hardcoded, volatile, hidden, broken) |
| `what_if` | Single-variable scenario recalc |
| `scenario_recalc` | Multi-variable scenario recalc composable with state.scenario_overrides |

### Three-tier `find_cells`

1. **Exact** — canonical cell ref (`P&L Summary!G32`) or exact named range name
2. **Keyword** — case-insensitive substring match on `cell.semantic_label`, seeded with `CANON_ALIASES`
3. **Semantic** — query Akash's `excel_knowledge` Qdrant collection (OpenAI embeddings), filtered by `user_id + data_source_id`, score threshold 0.5

In `auto` mode, tiers cascade in order and stop at first non-empty result.

### Specialists

One specialist active in v2A: **FormulaExplainer** (`core/rosetta/specialists/formula_explainer.py`).

- Input: a backward-trace tree JSON + original question
- Output: grounded prose explanation
- System prompt: strict style contract (cite every number with its ref, resolve every named range by name+value, never invent)
- Single LLM call — recursion through the tree is expressed *in the prompt*, not via sub-agents
- Fallback: deterministic trace walk if `ANTHROPIC_API_KEY` is missing

Coordinator triggers FormulaExplainer by emitting `<<DELEGATE_FORMULA_EXPLAINER ref=Sheet!G32>>` in its answer text, which the host splices before audit.

## Citation auditor

Pure Python, no LLM. Extracts and verifies three claim types:

| Claim type | Extraction | Verification |
|---|---|---|
| Numbers | regex `\$?-?\d{1,3}(?:,\d{3})+(?:\.\d+)?%?\|\$?-?\d+(?:\.\d+)?%?` with date-masking first | Must appear in some tool output within floating-point tolerance; also checks percent↔fraction match (5.8% ↔ 0.058) |
| Cell refs | quoted `'Sheet Name'!A1`, simple `Sheet!A1`, or multi-word prose-embedded `P&L Summary!G32` | Must appear in tool output `ref` fields or `wb.cells` |
| Named ranges | whole-word match against `wb.named_ranges` | Must be in workbook's named ranges |
| Qualitative keywords (`stale`, `circular`, `hidden`, `volatile`, `hardcoded`, `deprecated`, `broken`) | word-boundary substring match | In assertive context: must have matching audit finding. In negation/interrogative context (`no stale`, `are there any`, `returned 0 findings`): passes freely |

**Retry-on-violation:** one retry with violation list injected as user message. Second failure → return partial answer with what *was* verified + explicit list of unverified items.

## Conversation state

Akash's `conversations` table extended with two columns:

| Column | Type | Purpose |
|---|---|---|
| `active_entity` | TEXT | Last cell ref or metric mentioned; used for follow-up resolution |
| `scenario_overrides` | JSONB | What-if overrides stack (e.g. `{"FloorPlanRate": 0.07}`) |

Messages live in his existing `conversation_messages` table — unchanged. Rosetta's `load_state()` and `persist_state()` bridge these to the in-memory `ConversationState` dataclass used during a turn.

**Answer cache** is in-memory only (`_ANSWER_CACHES: dict[conversation_id, dict[question_hash, CachedAnswer]]`). Deliberately not persisted — cache miss on restart is cheap, and Postgres is the wrong storage for per-question hot cache.

## LLM usage & cost

Every coordinator turn records an `LLMUsage` row:

- `provider`: `anthropic`
- `model`: `claude-sonnet-4-5` (configurable via `ROSETTA_MODEL`)
- `input_tokens` / `output_tokens`: real counts from Claude API `usage` field
- `input_cost_usd` / `output_cost_usd` / `total_cost_usd`: computed in `core/rosetta/pricing.py`
- `context`: `{data_source_id, conversation_id, excel_schema_id, query_id, audit_status, tool_calls}`

Pricing for Sonnet 4.5: `$3/M input, $15/M output`.

## Upload-pipeline (Akash's original)

Retained unchanged. Lives in `core/agents/`:

- `base.py` — shared `AgentResult` + `BaseAgent`
- `extractor.py` — openpyxl structural extraction
- `mapper.py` — semantic schema builder (LLM-assisted)
- `semantic_enricher.py` — domain + metrics + suggested questions
- `orchestrator.py` — coordinates the pipeline

Files NO LONGER present (removed in v2A):

- `executor.py` — code-gen agent (CodeExecutorAgent)
- `token_tracker.py` — its estimates were replaced with real Anthropic token counts via `core/rosetta/pricing.py`

`orchestrator.ask_question()` still exists for backwards compat but raises `NotImplementedError` pointing callers at `ExcelAgentService.ask_question()`.

## What remains for future work

Not in v2A; tracked for v3+:

- **Pivot table introspection** — `list_pivots` tool + UI rendering
- **Version diff** — compare workbooks across ingests
- **Compute-aggregate tools** — `mean`, `argmax`, `top_n`, etc. to close the analytics gap without code-gen
- **Audit finding display in UI** — surface `trace`, `audit_status`, `evidence_refs` (already in API response, UI ignores them today)
- **Voyage AI embeddings** — stronger semantic retrieval
- **Fine-tuned coordinator model** — latency/cost if scale matters

## Pointers

- FastAPI app factory: `core/server.py`
- Routes: `core/api/v1/routes/`
- Service entry: `core/services/excel_agent.py::ExcelAgentService.ask_question`
- Rosetta entry: `core/rosetta/coordinator.py::answer`
- Tools: `core/rosetta/tools.py::execute_tool`
- Auditor: `core/rosetta/auditor.py::audit`
- Bridge: `core/rosetta/bridge.py::coordinator_to_service_result`
- Frontend API client: `ui/src/api/excelAgent.ts`
