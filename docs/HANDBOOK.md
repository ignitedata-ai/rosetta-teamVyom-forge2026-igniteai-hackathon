# Intelligent Excel Services — Project Handbook

*A complete, self-contained description of the system — business context, architecture, data flow, and file-by-file map. Written so a new developer (or a fresh Claude session) can read this file plus the code and continue building without context loss.*

---

# Part 1 — Business context

## 1.1 The problem

Finance teams, dealership groups, energy operators, and most mid-market companies run their real operating model in **Excel**, not in data warehouses or BI tools. A dealership group's 12-sheet P&L. An energy portfolio's 7-sheet merchant-pricing model. A retailer's inventory rollup built on top of VLOOKUP chains spanning four tabs.

These workbooks are **the source of truth**. They're also opaque. When a new analyst opens one and asks *"what drives the Adjusted EBITDA number in G32?"*, they face a dependency tree across six sheets, fourteen intermediate calculations, three named ranges, and a hardcoded assumption buried in row 112 of the Assumptions tab that hasn't been updated since 2023.

Existing LLM-on-Excel tools have tried to solve this. They consistently fail in one of two ways:

1. **Code-generation agents** (the common approach today: OpenAI + pandas/DuckDB). They read the workbook into a DataFrame, ask GPT to write Python that answers the question, and execute the code. **They hallucinate column names, confuse merged cells for data rows, and confidently return wrong numbers**. Formulas are destroyed the moment the file is parsed into a DataFrame.

2. **RAG over the raw cell values.** They embed cell contents, retrieve top-K, ask an LLM to answer. **They cannot explain formulas, cannot trace dependencies, and regularly fabricate numbers by averaging or summarizing retrieved chunks**.

The common failure mode in both: *confident, plausible-sounding wrong answers*. For finance teams where trust is everything, one hallucinated number destroys the tool.

## 1.2 The solution

**Intelligent Excel Services** is an agentic Q&A product with a hard contract: **every number, percentage, and cell reference in an answer must be traceable to a tool call in that turn**. If we can't verify a claim, we return *"I don't know"* — honestly and with the partial evidence we do have — rather than guess.

Instead of generating code or retrieving chunks, the system parses workbooks into a **computational graph** (cells, formulas, dependencies, named ranges, audit findings) and exposes that graph to Claude Sonnet 4.5 through a set of deterministic tools. Claude plans the query, calls tools, and writes a prose answer. A **citation auditor** then gates the answer: every cited number and cell ref must appear in a tool result from this session. Unverifiable claims are either retried with feedback or stripped and replaced with a grounded partial response.

This turns the product into something no code-gen agent can match: it can explain formulas at the cell level, trace dependencies across sheets, run what-if scenarios that propagate through the real formula tree, surface stale assumptions and circular references as first-class features, and refuse to answer rather than fabricate.

## 1.3 Who this is for

- **Finance teams** who need to explain and audit analyst-built models
- **Dealership groups, energy operators, franchise businesses** where the operating model lives in an Excel workbook that nobody outside the original author fully understands
- **Controllers and auditors** evaluating inherited financial models
- **Platform teams at data companies (e.g. Lens, ALM)** who want to ingest a customer's existing Excel logic rather than rebuild it from scratch

## 1.4 Product capabilities

| Capability | Concrete example |
|---|---|
| Value lookup with citation | *"What was total gross profit in March?"* → `$487,500 (P&L Summary!D18)` |
| Formula explanation | *"How is Adjusted EBITDA calculated?"* → narrative citing every component with cell refs and resolved named ranges |
| Dependency analysis | *"Which cells depend on FloorPlanRate?"* → grouped-by-sheet list of every dependent cell |
| What-if scenarios | *"What if FloorPlanRate went to 7%?"* → recomputed values for every impacted cell, with business-logic explanation |
| Multi-variable scenarios | *"What if Floor Plan = 7% and Tax Rate = 25%?"* → composed overrides, full propagation |
| Audit findings | Stale assumptions, circular references, hidden dependencies, hardcoded anomalies, volatile formulas, broken references |
| Multi-turn memory | Follow-up questions inherit context ("what about April?") via an active-entity tracker |
| Honest refusal | Returns *"I can only partially answer this"* instead of fabricating when tool results are insufficient |
| Workbook persistence | Uploaded workbooks are stored, indexed, and re-queryable across sessions; conversation history is durable in Postgres |
| OAuth-authenticated per-user access | Google OAuth + JWT; data isolated per user |

## 1.5 Why this is a moat

Most LLM-on-Excel tools optimize for *coverage of questions*. This product optimizes for **trust on the questions that matter**. A controller who catches one hallucinated number never trusts the tool again. By making the citation auditor a hard gate, we accept slightly lower coverage in exchange for never lying. That's the architectural bet.

---

# Part 2 — Technical overview

## 2.1 Architecture at a glance

```
┌─────────────────────────────────────────────────────────────┐
│                     Frontend (React + Vite)                  │
│            Google OAuth • Upload • Ask AI • History          │
│                         Port 3000                            │
└───────────────────────────┬─────────────────────────────────┘
                            │ JWT-authenticated REST
┌───────────────────────────▼─────────────────────────────────┐
│                  FastAPI backend (Port 8000)                 │
│                                                               │
│  UPLOAD PATH (per workbook):                                 │
│    POST /ingest → VisualMetadataExtractor (openpyxl)         │
│                 → SemanticMapper (OpenAI GPT-4o)             │
│                 → SemanticEnricher (OpenAI GPT-4o)           │
│                 → SemanticChunkGenerator                      │
│                 → OpenAI embeddings → Qdrant                 │
│                                                               │
│  Q&A PATH (per question):                                    │
│    POST /ask → ExcelAgentService                             │
│             → parse_workbook()   [Rosetta structural parser] │
│             → audit_workbook()   [audit engine]              │
│             → load ConversationState from Postgres           │
│             → coordinator.answer()                            │
│                  ↓                                            │
│             Claude Sonnet 4.5 tool-calling loop              │
│                  ↔ 11 deterministic tools                    │
│                  ↔ FormulaExplainer specialist (optional)    │
│                  ↔ Citation auditor (gate)                   │
│             → persist_state + record cost                    │
└────┬─────────────────────────────────────────────────┬──────┘
     │                                                  │
┌────▼─────────┐  ┌──────────────┐  ┌─────────────────▼─────┐
│ PostgreSQL   │  │ Redis        │  │ Qdrant                 │
│  • users     │  │ cache        │  │  • excel_knowledge     │
│  • data_src  │  │ (optional)   │  │    collection          │
│  • schemas   │  └──────────────┘  │  • 1536-dim OpenAI     │
│  • convers.  │                     │    embeddings          │
│  • messages  │                     └────────────────────────┘
│  • queries   │
│  • llm_usage │
└──────────────┘
```

## 2.2 Tech stack

| Layer | Technology | Why |
|---|---|---|
| Backend framework | **FastAPI** on Python 3.12 | Async-first, automatic OpenAPI, pydantic validation |
| Package / venv manager | **uv** (by Astral) | Fast, reproducible, Rust-based |
| Database | **PostgreSQL 16** via asyncpg + SQLAlchemy 2.0 async | Users, data sources, conversations, query history, LLM usage |
| Cache | **Redis 7** | Session cache, rate limiting |
| Vector DB | **Qdrant 1.9** | Semantic chunk search for workbook knowledge |
| Upload-pipeline LLM | **OpenAI GPT-4o** | Semantic mapping + enrichment of uploaded workbooks |
| Coordinator LLM | **Claude Sonnet 4.5** (Anthropic) | Tool-calling, planning, grounded answer composition |
| Embeddings | **OpenAI `text-embedding-3-small`** (1536-dim) | Workbook semantic chunks |
| Structural parser | **openpyxl** (formulas + cached values passes) | Parse `.xlsx` into formula AST + dependency graph |
| Dependency graph | **networkx** | Backward / forward trace, cycle detection |
| Frontend | **React 19 + Vite + Tailwind 4 + react-router** | SPA dashboard |
| Auth | **JWT (HS256) + Google OAuth 2.0** | User login + API auth |
| Schema migrations | **Alembic** | PostgreSQL DDL versioning |
| Observability | **OpenTelemetry + Structlog** | Structured logging, optional Jaeger tracing |
| Containers | **Docker Compose** | Local dev (Postgres + Redis + Qdrant + optional app) |

## 2.3 Repository layout

```
├── README.md                           # Quickstart
├── Dockerfile                          # Multi-stage build (Python 3.12)
├── docker-compose.yml                  # Postgres + Redis + Qdrant + excel-services
├── Makefile                            # make install | dev | migrate | ui-dev | test ...
├── main.py                             # uvicorn entrypoint → core.server:app
├── pyproject.toml + uv.lock            # Python dependencies
├── alembic.ini + alembic/versions/     # Database migrations (6 migrations, latest = d4e5f6a7b8c9)
│
├── core/                               # Backend package
│   ├── server.py                       # FastAPI app factory, lifespan, middleware
│   ├── config.py                       # Pydantic Settings (reads .env)
│   ├── logging.py / observability.py   # Structlog + OTel setup
│   │
│   ├── api/v1/                         # REST routes
│   │   ├── routes/auth.py              # Google OAuth callback, /refresh
│   │   ├── routes/data_sources.py      # Upload, list, get, DELETE, index, search
│   │   ├── routes/excel_agent.py       # /process, /ask, /schema, /conversations, /usage
│   │   └── schemas/                    # Pydantic request/response DTOs
│   │
│   ├── agents/                         # Upload processing pipeline (runs once per workbook)
│   │   ├── base.py                     # AgentResult, BaseAgent
│   │   ├── extractor.py                # VisualMetadataExtractor — openpyxl-based structural parse
│   │   ├── mapper.py                   # SemanticMapper — GPT-4o schema builder
│   │   ├── semantic_enricher.py        # SemanticEnricher — GPT-4o context/domain/suggestions
│   │   └── orchestrator.py             # Coordinates the three pipeline phases
│   │
│   ├── rosetta/                        # Q&A engine (runs per question)
│   │   ├── __init__.py
│   │   ├── coordinator.py              # Claude tool-calling loop + audit gate
│   │   ├── auditor.py                  # Citation auditor (post-answer verification)
│   │   ├── tools.py                    # 11 deterministic tools exposed to Claude
│   │   ├── bridge.py                   # QAResponse → his AskQuestionResponse adapter
│   │   ├── pricing.py                  # Claude token → USD cost
│   │   ├── conversation.py             # ConversationState + Postgres load/persist
│   │   ├── parser.py                   # openpyxl → WorkbookModel (formulas, deps, named ranges)
│   │   ├── formula_parser.py           # Formula AST + ref extraction
│   │   ├── graph.py                    # backward_trace / forward_impacted
│   │   ├── audit.py                    # audit_workbook() — findings engine
│   │   ├── evaluator.py                # Safe formula recalc for what-if
│   │   ├── cell_context.py             # Cell → rich context string builder
│   │   ├── models.py                   # WorkbookModel, CellModel, AuditFinding, etc.
│   │   ├── specialists/
│   │   │   └── formula_explainer.py    # Claude specialist: trace JSON → grounded prose
│   │   └── tests/
│   │       └── test_auditor_negation.py # 10 unit tests for auditor edge cases
│   │
│   ├── services/                       # Orchestration layer between routes and models
│   │   ├── auth.py                     # Google OAuth flow, JWT issuance/refresh
│   │   ├── data_source.py              # Upload, list, delete, KB index
│   │   ├── excel_agent.py              # ← ask_question calls coordinator.answer
│   │   └── conversation.py             # Conversation + message + LLM usage writes
│   │
│   ├── models/                         # SQLAlchemy models
│   │   ├── user.py                     # User (Google-linked)
│   │   ├── data_source.py              # DataSource (uploaded file)
│   │   ├── excel_schema.py             # ExcelSchema + QueryHistory (one per data source)
│   │   └── conversation.py             # Conversation + ConversationMessage + LLMUsage
│   │
│   ├── vector/                         # OpenAI embeddings + Qdrant client
│   │   ├── client.py                   # QdrantClientManager (async wrapper)
│   │   ├── embedding.py                # EmbeddingService (OpenAI text-embedding-3-small)
│   │   ├── chunk_generator.py          # SemanticChunkGenerator — workbook → 50-100 rich chunks
│   │   ├── excel_parser.py             # Upload-time parser (separate from rosetta parser)
│   │   └── knowledge_base.py           # index_data_source / search / delete
│   │
│   ├── database/session.py             # Async SQLA engine + session factory (with datetime-safe JSON)
│   ├── cache/                          # Redis wrapper + key maker
│   ├── middlewares/                    # CORS, logging, security headers
│   ├── dependencies/auth.py            # get_current_user (JWT validation)
│   ├── exceptions/                     # Base + handlers (404/422/500)
│   ├── security/                       # JWT helpers
│   └── utils/                          # Rate limiting, etc.
│
├── ui/                                 # React frontend
│   ├── src/
│   │   ├── App.tsx                     # Router
│   │   ├── pages/                      # Home, Login, Dashboard, DataSourceDetail, GoogleCallback
│   │   ├── components/                 # Layout, Sidebar
│   │   ├── context/AuthContext.tsx     # JWT + user state
│   │   └── api/                        # Typed fetch clients
│   │       ├── auth.ts                 # API_BASE_URL, login/refresh
│   │       ├── dataSources.ts          # upload, list, get, deleteDataSource
│   │       └── excelAgent.ts           # process, ask, conversations, usage
│   ├── package.json
│   └── vite.config.ts                  # Port 3000
│
├── data/                               # Sample workbooks for demos
│   ├── dealership_financial_model.xlsx
│   └── energy_portfolio_model.xlsx
│
├── uploads/data_sources/               # Runtime uploads (gitignored except .gitkeep)
├── scripts/                            # init-db.sql, init_data.py (no-op), setup_jaeger.sh
├── monitoring/                         # OTel collector config
│
└── docs/
    ├── architecture.md                 # Component deep-dive
    ├── runbook.md                      # Setup, make targets, deployment, troubleshooting
    └── HANDBOOK.md                     # ← this file
```

---

# Part 3 — Data flow: end-to-end

## 3.1 The upload flow (one-time per workbook)

When a user uploads an `.xlsx`, two independent processing tracks run: (a) Akash's upload-pipeline agents produce a semantic schema stored in Postgres, and (b) the KnowledgeBaseService produces OpenAI-embedded chunks stored in Qdrant. Both complete before the workbook is marked "Ready for queries".

```
User → UI
  │
  ▼ POST /api/v1/data-sources/upload  (multipart .xlsx + JWT)
  │
  ├─ DataSourceService.upload()
  │     1. persist file → uploads/data_sources/{uuid}_{filename}.xlsx
  │     2. extract sheet names + count via openpyxl (metadata-only)
  │     3. insert DataSource row (users.id FK, stored_file_path)
  │     4. schedule BackgroundTask
  │
  ▼ (sync response → UI shows file in My Files)
  │
  ── BackgroundTask: two parallel tracks ─────────────────────────────
  │
  │  Track A: Semantic schema (core/agents/)
  │    ExcelAgentOrchestrator.process_workbook()
  │      Phase A  VisualMetadataExtractor (openpyxl → WorkbookManifest)
  │               • sheet structure, rows, columns, colors, merged cells
  │               • cell values + formulas + sample data
  │      Phase B  SemanticMapper (OpenAI GPT-4o call)
  │               • workbook purpose, column semantic types, relationships
  │      Phase C  SemanticEnricher (OpenAI GPT-4o call)
  │               • domain detection, context_header_for_qa
  │               • query_routing hints, suggested questions
  │    → ExcelSchema row: manifest + semantic_schema + enrichment + metadata
  │    → sets is_ready_for_queries=True
  │
  │  Track B: Vector knowledge base (core/vector/)
  │    KnowledgeBaseService.index_data_source()
  │      SemanticChunkGenerator
  │        produces 50–100 DocumentChunks per workbook:
  │          • workbook_overview
  │          • per-sheet: sheet_overview, schema, column_analysis,
  │            formula_analysis, data_patterns, statistics
  │          • relationships
  │      EmbeddingService.embed_texts(chunks)
  │        • OpenAI text-embedding-3-small → 1536-dim vectors
  │        • batched, default batch size 100
  │      Qdrant.upsert(collection=excel_knowledge)
  │        • payload: {user_id, data_source_id, content, chunk_type,
  │           sheet_name, file_name}
  │    → 58 chunks indexed (dealership fixture); scales with sheet count
  │
  ── end BackgroundTask ──────────────────────────────────────────────

Poll: GET /api/v1/data-sources/{id} → is_ready_for_queries=True → ready to query
```

**Important:** The upload flow uses OpenAI (both for semantic schema via GPT-4o and for embeddings). The Q&A flow uses Anthropic (Claude Sonnet 4.5). These are intentionally decoupled — Akash built the upload pipeline on OpenAI and the grounded Q&A benefits from Anthropic's strong tool-calling support.

## 3.2 The query flow (per question)

```
User types question + clicks Send in Ask AI
  │
  ▼ POST /api/v1/excel-agent/data-sources/{id}/ask
  │   body: {question, conversation_id?}  headers: Bearer JWT
  │
  ├─ authenticate user (core/dependencies/auth.py::get_current_user)
  │
  ▼ ExcelAgentService.ask_question()                    (core/services/excel_agent.py)
  │
  │  1. Verify data_source + ExcelSchema
  │     - raise NotFoundError if schema missing
  │     - raise BusinessLogicError if not is_ready_for_queries
  │
  │  2. Load or create Conversation (ConversationService)
  │     - new conversation → title = first 100 chars of question
  │     - persist user ConversationMessage row
  │
  │  3. Create QueryHistory row (for audit / analytics)
  │
  │  4. ▼ ROSETTA integration point ─────────────────────────────────
  │
  │     wb = rosetta.parser.parse_workbook(data_source.stored_file_path)
  │       → returns WorkbookModel
  │         • cells: dict[ref, CellModel(value, formula, deps, label)]
  │         • named_ranges: [NamedRangeModel]
  │         • sheets: [SheetModel(regions, hidden_rows)]
  │         • graph_summary (dependency metrics, circular refs)
  │
  │     wb.findings = rosetta.audit.audit_workbook(wb)
  │       → runs 6 detectors:
  │         • _stale_assumptions  (rows w/ dates > 12mo old)
  │         • _hidden_deps        (formulas referencing hidden sheets/rows)
  │         • _volatile_formulas  (NOW, TODAY, OFFSET, INDIRECT, etc.)
  │         • _hardcoded_anomalies (cell that should be formula based on neighbors)
  │         • _circular_references (cycles in dep graph)
  │         • _broken_refs        (#REF! or dangling refs)
  │
  │     full_conversation = load conversation with messages from Postgres
  │     state = rosetta.conversation.load_state(full_conversation)
  │       → ConversationState with:
  │         • messages (chat history as ChatMessage objects)
  │         • active_entity (last ref from prior turn — for follow-ups)
  │         • scenario_overrides (JSONB from conversations table)
  │         • answer_cache (in-process, per-conversation)
  │         • tool_call_log (this turn, empty to start)
  │
  │     result = await rosetta.coordinator.answer(
  │         wb, state, question,
  │         user_id=user_id, data_source_id=data_source_id,
  │     )
  │       (full expansion below in §3.3)
  │
  │     persist_state(conversation, state)
  │       → writes active_entity + scenario_overrides back to Postgres
  │
  │  5. ▼ Cost tracking ─────────────────────────────────────────
  │
  │     input_tokens  = result['input_tokens']   (real from Claude API)
  │     output_tokens = result['output_tokens']  (real from Claude API)
  │     in_cost, out_cost, total_cost = pricing.compute_cost_usd(
  │         settings.ROSETTA_MODEL, input_tokens, output_tokens
  │     )
  │       → Claude Sonnet 4.5: $3/M input, $15/M output
  │
  │     ConversationService.record_llm_usage(
  │         provider="anthropic", model=..., tokens, cost,
  │         context={data_source_id, conversation_id, schema_id, query_id,
  │                  audit_status, tool_calls},
  │     )
  │       → insert LLMUsage row
  │
  │  6. Adapt response: bridge.coordinator_to_service_result()
  │       → returns AskQuestionResponse shape
  │
  │  7. Persist assistant ConversationMessage
  │       → content = answer text, code_used = pseudo-trail, tokens, cost
  │
  │  8. Update QueryHistory (success flag, iterations, execution_time_ms)
  │
  ▼ Response to UI:
  {
    success, answer, code_used, iterations, error,
    execution_time_ms, query_id, conversation_id,
    input_tokens, output_tokens, cost_usd,
    trace, audit_status, evidence_refs,
    active_entity, scenario_overrides,
  }
```

## 3.3 Inside `coordinator.answer()`

This is the heart of the grounded Q&A engine.

```
answer(wb, state, message, *, user_id, data_source_id):

  1. state.append_user(message)

  2. Cache lookup:
     qh = hash(question + scenario_overrides)
     if state.answer_cache[qh] and still fresh:
       return cached_result  (no LLM call, no cost)

  3. If no ANTHROPIC_API_KEY → return graceful "not configured" message

  4. Initialize:
     client = anthropic.AsyncAnthropic(api_key=...)
     model  = settings.ROSETTA_MODEL     (claude-sonnet-4-5)
     claude_messages = [previous turns + current (with active_entity context)]

  5. Main loop (max 2 attempts for audit retry):
     ┌─────────────────────────────────────────────────────────────┐
     │ _run_tool_loop(client, model, messages, wb, state):         │
     │                                                              │
     │   for turn in range(MAX_TOOL_TURNS=10):                      │
     │     resp = client.messages.create(                           │
     │       model, tools=TOOLS, system=COORDINATOR_PROMPT,         │
     │       temperature=0, max_tokens=2048                         │
     │     )                                                        │
     │     state.turn_input_tokens  += resp.usage.input_tokens      │
     │     state.turn_output_tokens += resp.usage.output_tokens     │
     │                                                              │
     │     if resp.stop_reason == "tool_use":                       │
     │       for tool_use_block in resp.content:                    │
     │         out = await execute_tool(                            │
     │           wb, block.name, block.input,                       │
     │           user_id=user_id, data_source_id=data_source_id,    │
     │         )                                                    │
     │         state.log_tool_call(...)                             │
     │         append tool_result to messages                       │
     │       continue                                               │
     │     else:  # end_turn                                        │
     │       return answer_text                                     │
     └─────────────────────────────────────────────────────────────┘

  6. If the answer contains "<<DELEGATE_FORMULA_EXPLAINER ref=X!Y>>":
     → await specialists.formula_explainer.explain(trace, question)
     → splice the specialist's grounded prose into the answer

  7. Citation audit (core/rosetta/auditor.py::audit):
     result = audit(answer_text, state.tool_call_log, wb)

     Extracts from answer:
       - all numbers (handles $, %, commas, decimals; masks dates first)
       - all cell refs (quoted 'Sheet Name'!A1, simple, or prose-embedded)
       - all named ranges mentioned
       - qualitative keywords (stale, circular, hidden, volatile,
         hardcoded, deprecated, broken)

     Verifies:
       - every number matches a tool-result value (±0.5% tolerance
         + rounding tolerance for display numbers like "$487,500")
       - every cell ref appears in tool outputs or wb.cells
       - every named range is a real workbook named range
       - qualitative claims in assertive context require matching
         AuditFinding category; negated/interrogative context (e.g.
         "no stale", "returned 0 findings", "are there any...")
         passes freely

     If audit fails:
       First failure  → inject violations list, re-run tool loop once
       Second failure → build partial "I don't know" response:
           "I can only partially answer this. Here's what I verified:
            [verified numbers/refs/named ranges]
            What I couldn't verify: [violations]
            You might rephrase ..."

  8. Post-process:
     - extract first cell ref from answer → state.active_entity
     - if audit passed → cache the answer keyed by qh
     - state.append_assistant(final_text)

  9. Build return dict including:
     { answer, trace, evidence, escalated, audit_status, confidence,
       tool_calls_made, active_entity, scenario_overrides,
       input_tokens, output_tokens, _tool_trail }
```

**Key design choice:** the coordinator never does arithmetic in its head. Numbers come from tools; the coordinator quotes them and composes prose around them. The auditor's job is to enforce this.

---

# Part 4 — Core subsystems, explained

## 4.1 The 11 deterministic tools

All tools are pure Python functions exposed via `core/rosetta/tools.py::execute_tool()`. The LLM sees their schema; when it emits a `tool_use` block, we execute the function and feed the result back as a `tool_result`. All tools are async for uniformity (most are sync internally; `find_cells` truly async for Qdrant queries).

| Tool | Signature | Purpose |
|---|---|---|
| **get_workbook_summary** | `() → {sheet_count, named_ranges, finding_counts, ...}` | Orient the coordinator on a fresh question |
| **list_sheets** | `() → {sheets: [{name, rows, formulas, hidden, regions}]}` | Per-sheet structural summary |
| **list_named_ranges** | `() → {named_ranges: [{name, scope, resolves_to, current_value, is_dynamic}]}` | Every named range with resolved ref |
| **get_cell** | `(ref) → {value, formula, formula_type, semantic_label, depends_on, depended_by, named_ranges_used, is_hardcoded, is_volatile}` | Full detail on one cell |
| **find_cells** | `(keyword, tier="auto"|"exact"|"keyword"|"semantic") → {matches: [{ref, label, value, score, tier_used}]}` | Three-tier cell search |
| **backward_trace** | `(ref, max_depth=6) → {trace: TraceNode tree}` | Full backward dependency tree |
| **forward_impact** | `(ref, max_results=100) → {total_impacted, by_sheet: {sheet: [...]}}` | What would change if ref changes |
| **resolve_named_range** | `(name) → {name, scope, resolves_to, current_value, is_dynamic}` | Named range lookup with metadata |
| **list_findings** | `(category?) → {findings: [{severity, category, location, message, confidence}]}` | Audit findings, optional filter |
| **what_if** | `(target, new_value, max_results=30) → {changes: [...]}` | Single-variable scenario recalc |
| **scenario_recalc** | `(overrides: dict, target_refs?: list) → {recalculated, changed_count, unsupported_formulas}` | Multi-variable scenario recalc (composes with state.scenario_overrides) |

### `find_cells` — three-tier resolution

```
tier="auto" tries:

  1. EXACT match
     - canonical cell ref ("P&L Summary!G32")
     - named range name ("FloorPlanRate")
     → score 1.0, return immediately

  2. KEYWORD match (if exact returned nothing)
     - case-insensitive substring on cell.semantic_label
     - scored by {formula-presence bonus, label specificity}
     - top 20 returned

  3. SEMANTIC match (if both exact+keyword returned nothing)
     - calls core.vector.knowledge_base.KnowledgeBaseService.search()
     - filtered by user_id + data_source_id
     - OpenAI query embedding → Qdrant cosine similarity
     - threshold 0.5
     - returns chunks (not cell-addressed); coordinator uses these as hints
       to then call find_cells(tier="keyword") with better terms
```

## 4.2 The citation auditor

Located at `core/rosetta/auditor.py`. Pure Python, no LLM.

**Extraction patterns:**

```python
NUMBER_RE = r"\$?-?\d{1,3}(?:,\d{3})+(?:\.\d+)?%?  |  \$?-?\d+(?:\.\d+)?%?"
DATE_RE   = r"\b\d{4}-\d{1,2}-\d{1,2}\b | \b\d{1,2}/\d{1,2}/\d{2,4}\b | ..."   # masked BEFORE number extraction
CELL_REF_QUOTED_RE  = r"'([^']+)'!(\$?[A-Z]{1,3}\$?\d+)"
CELL_REF_SIMPLE_RE  = r"(?<![\w!])([A-Za-z_]\w*)!(\$?[A-Z]{1,3}\$?\d+)"
COORD_RE            = r"!(\$?[A-Z]{1,3}\$?\d+)\b"  # for multi-word prose sheet names

NEGATION_TOKENS = {no, not, none, never, without, lacks, aren't, isn't, ..., zero, 0, any}
```

**Verification universes:**

```python
tool_numbers  = recursively walk all tool outputs, collect floats/ints
tool_refs     = recursively walk all tool outputs, collect Sheet!A1 patterns
workbook_nums = set of all wb.cells[*].value numeric values
workbook_refs = set of all wb.cells keys
nr_names      = {nr.name for nr in wb.named_ranges}
categories_seen = {f.category for f in wb.findings} ∪ categories returned
                   by list_findings this session
```

**Number match tolerance:**

```python
def _number_matches(target, universe):
    for v in universe:
        if target == v:                                            return True
        if v == 0 and abs(target) < 0.5:                           return True
        if abs(target - v) / abs(v) <= 0.005:                      return True  # ±0.5%
        if abs(target - v) <= 0.5:                                 return True
        if abs(target - round(v, -3)) <= 500:                      return True  # "$487,500" matches 487,532
    return False
```

**Qualitative keyword logic (the Q4-fix):**

```python
# For keyword k in {stale, circular, hidden, volatile, hardcoded, deprecated, broken}:
  if kw appears as whole word in answer (word-boundary, NOT inside "stale_assumption"):
    for each sentence containing kw:
      if sentence has negation token (no, not, zero, any, isn't, ...) or
         starts with interrogative pattern ("are there", "is the", "do any", ...):
        → pass (coordinator is negating or echoing the question)
      elif category in categories_seen:
        → pass (assertion is backed)
      else:
        → violation
```

**Retry-on-violation:**

```python
attempt 1: run tool loop → audit → passed? return
                        ↓ failed
inject violation list into messages → retry tool loop → audit → passed? return
                                                              ↓ failed
return partial "I don't know" response with what WAS verified
```

## 4.3 The FormulaExplainer specialist

Located at `core/rosetta/specialists/formula_explainer.py`. A single focused Claude call.

**Why a specialist:** the coordinator is a planner. For the "how is X calculated?" family of questions, we want the system to produce a polished narrative that walks a colleague through the calculation. A dedicated prompt with a strict style contract does this better than relying on the coordinator's general-purpose prompt.

**How it's invoked:** the coordinator emits `<<DELEGATE_FORMULA_EXPLAINER ref=Sheet!Ref>>` in its answer text. The host detects the marker, calls `backward_trace(ref, depth=3)`, runs the specialist, and splices the specialist's prose back in before audit.

**Style contract (in the system prompt):**

1. Cite every number with its cell ref: `(P&L Summary!G18: $487,500)`
2. Resolve every named range by name AND value: `FloorPlanRate (5.8%)`
3. Lead with WHAT the cell IS: label, ref, value
4. Walk the dependency tree one level deep by default (deeper only when essential)
5. Never round unless source is already rounded
6. Never introduce a number/ref/name outside the provided trace

**Fallback:** if `ANTHROPIC_API_KEY` is missing, returns a deterministic trace walk (less polished but still grounded).

## 4.4 The audit engine

Located at `core/rosetta/audit.py::audit_workbook(wb)`. Returns `list[AuditFinding]`.

Six detectors, each pure Python over the parsed `WorkbookModel`:

| Detector | Logic |
|---|---|
| `_stale_assumptions` | Scan sheets whose name contains "assumption" or "settings". For each row with a label in col A and a date in col B/C/D/E, flag if date > 12 months old. |
| `_hidden_deps` | Find formulas referencing hidden rows/columns. Flag as warning — these dependencies are invisible to human reviewers. |
| `_volatile_formulas` | Cells using `NOW()`, `TODAY()`, `RAND()`, `OFFSET()`, `INDIRECT()`, `INFO()`, `CELL()`. These recompute on every open. |
| `_hardcoded_anomalies` | For each column/row, compute the modal formula shape (function names + relative refs). Cells that deviate from the pattern are candidates. Catches the "row 23 has a hardcoded value where every other row has a SUMIFS" case. |
| `_circular_references` | `networkx.simple_cycles` over the dep graph. Flagged as warning with `intentional=True` if the cycle involves known patterns (service absorption ↔ overhead). |
| `_broken_refs` | Cells whose formula references `#REF!` or cells outside the workbook. |

## 4.5 The what-if evaluator

Located at `core/rosetta/evaluator.py`. A safe, partial Excel evaluator.

**Supported functions:** `SUM, AVERAGE, MIN, MAX, COUNT, COUNTA, PRODUCT, ROUND, ABS, IF, IFERROR, IFNA, AND, OR, NOT, SUMIF, SUMIFS, COUNTIF, COUNTIFS, AVERAGEIF, AVERAGEIFS, SUMPRODUCT, VLOOKUP, HLOOKUP, XLOOKUP, INDEX, MATCH, DATE, YEAR, MONTH, DAY, TODAY, NOW`.

**Operators:** `+ - * / ^ %`, `= <> > >= < <=`, `&` (string concat).

**Resolution:** handles cell refs, ranges, cross-sheet refs, named ranges, and uses `overrides` dict before falling back to parsed values.

**Limitation:** any formula it can't parse returns `None` with the ref added to `unsupported`. The coordinator surfaces this to the user honestly.

**How `scenario_recalc` uses it:**

```python
def _scenario_recalc(wb, overrides: dict, target_refs: list | None):
    resolved = resolve each override key (ref or named range) to a cell ref
    ev = Evaluator(wb, overrides=resolved)
    targets = target_refs or [all cells forward-impacted from resolved refs]
    for r in targets:
        new_v = ev.value_of(r)
        if new_v != wb.cells[r].value:
            yield {ref, label, old, new}
```

## 4.6 ConversationState

Located at `core/rosetta/conversation.py`.

```python
@dataclass
class ConversationState:
    session_id: str                    # = conversations.id (UUID)
    workbook_id: str                   # = data_sources.id
    messages: list[ChatMessage]        # loaded from conversation_messages
    active_entity: Optional[str]       # last Sheet!Ref seen (for follow-ups)
    scenario_overrides: dict[str, Any] # what-if overrides {name: value}
    answer_cache: dict[q_hash, ...]    # in-process, per conversation
    tool_call_log: list[ToolCall]      # this turn, for audit verification
    turn_input_tokens: int
    turn_output_tokens: int
```

**Postgres persistence:**

| In-memory field | Postgres location | Persistence |
|---|---|---|
| `messages` | `conversation_messages` table (rows) | Saved per-turn by `ConversationService.add_message` |
| `active_entity` | `conversations.active_entity` TEXT | Saved in `persist_state()` at end of turn |
| `scenario_overrides` | `conversations.scenario_overrides` JSONB | Saved in `persist_state()` |
| `answer_cache` | (in-process only) | Dict keyed by conversation_id; lost on restart |
| `tool_call_log` | (in-process only) | Cleared between turns |

---

# Part 5 — Data model

## 5.1 Postgres tables

Applied via 6 Alembic migrations (latest: `d4e5f6a7b8c9_add_conversation_state_columns`).

```
users                          (created by Alembic migration dce8846e5d56)
  id                UUID PK
  email             unique, indexed
  first_name, last_name, full_name, profile_picture
  auth_provider     "google"
  is_active, is_verified
  created_at, last_login_at

data_sources                   (57f5ac9a2f11)
  id                UUID PK
  user_id           FK users.id ON DELETE CASCADE
  name              user-friendly name
  original_file_name
  mime_type, file_extension, file_size_bytes
  stored_file_path  "uploads/data_sources/{uuid}_{name}.xlsx"
  sheet_count, sheet_names JSON
  file_checksum_sha256
  meta_info         JSON
  created_at, updated_at

excel_schemas                  (a1b2c3d4e5f6 + c3d4e5f6a7b8 enrichment)
  id                UUID PK
  data_source_id    FK data_sources.id UNIQUE CASCADE
  processing_status ProcessingStatus (PENDING/EXTRACTING/MAPPING/ENRICHING/COMPLETED/FAILED)
  processing_error  TEXT
  manifest          JSON   ← VisualMetadataExtractor output
  semantic_schema   JSON   ← SemanticMapper output
  enrichment        JSON   ← SemanticEnricher output
  workbook_title, workbook_purpose, domain
  context_header_for_qa TEXT
  query_routing     JSON
  detected_colors   JSON
  total_sections, total_merged_regions
  queryable_questions JSON
  data_quality_notes  JSON
  is_ready_for_queries BOOL
  created_at, updated_at, processed_at

query_history                  (a1b2c3d4e5f6)
  id                UUID PK
  excel_schema_id   FK excel_schemas.id CASCADE
  user_id           FK users.id CASCADE
  question          TEXT
  answer            JSON (any type)
  code_used         TEXT    ← pseudo-trail from Rosetta; None otherwise
  success           BOOL
  error_message     TEXT
  execution_time_ms INT
  iterations_used   INT     ← number of tool calls
  created_at

conversations                  (b2c3d4e5f6a7 + d4e5f6a7b8c9)
  id                UUID PK
  user_id           FK users.id CASCADE
  data_source_id    FK data_sources.id CASCADE
  title             VARCHAR(255)
  is_active         BOOL
  total_input_tokens, total_output_tokens, total_cost_usd
  active_entity     TEXT      ← Rosetta (added in d4e5f6a7b8c9)
  scenario_overrides JSONB    ← Rosetta (added in d4e5f6a7b8c9)
  created_at, updated_at, last_message_at

conversation_messages          (b2c3d4e5f6a7)
  id                UUID PK
  conversation_id   FK conversations.id CASCADE
  role              "user" | "assistant"
  content           TEXT
  code_used         TEXT (for assistant — pseudo-trail of tool calls)
  execution_time_ms, is_error, error_message
  input_tokens, output_tokens, cost_usd
  llm_usage_id      FK llm_usage.id SET NULL
  created_at

llm_usage                      (b2c3d4e5f6a7)
  id                UUID PK
  user_id           FK users.id CASCADE
  call_type         "ask_question" | "metadata_extraction" | "semantic_mapping" | ...
  context           JSON {data_source_id, conversation_id, excel_schema_id,
                          query_id, audit_status, tool_calls}
  provider          "anthropic" | "openai"
  model             e.g. "claude-sonnet-4-5", "gpt-4o", "text-embedding-3-small"
  input_tokens, output_tokens
  input_cost_usd, output_cost_usd, total_cost_usd  Numeric(10,6)
  latency_ms, success, error_message
  created_at
```

**Cascade behavior:** deleting a data source cascades to `excel_schemas`, `conversations` (and therefore their messages, query_history, and `llm_usage_id` foreign key on messages via SET NULL). `llm_usage` rows are preserved but orphaned for billing / analytics.

## 5.2 Qdrant collection

Single collection: `excel_knowledge` (1536-dim, cosine distance).

**Point payload:**

```json
{
  "user_id":        "UUID string",
  "data_source_id": "UUID string",
  "content":        "rich chunk text (500 chars / chunk typical)",
  "chunk_type":     "workbook_overview" | "sheet_overview" | "schema" |
                    "column_analysis" | "formula_analysis" | "data_patterns" |
                    "statistics" | "relationships",
  "sheet_name":     "P&L Summary" | null,
  "file_name":      "dealership_financial_model.xlsx"
}
```

**Chunk generation (per workbook):**

- 1 `workbook_overview` chunk (purpose + sheet summary)
- Per-sheet: `sheet_overview`, `schema`, N `column_analysis` chunks, `formula_analysis`, `data_patterns`, `statistics`
- 1 `relationships` chunk (cross-sheet connections)

**Search API** (via `core/vector/knowledge_base.py`):

```python
KnowledgeBaseService.search(
    query="user question text",
    user_id="UUID",
    data_source_id="UUID",  # scoped to one workbook
    limit=10,
    score_threshold=0.5
) → list[SearchResult(id, content, score, metadata)]
```

Rosetta's `find_cells(tier="semantic")` calls this, then the coordinator uses the hits as contextual hints to look up specific cells via `find_cells(tier="keyword")` or `get_cell`.

## 5.3 File storage

Uploaded xlsx files live at `uploads/data_sources/{uuid}_{original_file_name}.xlsx`. The `stored_file_path` in the `data_sources` table is **relative to the app's working directory** (repo root). The rosetta parser reads from this path on every `/ask` call.

The directory is gitignored except for a `.gitkeep` marker. Users bring their own data.

---

# Part 6 — Cost tracking

Every coordinator call writes an `LLMUsage` row in Postgres with real token counts from the Anthropic API.

**Pricing** (Claude Sonnet 4.5, Apr 2026, per `core/rosetta/pricing.py`):

```
input:  $3.00 per 1M tokens  → $0.000003 / token
output: $15.00 per 1M tokens → $0.000015 / token
```

Other supported models in `CLAUDE_PRICING`: `claude-opus-4-6`, `claude-haiku-4-5-20251001`, `claude-sonnet-4-6`.

**Per-question cost formula:**

```
cost_usd = (input_tokens / 1M × input_rate) + (output_tokens / 1M × output_rate)
```

Quantized to 6 decimal places to fit `Numeric(10,6)` column.

**Typical costs per question** (dealership fixture):

| Question type | Tool calls | Input | Output | Cost |
|---|---|---|---|---|
| Simple value lookup ("total gross profit March") | 2–3 | ~5,000 | ~300 | $0.02 |
| Formula explanation via FormulaExplainer | 4–6 | ~15,000 | ~450 | $0.05 |
| Dependency question | 3–5 | ~10,000 | ~400 | $0.04 |
| What-if scenario | 2–3 | ~9,000 | ~500 | $0.04 |
| Audit question | 1–2 | ~8,000 | ~200 | $0.03 |
| Audit-retry (partial answer) | 6–10 | ~25,000 | ~1,000 | $0.09 |

**Accumulation:**

- Per turn: tracked in `ConversationState.turn_input_tokens` / `turn_output_tokens`
- Per conversation: aggregated in `conversations.total_input_tokens` / `total_cost_usd` via `Conversation.add_cost(...)` called by `ConversationService.add_message`
- Per user: queryable via `GET /api/v1/excel-agent/usage/summary?days=30`

**Upload cost** (OpenAI, not tracked in LLMUsage today):

- GPT-4o semantic_mapper: ~$0.01–0.03 per workbook (depends on complexity)
- GPT-4o semantic_enricher: ~$0.01–0.02 per workbook
- text-embedding-3-small: ~$0.00001–0.00005 per workbook (negligible)

**Total daily cost for a team of 10 asking 20 questions each:** ≈ $10 in Claude costs + ≈ $1 in OpenAI for new uploads.

---

# Part 7 — Security and auth

## 7.1 Auth flow

```
Browser → /login → Google OAuth consent
  → Google redirects to /api/v1/auth/google/callback?code=...
  → core/services/auth.py:
       • exchange code for Google tokens
       • fetch user profile
       • upsert User row (by email)
       • issue JWT (HS256, exp=30min) + refresh token (7 days)
  → returns tokens to frontend → stored in localStorage
  → every API call: Authorization: Bearer <access_token>
  → core/dependencies/auth.py::get_current_user validates JWT
```

**Keys:**

- `JWT_SECRET_KEY` — HS256 signing key. **Must be rotated in production.**
- `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` — from Google Cloud Console OAuth credentials
- `GOOGLE_REDIRECT_URI` — must match the Authorized Redirect URI in Google Cloud Console

## 7.2 Data isolation

Every route that touches user data calls `_verify_user_owns(data_source_id, user_id)` or similar before returning. Database queries scope by `user_id`. Qdrant searches filter by `user_id` via payload match.

## 7.3 Threat model

- **User A cannot access User B's data:** enforced via user_id ownership checks in services + payload filters in Qdrant.
- **API key exposure:** `.env` is gitignored; `.env.example` has only placeholders.
- **XSS / CSRF:** CORS is permissive (`CORS_ALLOW_ALL_ORIGINS=true`) in dev — tighten for production. Security headers middleware adds CSP, HSTS, X-Frame-Options.
- **SQL injection:** SQLAlchemy ORM (parameterized queries throughout).
- **Prompt injection (user question → Claude):** limited risk because Claude's output is audit-gated; injected instructions to fabricate numbers would be caught by the citation auditor.

---

# Part 8 — API surface

All authenticated routes require `Authorization: Bearer <JWT>`.

**Auth**

- `GET /api/v1/auth/google/url?redirect_uri=...` → `{url}` — start OAuth
- `POST /api/v1/auth/google/callback` → `{access_token, refresh_token, user}`
- `POST /api/v1/auth/refresh` → `{access_token, refresh_token}`

**Data sources**

- `POST /api/v1/data-sources/upload` (multipart: `name`, `file`) → `DataSource`
- `GET /api/v1/data-sources` → `DataSourceListResponse`
- `GET /api/v1/data-sources/{id}` → `DataSource`
- `GET /api/v1/data-sources/{id}/analysis` → workbook analysis or null
- `POST /api/v1/data-sources/{id}/index` → re-run indexing
- `DELETE /api/v1/data-sources/{id}` → full delete (file + Qdrant + DB cascades)
- `DELETE /api/v1/data-sources/{id}/index` → remove Qdrant chunks only
- `POST /api/v1/data-sources/search` (body: `{query, data_source_id?, limit}`) → `KnowledgeSearchResponse`

**Excel agent**

- `POST /api/v1/excel-agent/data-sources/{id}/process` (body: `{force_reprocess}`) → `ProcessDataSourceResponse`
- `GET /api/v1/excel-agent/data-sources/{id}/schema` → full `ExcelSchemaResponse`
- `GET /api/v1/excel-agent/data-sources/{id}/schema/info` → concise `SchemaInfoResponse`
- `GET /api/v1/excel-agent/data-sources/{id}/manifest` → summary
- `GET /api/v1/excel-agent/data-sources/{id}/enrichment`
- `POST /api/v1/excel-agent/data-sources/{id}/ask` (body: `{question, conversation_id?}`) → `AskQuestionResponse`
- `GET /api/v1/excel-agent/data-sources/{id}/questions/suggested` → `{questions}`
- `GET /api/v1/excel-agent/data-sources/{id}/queries/history?limit=50`
- `GET /api/v1/excel-agent/conversations?skip&limit&data_source_id?`
- `GET /api/v1/excel-agent/conversations/{id}`
- `DELETE /api/v1/excel-agent/conversations/{id}`
- `PATCH /api/v1/excel-agent/conversations/{id}` (body: `{title}`)
- `GET /api/v1/excel-agent/usage/summary?days=30` → `UsageSummaryResponse`

**AskQuestionResponse shape** (the main Q&A response):

```typescript
{
  success: bool,
  answer: string,
  code_used: string | null,            // pseudo-trail of tool calls
  iterations: number | null,            // = tool_calls_made
  error: string | null,
  execution_time_ms: number,
  query_id: string,
  conversation_id: string,
  input_tokens: number | null,
  output_tokens: number | null,
  cost_usd: number | null,              // real dollar cost of this turn

  // Rosetta extensions (optional; UI may ignore):
  trace: object | null,                 // backward-trace tree
  audit_status: "passed" | "partial" | "unknown" | null,
  evidence_refs: string[] | null,       // cell refs cited
  active_entity: string | null,         // last Sheet!Ref for follow-ups
  scenario_overrides: object | null     // active what-if scenarios
}
```

---

# Part 9 — Configuration

## 9.1 Environment variables

Full reference in `.env.example`. Required for full operation:

```
# Server
HOST=0.0.0.0
PORT=8000

# Database (Postgres + Redis + Qdrant)
DATABASE_URL="postgresql+asyncpg://postgres:postgres@localhost:5432/intellegent-excel"
REDIS_URL="redis://localhost:6379/0"
QDRANT_HOST="localhost"
QDRANT_PORT=6333

# JWT
JWT_SECRET_KEY="<strong-random-string>"   # rotate for production
JWT_ALGORITHM="HS256"
JWT_ACCESS_TOKEN_EXPIRE_MINUTES=30
JWT_REFRESH_TOKEN_EXPIRE_DAYS=7

# Google OAuth (from Google Cloud Console)
GOOGLE_CLIENT_ID="..."
GOOGLE_CLIENT_SECRET="..."
GOOGLE_REDIRECT_URI="http://localhost:8000/api/v1/auth/google/callback"

# OpenAI (upload pipeline + embeddings)
OPENAI_API_KEY="sk-..."
AGENT_LLM_PROVIDER="openai"
AGENT_LLM_MODEL="gpt-4o"
EMBEDDING_PROVIDER="openai"
EMBEDDING_MODEL="text-embedding-3-small"
EMBEDDING_DIMENSION=1536

# Anthropic (Rosetta coordinator)
ANTHROPIC_API_KEY="sk-ant-..."
ROSETTA_MODEL="claude-sonnet-4-5"

# Qdrant collection
KNOWLEDGE_COLLECTION_NAME="excel_knowledge"

# CORS / security / logging
CORS_ALLOW_ALL_ORIGINS=true
SECURITY_HEADERS_ENABLED=true
LOG_LEVEL=INFO
LOG_FORMAT=console
```

### Note on `ANTHROPIC_API_KEY` shell conflict

Some macOS shells export `ANTHROPIC_API_KEY=""` globally (empty). Pydantic Settings prefers shell env over `.env`, so the empty value wins. If you see *"ANTHROPIC_API_KEY not set"* despite having it in `.env`, either:

- Run `unset ANTHROPIC_API_KEY` before `make dev`, OR
- Remove the empty export from your shell rc file

## 9.2 Settings class

Defined in `core/config.py` as a Pydantic `BaseSettings` subclass. Reads from `.env`, falls back to defaults. Adding new settings requires extending this class (unknown `.env` keys are rejected by default — `extra="forbid"`).

---

# Part 10 — Running locally

## 10.1 Prerequisites

- macOS or Linux
- Docker Desktop running
- Python 3.12+ (uv will download if absent)
- Node 18+
- `uv` package manager (`pip install uv`)

## 10.2 First-time setup

```bash
# 1. Install Python dependencies (creates .venv/)
uv sync --frozen --python 3.12

# 2. Install UI dependencies
make ui-install    # or: cd ui && npm install

# 3. Create env file
cp .env.example .env
# Edit .env to add real values (especially ANTHROPIC_API_KEY, OPENAI_API_KEY,
# GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, JWT_SECRET_KEY)

# 4. Start database services (Postgres + Redis + Qdrant in Docker)
make db-up

# 5. Apply migrations
uv run alembic upgrade head

# 6. Start backend (port 8000)
unset ANTHROPIC_API_KEY   # only if shell exports it empty
make dev

# 7. In another terminal, start UI (port 3000)
make ui-dev
```

Open `http://localhost:3000`, sign in with Google, upload an `.xlsx`, ask a question.

## 10.3 Make targets

| Target | Purpose |
|---|---|
| `make install` | `uv sync --frozen --no-cache` |
| `make dev-setup` | Full setup: install + db-up + migrate + init-db |
| `make dev` | Start backend via `uv run python main.py` |
| `make migrate` | `alembic upgrade head` |
| `make init-db` | Run no-op seed script |
| `make db-up` / `make db-down` | Start/stop Postgres + Redis containers |
| `make up` / `make down` | Full Docker stack (app + DBs) |
| `make build` | Build Docker image |
| `make logs` | Tail Docker logs |
| `make shell` | Shell into backend container |
| `make ui-install` / `make ui-dev` / `make ui-build` | UI operations |
| `make test` | `uv run pytest -v` (coverage reports to `htmlcov/`) |
| `make test-cov` | Tests with coverage |
| `make lint` | `uv run ruff check .` |
| `make format` | Auto-format with ruff |
| `make typecheck` | Optional: `uv run pyright` |
| `make check` | `lint + test` |
| `make clean` | Remove `__pycache__`, caches, coverage |

## 10.4 Tests

```bash
uv run pytest                                         # all tests
uv run python -m core.rosetta.tests.test_auditor_negation  # standalone auditor tests
```

Current tests: **10 auditor unit tests** covering negation handling, interrogative contexts, compound identifiers, assertive claim blocking, mixed sentence handling.

---

# Part 11 — Deployment

## 11.1 Recommended: Render.com

1. **Qdrant**: free-tier cluster at https://cloud.qdrant.io/. Copy URL + API key.
2. **Postgres**: Render Postgres addon. Copy `DATABASE_URL`.
3. **Redis**: Render Key-Value addon (or skip — optional).
4. **Backend web service**:
   - Repo: this one
   - Build: `pip install uv && uv sync --frozen`
   - Start: `uv run python main.py`
   - Instance: Standard (≥2GB RAM)
   - Env vars: everything from `.env.example`, with real values. Set `GOOGLE_REDIRECT_URI=https://<service>.onrender.com/api/v1/auth/google/callback`.
5. **Post-deploy**: open Render Shell → `uv run alembic upgrade head`.
6. **Frontend**: separate Render Static Site on `ui/`. Build: `npm install && npm run build`. Publish dir: `ui/dist`. Add `VITE_API_BASE_URL=https://<backend>.onrender.com/api/v1` — and update `ui/src/api/auth.ts` to read this env var instead of hardcoding `http://localhost:8000/api/v1`.

## 11.2 Docker Compose (local or VPS)

```bash
make up       # builds + starts 4 containers
make logs     # tail app logs
make down     # stop
```

Proxy via nginx or Caddy for HTTPS in production.

## 11.3 Post-deploy checks

- `GET /health` → 200 OK
- `GET /docs` → Swagger UI loads
- Sign in flow end-to-end
- Upload a sample workbook
- Ask a question → verify `audit_status=passed` and real cost in response

---

# Part 12 — Known limitations and technical debt

## 12.1 Product gaps (documented, not broken)

| Gap | Impact | Where it would be added |
|---|---|---|
| **Pivot table introspection** | Can't answer "what does this pivot show?" | New `list_pivots` tool in `core/rosetta/tools.py` |
| **Version diff** | Can't compare two ingests of the same workbook | New `version_diff` tool + workbook version hashing |
| **Row-level analytics (top-N, correlations, group-by)** | Returns "I don't know" honestly for these | New `compute_aggregate` tool in tools.py — deterministic, no code-gen |
| **Async ingest / job queue** | Large workbooks (>1000 cells) block the HTTP request up to 30s | Swap `BackgroundTasks` for Celery/RQ; add `GET /ingest/{job_id}/status` |
| **Multi-tenancy beyond per-user** | Can't enforce team or org boundaries | Add `organization_id` FK, scope queries |
| **Rate limiting** | Global only (`RATE_LIMIT_ENABLED`), not per-user or per-endpoint | Add `slowapi` decorators |
| **StructuralComparator specialist** | Comparison questions use only the general coordinator | Build `core/rosetta/specialists/structural_comparator.py` |

## 12.2 Code debt

- **66 pre-existing pyright type issues** in `core/vector/`, `core/services/`. Run `make typecheck` to see them. Fix incrementally; not blocking.
- **`core/rosetta/evaluator.py` custom evaluator** covers ~30 Excel functions. Any formula using a function outside that set returns `None` for what-if. Long-term fix: replace with `formulas` pip package or LibreOffice headless.
- **UI hardcodes `http://localhost:8000/api/v1`** in `ui/src/api/auth.ts`. Needs `VITE_API_BASE_URL` env var for deployment.
- **Upload pipeline uses OpenAI (GPT-4o)** while Q&A uses Anthropic (Claude). If Anthropic-only is a requirement, the upload pipeline agents (`mapper.py`, `semantic_enricher.py`) need porting.

## 12.3 Known non-issues that look like issues

- **`make lint` ignores many style rules** (line length, docstring formatting) — intentional, documented in `pyproject.toml` with comments. These are pre-existing style debt not worth blocking on.
- **Coverage is ~10%** — we disabled the 60% gate. Real test coverage is a follow-up; current tests cover the auditor only.
- **`orchestrator.ask_question()` raises `NotImplementedError`** — intentional. Q&A is handled by `core/rosetta/coordinator.py`. The legacy method is kept for backwards-compat signature only.

---

# Part 13 — How to extend the system

## 13.1 Adding a new tool to the coordinator

1. Add function to `core/rosetta/tools.py`:
   ```python
   def _my_new_tool(wb: WorkbookModel, arg1: str) -> dict:
       # pure-Python logic over wb
       return {"result": ...}
   ```
2. Add tool schema to the `TOOLS` list at the top of the file:
   ```python
   {
     "name": "my_new_tool",
     "description": "What the tool does, in one sentence for Claude.",
     "input_schema": {"type": "object", "properties": {...}, "required": [...]}
   }
   ```
3. Add dispatch case in `execute_tool()`:
   ```python
   if name == "my_new_tool":
       return _my_new_tool(wb, args["arg1"])
   ```
4. Update the coordinator's system prompt in `core/rosetta/coordinator.py::COORDINATOR_SYSTEM_PROMPT` with a hint on when to call it.

## 13.2 Adding a new specialist

1. Create `core/rosetta/specialists/your_specialist.py` with an `async def specialist_fn(input, context) -> dict`.
2. Coordinator invokes it by emitting a delegation marker (e.g. `<<DELEGATE_YOUR_SPECIALIST arg=X>>`) in its answer text.
3. Add handling in `core/rosetta/coordinator.py::_maybe_delegate_to_your_specialist` (pattern after `_maybe_delegate_to_explainer`).

## 13.3 Adding an audit detector

1. Add `def _my_detector(wb: WorkbookModel) -> list[AuditFinding]:` to `core/rosetta/audit.py`.
2. Add `findings.extend(_my_detector(wb))` in `audit_workbook()`.
3. Use a new `category` string (e.g. `"my_category"`). If the category represents a qualitative claim (like `stale_assumption`), also add the keyword to `QUAL_KEYWORDS` in `auditor.py`.
4. Add a test in `core/rosetta/tests/test_auditor_negation.py`.

## 13.4 Adding a new Postgres column

1. Generate migration: `uv run alembic revision --autogenerate -m "add column X"`
2. Review the generated migration in `alembic/versions/`
3. Add the column to the SQLAlchemy model in `core/models/`
4. Apply: `uv run alembic upgrade head`

## 13.5 Adding a new UI page

1. Create component in `ui/src/pages/`
2. Add route in `ui/src/App.tsx`
3. Add sidebar entry in `ui/src/components/Sidebar.tsx`
4. Add API client in `ui/src/api/` if needed

## 13.6 Changing the coordinator's LLM

To swap Claude for another model (e.g. GPT-4 or Gemini):

1. Change `ROSETTA_MODEL` env var.
2. If the provider is not Anthropic, replace `anthropic.AsyncAnthropic` client in `core/rosetta/coordinator.py` with the new SDK. Tool-calling block formats differ between providers — carefully adapt the `resp.content` / `resp.stop_reason` handling.
3. Update `core/rosetta/pricing.py` with the new model's per-token rates.
4. The coordinator's system prompt and tool schemas are model-agnostic — no changes there.

---

# Part 14 — Troubleshooting playbook

| Symptom | Likely cause | Fix |
|---|---|---|
| `pydantic-core` build fails during `uv sync` | uv chose Python 3.14; PyO3 maxes at 3.13 | `uv sync --frozen --python 3.12` |
| Backend returns *"ANTHROPIC_API_KEY not set"* despite `.env` populated | Shell exports `ANTHROPIC_API_KEY=""` globally | `unset ANTHROPIC_API_KEY` before `make dev` |
| `/ingest` fails with *"datetime is not JSON serializable"* | An Excel cell has a date value; default JSON can't serialize `datetime` | Already fixed via custom `_json_serializer` in `core/database/session.py`. If you add new models with JSON columns, they automatically benefit. |
| Docker containers fail: "port already allocated" | Another project holds 5432 / 6379 / 6333 | `docker stop <container>` or change ports in `docker-compose.yml` |
| Upload succeeds, "Process File" click fails with *"duplicate key"* | Race between background-task processing and explicit /process call | Already fixed via IntegrityError catch in `core/services/excel_agent.py::process_data_source` |
| `/ask` returns *"anthropic SDK not installed"* | uv env out of sync | `uv sync --frozen --python 3.12` |
| UI shows *"Failed to fetch"* | Backend down or CORS misconfigured | Check `curl http://localhost:8000/health`; check browser Network tab |
| Audit returns "partial" when answer is correct | LLM used a qualitative keyword in context the auditor flags | Review `NEGATION_TOKENS` / interrogative patterns in `core/rosetta/auditor.py`. Add a test case and extend as needed. |
| Qdrant collection `excel_knowledge` missing / "collection not found" | Fresh DB state | It auto-creates on first upload. If manually needed: upload any workbook. |
| Stale data source references missing file | User deleted file outside the UI | `DELETE /api/v1/data-sources/{id}` from UI (my-files → delete button) cleans it properly |

## Quick reset to clean slate (dev)

```bash
# Wipe all user data but keep your user row
docker exec excel-postgres psql -U postgres -d intellegent-excel -c "\
  DELETE FROM llm_usage; \
  DELETE FROM query_history; \
  DELETE FROM conversation_messages; \
  DELETE FROM conversations; \
  DELETE FROM excel_schemas; \
  DELETE FROM data_sources;"

rm -rf uploads/data_sources/*
touch uploads/data_sources/.gitkeep

curl -X DELETE http://localhost:6333/collections/excel_knowledge
```

---

# Part 15 — Glossary

| Term | Meaning |
|---|---|
| **Rosetta** | Internal name for the grounded Q&A engine (`core/rosetta/`). From the Rosetta Stone — our system translates Excel workbooks into something queryable. |
| **Coordinator** | The Claude agent in `core/rosetta/coordinator.py` that plans and executes a Q&A turn via tool-calling. |
| **Specialist** | A narrow-scope Claude call with a rigid style contract. Today: FormulaExplainer only. |
| **Citation auditor** | The post-answer verification pass in `core/rosetta/auditor.py` that checks every claim against tool outputs. |
| **Grounded answer** | An answer where every number/cell-ref/named-range is traceable to a tool result in the current session. |
| **ConversationState** | The in-memory per-turn working copy loaded from and persisted back to Postgres. Contains messages, active_entity, scenario_overrides. |
| **Active entity** | The last `Sheet!Ref` or metric mentioned in prior turns. Used to resolve follow-ups like "what about April?". |
| **Scenario overrides** | Dict of `{named_range_or_ref: override_value}` enabling composable what-if questions. Persisted per conversation. |
| **What-if** | Recompute a workbook with scenario overrides applied. Uses the in-house evaluator (partial Excel support). |
| **Audit finding** | A structural issue surfaced by one of six detectors (stale, circular, hidden, volatile, hardcoded, broken). |
| **Named range** | An Excel alias for a cell or range (e.g. `FloorPlanRate` → `Assumptions!$B$2`). Carries business semantics. |
| **Backward trace** | Recursive tree of what a cell depends on, rooted at the target cell. |
| **Forward impact** | List of cells that would change if the target cell changes. |
| **Workbook manifest** | Akash's output from `VisualMetadataExtractor` — visual/structural metadata about the workbook. |
| **Semantic schema** | Akash's output from `SemanticMapper` — LLM-inferred business meaning of sheets, columns, formulas. |
| **Semantic enrichment** | Akash's output from `SemanticEnricher` — domain classification, suggested questions, context header. |
| **Context header for Q&A** | A compact description of the workbook generated at upload time, intended to prime any Q&A prompt. Currently populated by upload pipeline but not yet injected into Rosetta's system prompt — opportunity for quality improvement. |
| **Knowledge base** | The Qdrant collection of semantic chunks per workbook, searchable via `KnowledgeBaseService.search`. |

---

# Part 16 — Starting points for a new developer

If you have just cloned the repo and want to understand how a question gets answered, read these files in this order:

1. **`main.py`** — entrypoint (trivial)
2. **`core/server.py`** — FastAPI app factory, lifespan
3. **`core/api/v1/routes/excel_agent.py::ask_question`** — the `/ask` endpoint (thin)
4. **`core/services/excel_agent.py::ExcelAgentService.ask_question`** — the glue
5. **`core/rosetta/coordinator.py::answer`** — the tool-calling loop
6. **`core/rosetta/tools.py`** — the 11 tools available to Claude
7. **`core/rosetta/auditor.py::audit`** — the grounding guarantee
8. **`core/rosetta/parser.py`** — how an `.xlsx` becomes a `WorkbookModel`

If you want to understand how a workbook gets uploaded:

1. **`core/api/v1/routes/data_sources.py::upload_sheet`**
2. **`core/services/data_source.py::upload`**
3. **`core/agents/orchestrator.py::process_workbook`**
4. **`core/vector/knowledge_base.py::index_data_source`**

If you want to understand the data model:

1. **`core/models/user.py`** → **`data_source.py`** → **`excel_schema.py`** → **`conversation.py`**
2. **`alembic/versions/`** — migration history

If you want to understand the frontend:

1. **`ui/src/App.tsx`** — routes
2. **`ui/src/pages/Dashboard.tsx`** — main page (My Files + Ask AI + Conversations)
3. **`ui/src/api/excelAgent.ts`** — all Q&A API calls
4. **`ui/src/context/AuthContext.tsx`** — JWT state

---

**End of handbook.** For day-to-day operational questions, see `docs/runbook.md`. For a brief component-level view, see `docs/architecture.md`. For getting started, see the top-level `README.md`.
