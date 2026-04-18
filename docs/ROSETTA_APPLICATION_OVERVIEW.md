# Rosetta — Complete Application Overview

> **Tagline:** *Spreadsheets that explain themselves.*
>
> Rosetta is an agentic Q&A system for Excel workbooks. It parses a workbook into a deterministic cell/formula graph, then lets Anthropic Claude Sonnet 4.5 answer natural-language questions by **calling tools over that graph** — with every number, reference, and qualitative claim **independently audited** against workbook and tool-output evidence before the answer ships. Two strikes on the auditor → the system says "I don't know" instead of hallucinating.

This document is the full technical narrative of the application in its current state: tech stack, architecture, modules, agents, tools, flows, APIs, models, UI, and user journey. Everything you need for a demo-day presentation is here.

---

## Table of Contents

1. [What Rosetta Does — In One Screen](#1-what-rosetta-does--in-one-screen)
2. [Architecture Diagram & Narrative](#2-architecture-diagram--narrative)
3. [Tech Stack (Backend + Frontend)](#3-tech-stack-backend--frontend)
4. [Repository Layout](#4-repository-layout)
5. [Data Model — Postgres + Qdrant](#5-data-model--postgres--qdrant)
6. [Upload & Enrichment Pipeline](#6-upload--enrichment-pipeline)
7. [The Rosetta Core — Parser, Graph, Audit](#7-the-rosetta-core--parser-graph-audit)
8. [The Coordinator — Claude Tool-Calling Loop](#8-the-coordinator--claude-tool-calling-loop)
9. [The Tool Registry (27+ Deterministic Tools)](#9-the-tool-registry-27-deterministic-tools)
10. [The Citation Auditor — Why Rosetta Doesn't Hallucinate](#10-the-citation-auditor--why-rosetta-doesnt-hallucinate)
11. [The Formula Explainer Specialist](#11-the-formula-explainer-specialist)
12. [Multi-turn Memory — Sessions, Entities, Scenarios](#12-multi-turn-memory--sessions-entities-scenarios)
13. [Pricing & Usage Tracking](#13-pricing--usage-tracking)
14. [API Surface — Every Route](#14-api-surface--every-route)
15. [Frontend — Pages, Components, Styling](#15-frontend--pages-components-styling)
16. [End-to-End Query Flow (Input → Output)](#16-end-to-end-query-flow-input--output)
17. [Authentication & Security](#17-authentication--security)
18. [Observability Stack](#18-observability-stack)
19. [Caching Strategy](#19-caching-strategy)
20. [Configuration & Feature Flags](#20-configuration--feature-flags)
21. [Deployment (Docker Compose)](#21-deployment-docker-compose)
22. [User Journey](#22-user-journey)
23. [Key Design Principles & Differentiators](#23-key-design-principles--differentiators)
24. [Glossary](#24-glossary)

---

## 1. What Rosetta Does — In One Screen

A finance/ops team uploads a messy Excel workbook (a dealership P&L, an energy portfolio model — anything). Rosetta:

1. **Parses** every sheet into a typed cell/formula graph — values, formulas, dependencies, named ranges, merged regions, pivot tables, hidden deps, circular references.
2. **Enriches** the workbook via an LLM pass — domain classification, semantic columns, key metrics, dimensions, retrieval hints, a "context header" paragraph injected into every Q&A prompt.
3. **Indexes** labeled cells into Qdrant (OpenAI `text-embedding-3-small`, 1536-dim) so that "adjusted EBITDA" or "floor plan interest" resolves to the right cell ref even when the header wording differs.
4. **Audits** the workbook for stale assumptions, hardcoded anomalies, volatile formulas, broken refs, circular references, hidden dependencies.
5. **Answers** questions by running Claude Sonnet 4.5 in an Anthropic-SDK tool-calling loop (max 10 turns) against **27+ deterministic tools** (graph traversal, what-if, scenario recalc, DuckDB-over-sheets SQL, goal seek, sensitivity/tornado, time-series, joins, pivot lookups, semantic search). Every tool reads from the parsed graph — **the LLM never invents numbers, it only cites them**.
6. **Audits the answer** via an independent regex + workbook-universe check before shipping. If any number, cell ref, named range, or qualitative claim is unverifiable, retry once with violation feedback; second failure → partial "I can only answer in part" response. Confidence score attached.
7. **Renders** the answer with a formula dependency tree (`react-d3-tree`), signed equation chips, optional analytics charts (tornado / goal-seek convergence / bar), and a navigable ER diagram of cross-sheet relationships.
8. **Remembers** within a session — `active_entity` and `scenario_overrides` persist to Postgres so "and what about April?" / "what if FloorPlanRate went to 8%?" compose against prior turns.

**Trust principles** baked into the UI footer: *No black boxes · No string arithmetic · No orphan answers.*

---

## 2. Architecture Diagram & Narrative

### 2.1 Full system diagram

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                               BROWSER (React 19)                              │
│                                                                                │
│   /             /login    /auth/google/callback     /dashboard/*   /data-…     │
│   Home       Login Page      GoogleCallback          Dashboard     Detail     │
│                                         │                   │                  │
│                                    AuthContext        Layout + Sidebar         │
│                                 (user, tokens,           │                     │
│                                  localStorage)     ask-ai │ my-files │ convo   │
│                                                   ────────────────────────     │
│                                                   SchemaInspector  FormulaModal│
│                                                    (ER diagram)  Map + Chips   │
│                                                   AnswerMarkdown  AnalyticsCh. │
│                                                   (react-markdown) Tornado /   │
│                                                                    GoalSeek    │
│                                                                    / Bar       │
└──────────────────────────────────────────────┬───────────────────────────────┘
                                               │  HTTPS (Bearer JWT)
                                               │  withAuthRetry → 401 → refresh
                                               ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│                        FASTAPI APP — core/server.py                            │
│   CORS → SecurityHeaders → LoggingMiddleware (X-Correlation-ID) → Router       │
│                                                                                │
│   /api/v1/auth/*               /api/v1/data-sources/*         /api/v1/excel-   │
│     google/url                   upload (multipart)             agent/         │
│     google/callback              list / get / analysis          …/process      │
│     refresh                      search (Qdrant)                …/schema       │
│                                  DELETE (cascade)               …/ask  ◄─────┐ │
│                                                                 …/questions/ │ │
│                                                                  suggested   │ │
│                                                                 conversations│ │
│                                                                 usage/summary│ │
│   /health   /metrics (Prometheus)                                            │ │
└──────────────────────────────────────────────────────────────────────────────┘
   │                              │                                            │
   │                              │                                            │
   │ AuthService                  │ DataSourceService                          │
   │ (Google OAuth, JWT)          │ ExcelAgentService                          │
   │                              │ ConversationService                        │
   ▼                              ▼                                            │
┌─────────────────┐   ┌──────────────────────────────────────────────┐        │
│  PostgreSQL 16  │   │        UPLOAD & ENRICHMENT PIPELINE           │        │
│  (SQLAlchemy2   │   │                                                │        │
│   async+alembic)│   │  openpyxl/xlrd →  VisualMetadataExtractor      │        │
│                 │   │  manifest        (colors, merges, sections)    │        │
│  users          │   │     │                                          │        │
│  data_sources   │   │     ▼                                          │        │
│  excel_schemas  │   │  LangChain LLM → SemanticMapper (legacy)       │        │
│  conversations  │   │     │           (schema JSON)                  │        │
│  conversation_  │   │     ▼                                          │        │
│    messages     │   │  LangChain LLM → SemanticEnricher              │        │
│  llm_usage      │   │  (Gemini/OpenAI) (time_dim, key_metrics,       │        │
│  file_upload_   │   │                   dimensions, tables, domain,  │        │
│    usage        │   │                   context_header_for_qa,       │        │
│  query_history  │   │                   cross_sheet_relationships)   │        │
└─────────────────┘   │     │                                          │        │
                      │     ▼                                          │        │
                      │  KnowledgeBaseService →                        │        │
                      │   ExcelParser → SemanticChunkGenerator →       │        │
                      │   OpenAI embeddings (text-embedding-3-small) → │        │
                      │   Qdrant upsert  (user_id + data_source_id     │        │
                      │                   filter, 1536-dim Cosine)     │        │
                      └──────────────────────────────────────────────┘        │
                                                                                │
                      ┌──────────────────────────────────────────────┐        │
                      │           ROSETTA Q&A (core/rosetta/)         │◄───────┘
                      │                                                │
                      │  parser.py      — openpyxl 2-pass, typed cells│
                      │  formula_parser — token-level dep extraction  │
                      │  evaluator.py   — partial Excel evaluator     │
                      │  graph.py       — backward/forward trace      │
                      │  graph_viz.py   — trace → React Flow payload  │
                      │  audit.py       — structural findings         │
                      │  pivot_parser   — raw xl/pivotTables/*.xml    │
                      │  analytics/     — aggregators, SQL (DuckDB),  │
                      │                   time_series, stats, filters,│
                      │                   goal_seek, sensitivity, DQ  │
                      │                                                │
                      │  ┌─────────────────────────────────────────┐  │
                      │  │   COORDINATOR (Claude Sonnet 4.5 tool   │  │
                      │  │      loop, max 10 turns)                │  │
                      │  │                                         │  │
                      │  │   system = COORDINATOR_SYSTEM_PROMPT    │  │
                      │  │   tools  = TOOLS (27+ deterministic)    │  │
                      │  │   model  = claude-sonnet-4-5            │  │
                      │  │   temperature=0, max_tokens=2048        │  │
                      │  │                                         │  │
                      │  │   on tool_use → execute_tool(wb,name,   │  │
                      │  │                 args, user_id,ds_id)    │  │
                      │  │                                         │  │
                      │  │   <<DELEGATE_FORMULA_EXPLAINER ref=…>>  │  │
                      │  │     → specialists/formula_explainer     │  │
                      │  │       (separate Anthropic call)         │  │
                      │  │                                         │  │
                      │  │   → auditor.audit(text, tool_log, wb)   │  │
                      │  │     passed  → confidence 0.9, ship      │  │
                      │  │     failed  → inject feedback, retry 1x │  │
                      │  │     failed² → partial answer, conf 0.3  │  │
                      │  └─────────────────────────────────────────┘  │
                      │                      │                         │
                      │                      ▼                         │
                      │   bridge.py → service dict → LLMUsage row +    │
                      │     ConversationMessage rows + cache update    │
                      │                                                │
                      │   Response: {answer, trace (TraceNode tree),   │
                      │              graph_data (ReactFlow), chart_    │
                      │              data, audit_status, evidence_refs,│
                      │              active_entity, scenario_overrides}│
                      └──────────────────────────────────────────────┘
                                              │
   ┌──────────────────────────────────────────┴──────────────────────────────┐
   │                                                                          │
   ▼                                                                          ▼
┌─────────────┐       ┌──────────────────────┐       ┌────────────────────────┐
│ Redis 7     │       │ Qdrant 1.9.7         │       │ Anthropic API (Claude) │
│ (cache,     │       │ collection           │       │ + OpenAI embeddings    │
│  in-process │       │ excel_knowledge      │       │ + Gemini/OpenAI        │
│  tenant     │       │ 1536-dim Cosine      │       │ (enrichment)           │
│  cache,     │       │ filter by user_id +  │       └────────────────────────┘
│  rate-      │       │ data_source_id       │
│  limiter)   │       └──────────────────────┘
└─────────────┘

Observability: OpenTelemetry (traces + logs + metrics) → Jaeger (OTLP 4318) +
Prometheus (/metrics) + Grafana (provisioned datasources).
```

### 2.2 Narrative of the diagram

- **Left column — Postgres** is the durable source of truth for users, data sources (file metadata), parsed `excel_schemas` (manifest, semantic_schema, enrichment), and conversation/message history with per-call LLM cost accounting.
- **Center top — Upload pipeline** runs once per workbook (or on `force_reprocess`). Phase A is pure openpyxl; Phase B is a legacy mapper LLM (retained as fallback); Phase C is the domain-aware semantic enricher whose output feeds **both** the Q&A context header and the schema inspector UI. The knowledge-base step fan-outs embeddings to Qdrant.
- **Center bottom — Rosetta Q&A** parses the workbook fresh at query time (`parse_workbook` is cheap — ~openpyxl speed) into a rich in-memory `WorkbookModel`. The coordinator then runs a Claude tool-calling loop that **only** touches the workbook through the deterministic tool set. The auditor intercepts the final text before it leaves the service.
- **Right column — External services**: Anthropic for the coordinator and FormulaExplainer specialist; OpenAI for embeddings; Gemini *or* OpenAI (configurable via `AGENT_LLM_PROVIDER`) for enrichment-time LLM calls.
- **Bottom sidebar — Ops substrate**: Redis (cache + rate limiter), Qdrant (vector semantic search), full OpenTelemetry instrumentation (FastAPI, SQLAlchemy, Redis) exporting to Jaeger + Prometheus.

### 2.3 Request life-cycle (happy path, ask-question)

```
User → Browser             POST /api/v1/excel-agent/data-sources/{id}/ask
 │                         {question, conversation_id?}
 ▼
 FastAPI router  ──(get_current_user)──► AuthService.verify_access_token
 │
 ▼
 ExcelAgentService.ask_question
 │
 ├─► ensure Conversation row (create if new)
 ├─► rosetta.parser.parse_workbook(stored_file_path)  → WorkbookModel
 ├─► rosetta.audit.audit_workbook(wb)                  → wb.findings[]
 ├─► rosetta.conversation.load_state(session, convo)   → ConversationState
 ├─► check state.answer_cache[question_hash]           → maybe short-circuit
 │
 ├─► coordinator.answer(wb, state, message, user_id, data_source_id)
 │   │
 │   ├─ build Claude messages (prepend [Context: active_entity, scenario_overrides])
 │   ├─ loop ≤10 turns:
 │   │    anthropic.messages.create(
 │   │      model=claude-sonnet-4-5,
 │   │      system=COORDINATOR_SYSTEM_PROMPT,
 │   │      tools=TOOLS,
 │   │      messages=claude_messages,
 │   │      temperature=0, max_tokens=2048)
 │   │    on tool_use → execute_tool(wb, name, args, user_id, data_source_id)
 │   │                 → append tool_result (≤12KB JSON) → continue
 │   │    on end_turn  → final text
 │   ├─ detect <<DELEGATE_FORMULA_EXPLAINER ref=Sheet!Ref>> → run specialist,
 │   │   splice prose
 │   ├─ auditor.audit(text, tool_log, wb)
 │   │   passed   → return answer (confidence 0.9)
 │   │   failed¹  → inject violation feedback, re-run loop once
 │   │   failed²  → return partial "I can only partially answer this" (0.3)
 │   └─ extract evidence_refs, update active_entity, cache if passed
 │
 ├─► rosetta.pricing.compute_cost_usd(model, input, output)
 ├─► insert LLMUsage + user ConversationMessage + assistant ConversationMessage
 ├─► rosetta.conversation.persist_state → update conversations.active_entity,
 │                                                  scenario_overrides
 │
 └─► bridge.coordinator_to_service_result(...)
     → {success, answer, code_used (pseudocode trail), trace, graph_data,
        chart_data, audit_status, evidence_refs, active_entity,
        scenario_overrides, input_tokens, output_tokens, cost_usd,
        execution_time_ms, query_id, conversation_id}

Browser ◄── AskQuestionResponse
 ├─ chat bubble (AnswerMarkdown)
 ├─ "Visualise formula" button → FormulaModal (Map / Formula toggle)
 ├─ AnalyticsChart (if chart_data) → Tornado / GoalSeek / Bar
 └─ evidence_refs / audit_status available for future surfaces
```

---

## 3. Tech Stack (Backend + Frontend)

### 3.1 Backend
| Area | Choice |
|---|---|
| Language / runtime | **Python ≥3.12** (Dockerfile: `python:3.12-slim`, multi-stage, non-root `appuser`) |
| Web framework | **FastAPI ≥0.116.1**, uvicorn, pydantic 2, pydantic-settings |
| RDBMS | **PostgreSQL 16** (alpine) via SQLAlchemy 2 async + asyncpg + Alembic |
| Cache | **Redis 7** (`redis.asyncio`, tenant cache, tag invalidation, metrics) |
| Vector DB | **Qdrant 1.9.7** (`qdrant-client`, async+sync singletons, Cosine) |
| Embeddings | **OpenAI `text-embedding-3-small`** (1536-dim, batch size 100) |
| Coordinator LLM | **Anthropic Claude Sonnet 4.5** (`anthropic ≥0.96`, AsyncAnthropic) |
| Specialist LLM | Claude Sonnet 4.5 via `anthropic` (sync) — FormulaExplainer |
| Enrichment LLM | Google **Gemini 1.5 Pro** (default) or OpenAI via LangChain (`AGENT_LLM_PROVIDER=gemini\|openai`) |
| Excel parsing | `openpyxl`, `xlrd`, `lxml` (raw pivot XML), `pandas` |
| In-process SQL | **DuckDB** — sheets exposed as tables to Claude via `sql_query` tool |
| Observability | OpenTelemetry (API/SDK/OTLP exporters), `prometheus-client`, `structlog` JSON/text, Jaeger, Grafana |
| Auth | Google OAuth via `httpx`; `pyjwt` HS256 (access 30m, refresh 7d); `passlib[bcrypt]` for optional local auth |
| Dev/CI | `pytest`, `pytest-asyncio`, `pytest-cov`, `ruff`, `pyright`, `bandit`, `locust`, `debugpy`, `pre-commit` |

### 3.2 Frontend
| Area | Choice |
|---|---|
| Framework | **React 19.2.4** under `StrictMode`, `createRoot` |
| Router | `react-router-dom ^7.14.0` |
| Styling | **Tailwind CSS v4** via `@tailwindcss/vite` (CSS-first config — no `tailwind.config.*`), custom design tokens in `:root` |
| Build | **Vite 8**, TypeScript ~6.0, ESLint 9 flat config |
| Graph viz | `@xyflow/react ^12` (React Flow) + `dagre ^0.8.5` for LR auto-layout; `react-d3-tree ^3.6.6` for the backward-trace tree |
| Charts | **Pure SVG** — no D3/Recharts. Tornado, goal-seek, bar all hand-rolled |
| Markdown | `react-markdown ^10` + `remark-gfm ^4` (GFM tables) |
| State | React Context only (`AuthContext`) + local `useState` |
| Fonts | **Inter 300/400/500** + **JetBrains Mono 400** via Google Fonts at document level |
| Auth client | Hand-rolled fetch + `localStorage` + Google redirect flow |

---

## 4. Repository Layout

```
Forge_Hackathon_2026/
├── main.py                         # uvicorn.run("core.server:app", …)
├── pyproject.toml · uv.lock        # Python deps (uv)
├── Dockerfile · docker-compose.yml
├── Makefile · run-dev.sh
├── alembic.ini · alembic/versions  # 6 migrations (users → conversation state)
├── data/                           # demo xlsx files (dealership, energy)
├── uploads/data_sources/           # user uploads at runtime
├── monitoring/                     # prometheus.yml, grafana datasources
├── scripts/                        # init-db.sql, init_data.py, setup_jaeger.sh
├── core/
│   ├── server.py                   # FastAPI factory, lifespan, middleware, handlers
│   ├── config.py                   # Settings (BaseSettings)
│   ├── logging.py · observability.py
│   ├── api/v1/                     # routers + schemas
│   │   ├── __init__.py             # api_router = APIRouter(prefix="/v1")
│   │   ├── routes/auth.py · data_sources.py · excel_agent.py
│   │   └── schemas/auth.py · data_sources.py · excel_agent.py
│   ├── middlewares/                # cors, security, logging
│   ├── dependencies/               # auth (get_current_user), cache
│   ├── security/                   # (empty package)
│   ├── models/                     # SQLAlchemy: user, data_source, excel_schema, conversation
│   ├── schemas/                    # shared pydantic base (pagination, timestamp mixin)
│   ├── services/                   # auth, data_source, excel_agent, conversation
│   ├── repository/                 # BaseRepository generic CRUD
│   ├── database/                   # session manager, engine, JSON serializer
│   ├── cache/                      # RedisBackend, tenant cache, key_maker, metrics
│   ├── exceptions/                 # base hierarchy + handlers
│   ├── utils/rate_limit.py         # slowapi Limiter (Redis storage)
│   ├── observability.py            # full OTel wiring
│   ├── agents/                     # UPLOAD PIPELINE (enrichment, not Q&A)
│   │   ├── base.py                 # BaseAgent, AgentResult, get_llm_client (LangChain)
│   │   ├── extractor.py            # VisualMetadataExtractor (openpyxl)
│   │   ├── mapper.py               # SemanticMapper (legacy, LLM JSON)
│   │   ├── semantic_enricher.py    # SemanticEnricher (domain/metrics/context_header)
│   │   └── orchestrator.py         # ExcelAgentOrchestrator (Phase A→B→C)
│   ├── rosetta/                    # Q&A HEART (Claude + deterministic tools)
│   │   ├── models.py               # pydantic WorkbookModel, TraceNode, CellModel, etc.
│   │   ├── parser.py               # parse_workbook(path) → WorkbookModel (2-pass openpyxl)
│   │   ├── formula_parser.py       # token-level dependency extraction
│   │   ├── evaluator.py            # partial Excel evaluator (what-if engine)
│   │   ├── graph.py                # backward_trace, forward_impacted
│   │   ├── graph_viz.py            # trace_to_graph → React Flow payload
│   │   ├── audit.py                # structural audit findings
│   │   ├── pivot_parser.py         # raw xl/pivotTables/*.xml parser
│   │   ├── cell_context.py         # semantic chunk text builder
│   │   ├── pricing.py              # Claude $/token table → USD cost
│   │   ├── conversation.py         # ConversationState, load/persist, answer_cache
│   │   ├── coordinator.py          # ** Claude tool-loop + audit gate **
│   │   ├── tools.py                # TOOLS list (Claude schemas) + execute_tool dispatch
│   │   ├── auditor.py              # ** citation auditor (independent gate) **
│   │   ├── bridge.py               # coordinator result → API response dict
│   │   ├── analytics/              # aggregators, filters, sql (DuckDB), time_series,
│   │   │                            # stats, goal_seek, sensitivity, data_quality, view
│   │   ├── specialists/
│   │   │   └── formula_explainer.py  # Claude specialist for "how is X calculated?"
│   │   └── tests/test_auditor_negation.py
│   ├── semantic_layer/             # example-prompt.md (spec/blueprint, not imported)
│   └── vector/
│       ├── client.py               # QdrantClientManager singleton
│       ├── embedding.py            # EmbeddingService (OpenAI)
│       ├── excel_parser.py         # deep analysis for chunking (distinct from rosetta parser)
│       ├── chunk_generator.py      # SemanticChunkGenerator → DocumentChunk[]
│       └── knowledge_base.py       # KnowledgeBaseService (index, search, delete)
└── ui/
    ├── index.html                  # Inter + JetBrains Mono preconnects
    ├── vite.config.ts              # @vitejs/plugin-react + @tailwindcss/vite, :3000
    ├── package.json
    └── src/
        ├── main.tsx · App.tsx · index.css
        ├── context/AuthContext.tsx
        ├── api/auth.ts · dataSources.ts · excelAgent.ts
        ├── pages/Home · Login · GoogleCallback · Dashboard · DataSourceDetail
        └── components/Layout · Sidebar · AnswerMarkdown · AnalyticsChart ·
                       TornadoChart · GoalSeekConvergence · DependencyGraphCard ·
                       SchemaInspector · FormulaModal · FormulaMap · EquationChips
```

---

## 5. Data Model — Postgres + Qdrant

### 5.1 `users`
`id (UUID, pk), email (unique), password_hash (nullable for OAuth), first_name, last_name, full_name, profile_picture (Text), auth_provider ∈ {LOCAL, GOOGLE}, google_id (unique), is_active, is_verified, is_superuser, created_at, updated_at, last_login_at`.

### 5.2 `data_sources`
`id, user_id (FK, CASCADE), name, original_file_name, stored_file_path, mime_type, file_extension, file_size_bytes (BIGINT), sheet_count, sheet_names (JSON), file_checksum_sha256, meta_info (JSON — contains knowledge_base.analysis), created_at, updated_at`.

### 5.3 `excel_schemas` (1:1 with `data_sources`)
`processing_status ∈ {PENDING, EXTRACTING, MAPPING, ENRICHING, COMPLETED, FAILED}, processing_error, manifest (JSON), semantic_schema (JSON — legacy), enrichment (JSON), workbook_title, workbook_purpose, domain, context_header_for_qa (Text — injected into every Q&A prompt), query_routing (JSON), detected_colors, total_sections, total_merged_regions, queryable_questions (JSON), data_quality_notes (JSON), is_ready_for_queries, processed_at`.
Helpers: `mark_extracting/mapping/enriching/completed/failed`.

### 5.4 `conversations`
`id, user_id, data_source_id (both CASCADE), title, is_active, total_input_tokens, total_output_tokens, total_cost_usd (Numeric(10,6)),` **`active_entity (Text)`, `scenario_overrides (JSONB, default '{}')`** *(Rosetta v2A)*`, last_message_at, created_at, updated_at`.

### 5.5 `conversation_messages`
`id, conversation_id (CASCADE), role ∈ {user, assistant}, content, code_used, execution_time_ms, is_error, error_message, input_tokens, output_tokens, cost_usd, llm_usage_id (FK SET NULL), created_at`.

### 5.6 `llm_usage`
Per-API-call accounting. `user_id, call_type ∈ {ASK_QUESTION, METADATA_EXTRACTION, SEMANTIC_MAPPING, CODE_GENERATION, ERROR_CORRECTION}, context (JSON — data_source_id, conversation_id, excel_schema_id, message_id), provider ∈ {OPENAI, GEMINI}, model, input/output/total tokens, input_cost_usd, output_cost_usd, total_cost_usd (Numeric(10,6)), extra_metadata (column "metadata"), latency_ms, success, error_message`. Classmethod `calculate_cost(provider, model, in, out)`.

### 5.7 `file_upload_usage`
Per-upload cost breakdown: `metadata_extraction_cost_usd, semantic_mapping_cost_usd, total_processing_cost_usd`, token totals.

### 5.8 `query_history` (legacy)
`excel_schema_id, user_id, question, answer (JSON), code_used, success, error_message, execution_time_ms, iterations_used, created_at`.

### 5.9 Qdrant — collection `excel_knowledge`
Single shared collection, 1536-dim Cosine, on-disk payload, Pointstruct payload includes `user_id`, `data_source_id`, `cell_ref`, `cell_label`, `section_header`, `chunk_type`. All searches are filtered by `(user_id AND optionally data_source_id)` so tenant isolation is enforced by filter.

### 5.10 Alembic migrations
1. `dce8846e5d56_create_users_table.py`
2. `57f5ac9a2f11_create_data_sources_table.py`
3. `a1b2c3d4e5f6_create_excel_schema_tables.py` — `excel_schemas` + `query_history`
4. `b2c3d4e5f6a7_create_conversation_tables.py` — `conversations` + `conversation_messages` + `llm_usage` + `file_upload_usage`
5. `c3d4e5f6a7b8_add_semantic_enrichment_fields.py` — enrichment, workbook_title, domain, context_header_for_qa, query_routing
6. `d4e5f6a7b8c9_add_conversation_state_columns.py` — `active_entity` + `scenario_overrides` (Rosetta v2A)

---

## 6. Upload & Enrichment Pipeline

Triggered by `POST /api/v1/data-sources/upload` (with `auto_process=True`) or by `POST /api/v1/excel-agent/data-sources/{id}/process`. Runs in a FastAPI `BackgroundTasks` coroutine.

### 6.1 Phase A — Visual metadata extraction (`core/agents/extractor.py`)
Pure openpyxl, no LLM. Walks every sheet and produces a `WorkbookManifest`:
- Per-cell: `CellMetadata` (value, type, formula presence, number format, font, fill color, alignment).
- Merged regions (`MergedRegion`), color regions (hex → semantic label via `COLOR_LABELS` lookup — e.g. `FF0000 → "Red/Alert"`, nearest-RGB fallback).
- Header row detection (rows 1–20 with ≥60% text cells).
- Section detection from merged headers spanning ≥3 cols; secondary color-based section detection.
- Empty rows/cols (90% threshold), sample data extraction (configurable, default 5 rows).
- Serialized via `manifest_to_dict(manifest)` for downstream LLM consumption.

### 6.2 Phase B — Semantic mapping, legacy fallback (`core/agents/mapper.py`)
LangChain chat client (Gemini/OpenAI). Single LLM pass with `SEMANTIC_MAPPING_PROMPT` asking for a workbook-level JSON schema: `workbook_purpose`, per-sheet `purpose/primary_entity/columns[]/sections[]/relationships[]/queryable_questions[]`, `global_metrics`, `data_quality_notes`. Output normalized through a markdown-fence/first-JSON-object extractor for robustness. Non-fatal on failure — retained for backward compatibility.

### 6.3 Phase C — Semantic enrichment (`core/agents/semantic_enricher.py`)
The **domain-aware** pass whose output is injected into every Q&A prompt. Two LLM stages:

**Stage 1 — per-sheet enrichment** (parallelized with `asyncio.gather`). System prompt: *"senior data analyst specialising in interpreting structured and semi-structured Excel spreadsheets"*. Classifies each sheet as `financial | sales_crm | operations_inventory | general` and emits JSON with:
- `time_dimension` (period type, granularity, column mapping)
- `key_metrics[]` — name, unit, semantic_role (revenue/cost/margin/…)
- `dimensions[]` — categorical axes
- `detected_tables[]` — each with columns (name, inferred_type, semantic_role)
- `section_labels[]`, `answerable_question_types[]`, `data_quality_flags[]`
- `retrieval_hints` — which chunking strategy the knowledge base should use
- `confidence` score

**Stage 2 — workbook-level summary**. Emits:
- `workbook_title`, `purpose`, `domain`
- `sheet_index[]`
- **`cross_sheet_relationships[]`** — drives the ER diagram
- `global_metrics[]`
- `recommended_query_routing{schema_questions, financial_questions, trend_questions, lookup_questions}`
- **`context_header_for_qa`** — a 3–5 sentence grounding paragraph

### 6.4 Phase D — Knowledge base indexing (`core/vector/knowledge_base.py`)
Distinct pipeline: `ExcelParser` (different from `rosetta/parser.py`) does deep cell-level analysis → `SemanticChunkGenerator` emits chunks at multiple granularities (overview, sheet, column-group, **labeled-cell** — each with `cell_ref`, `cell_label`, `section_header` metadata). OpenAI embeds in batches of 100 (max 8000 chars/chunk) → Qdrant upserts with filter-friendly payload.

**The labeled-cell chunks are what Rosetta's `find_cells(tier='semantic')` tool queries at Q&A time.**

### 6.5 Orchestration (`core/agents/orchestrator.py`)
`ExcelAgentOrchestrator.process_workbook(file_path, force_reprocess, skip_enrichment)` runs A→B→C with an in-memory cache. `ask_question()` in this class explicitly raises `NotImplementedError` with the comment *"Use ExcelAgentService.ask_question() which invokes the Rosetta coordinator with citation audit."*

---

## 7. The Rosetta Core — Parser, Graph, Audit

### 7.1 `core/rosetta/models.py` — the universe
All Pydantic. Central types:
- **`CellModel`**: `sheet, coord, ref ("Sheet!G32"), value, formula, formula_type, depends_on[], depended_by[], named_ranges_used[], is_hardcoded, is_volatile, data_type, semantic_label`.
- **`NamedRangeModel`**: `name, scope, raw_value, resolved_refs[], current_value, is_dynamic`.
- `RegionModel`, `PivotFieldModel`, `PivotTableModel`, `SheetModel`, `CircularRef`, `AuditFinding`, `DependencyGraphSummary`.
- **`WorkbookModel`**: the whole graph — `workbook_id, filename, sheets, named_ranges, cells: dict[ref → CellModel], graph_summary, findings, ingested_at`.
- Response types: `TraceNode`, `QAEvidence`, `QAResponse`, `WhatIfImpact`, `WhatIfResponse`.

### 7.2 `parser.py` — `parse_workbook(path) -> WorkbookModel` (633 lines)
Two-pass openpyxl load (formulas + cached values). Key subroutines:
- `_canon(sheet, coord)` → canonical refs.
- `_infer_data_type(value, number_format, label)` — classifies into `empty | bool | date | number | percent | currency | string | error`. Uses number format regexes **plus** label hints: `_PERCENT_LABEL_HINTS = ("rate", "percent", "ratio", "margin", "%")`, `_CURRENCY_LABEL_HINTS = ("revenue", "cost", "price", "gross", "profit", "income", "expense", "amount", "total", "budget", "addback", "payroll", "fee", "spend", "pvr", "allowance", "compensation")`.
- Extracts dependencies via `formula_parser.parse_formula`.
- Merges pivot-table data from `pivot_parser.parse_pivot_tables`.

### 7.3 `formula_parser.py` — token-level dependency extraction (313 lines)
Deterministic. Constants: `VOLATILE_FUNCS = {NOW, TODAY, RAND, RANDBETWEEN, OFFSET, INDIRECT, INFO, CELL}`, plus `AGGREGATION_FUNCS`, `LOOKUP_FUNCS`, `CONDITIONAL_FUNCS`. Handles quoted sheet names, absolute refs, ranges, named ranges.
Public: `parse_formula(formula, current_sheet)`, `expand_refs`, `expand_range`, `col_to_index`, `index_to_col`.

### 7.4 `evaluator.py` — partial Excel evaluator (918 lines)
Tokenizer + expression parser implementing arithmetic, comparisons, `&` concat, and a function whitelist: `SUM, AVERAGE, MIN, MAX, COUNT[A], PRODUCT, ROUND, ABS, IF, IFERROR, IFNA, AND, OR, NOT, SUMIF[S], COUNTIF[S], AVERAGEIF[S], SUMPRODUCT, VLOOKUP, HLOOKUP, XLOOKUP, INDEX, MATCH, DATE, YEAR, MONTH, DAY, TODAY, NOW`. `Evaluator(wb, overrides=None)` memoizes, detects circular refs via `_eval_stack`, and tracks `.unsupported: set[str]`. Used by `what_if` / `scenario_recalc` / `join_on_key` / `find_cells` (value backfill). Slated to migrate to the `formulas` pip package in v2.

### 7.5 `graph.py` — traversal (112 lines)
- `backward_trace(wb, ref, max_depth=8) → TraceNode` — tree of inputs with hardcoded/volatile warnings. Logical ranges collapse into a single leaf node.
- `forward_impacted(wb, ref, max_depth=12) → [(ref, depth)]` — BFS over `depended_by`.
- `forward_impacted_for_named_range(wb, name)` — union across all resolved refs + every cell that uses the name as a symbol.

### 7.6 `graph_viz.py` — trace → React Flow payload (118 lines)
`trace_to_graph(trace) → {nodes, edges, focal_ref, node_count, edge_count} | None`. Edges left→right (input → output). Returns `None` if <2 cells. Node `data` carries every detail the `DependencyGraphCard` needs.

### 7.7 `audit.py` — structural findings
`audit_workbook(wb, source_path=None) → list[AuditFinding]`. Detectors:
- `_stale_assumptions` — sheets named *assumption*/*settings* with dates >12 months old.
- `_hidden_deps` — cells computed from hidden rows/cols.
- `_volatile_formulas` — cells using `VOLATILE_FUNCS`.
- `_hardcoded_anomalies` — raw numbers where peers use formulas.
- `_circular_references` — with author-comment evidence if present.
- `_broken_refs` — `#REF!`, `#N/A`, etc.
- `_conditional_formatting_rules` — if `source_path` provided (opens the zip).
- `analytics.data_quality.scan_flat_table` — duplicates, outliers, missing values on tabular sheets.

### 7.8 `pivot_parser.py` — raw XML pivot parser (260 lines)
Opens the `.xlsx` zip directly and reads `xl/pivotTables/*.xml` + `xl/pivotCache/pivotCacheDefinition*.xml`. Extracts location, source range, fields by axis (row/column/value/filter), aggregation per value field, calculated-field formulas, refresh flags. Skips OLAP/Power Query sources.

### 7.9 `cell_context.py` — semantic chunk text builder
Produces context strings like `"P&L Summary / Adjusted EBITDA / Mar 2026 / cross_sheet_calculation / major_output"` that get embedded into Qdrant for `find_cells(tier='semantic')`.

---

## 8. The Coordinator — Claude Tool-Calling Loop

### 8.1 File: `core/rosetta/coordinator.py` (536 lines)
Public entry: `async answer(wb, state, message, *, user_id, data_source_id) -> dict`.

**Step-by-step internals:**

1. **Append user turn** to `state.messages`. **Cache check** — hash the question (sha-256 of normalized text + sorted JSON of `scenario_overrides`) against `state.answer_cache` (TTL from `ROSETTA_CACHE_TTL_SECS`, default 3600s). Cache hit returns immediately.

2. **Build Claude messages** via `_build_claude_messages(state)`. Prepends a synthetic `[Context: Active entity=..., Active scenario overrides=...]` block to the current user message so Claude can resolve pronouns like "it" and "that cell".

3. **Run the tool loop** (`_run_tool_loop`). Max `MAX_TOOL_TURNS = 10` iterations of:
    ```python
    await anthropic.AsyncAnthropic().messages.create(
        model=settings.ROSETTA_MODEL,       # claude-sonnet-4-5 default
        max_tokens=2048,
        temperature=0,
        system=COORDINATOR_SYSTEM_PROMPT,
        tools=TOOLS,                         # registry of 27+ deterministic tools
        messages=claude_messages,
    )
    ```
    On `stop_reason == "tool_use"`: each tool_use block is executed via `execute_tool(wb, name, args, user_id, data_source_id)`. Result is serialized to ≤12 KB JSON and appended as a `tool_result` content block, then the loop continues.
    Accumulates `state.turn_input_tokens` / `state.turn_output_tokens` across turns. Captures first `backward_trace` output as `trace_seen` and the last non-null `chart_data` from analytics tools.

4. **Specialist delegation** (`_maybe_delegate_to_explainer`). If the coordinator emits `<<DELEGATE_FORMULA_EXPLAINER ref=Sheet!Ref>>`, run `backward_trace(wb, ref, 3)` and splice in `formula_explainer.explain(trace, question)["prose"]` — a separate Anthropic call with a tighter, style-guided system prompt.

5. **Citation audit** — `auditor.audit(attempt_text, state.tool_call_log, wb)`:
   - `passed` → return answer, `audit_status="passed"`, `confidence=0.9`.
   - `failed` and retries remain (`MAX_AUDIT_RETRIES = 1`) → inject a violation-feedback message back into `claude_messages` and re-run the tool loop.
   - `failed` after retry → call `_build_partial_answer(...)` to produce `"I can only partially answer this: …"`, `audit_status="unknown"`, `confidence=0.3`.

6. **Post-process**:
   - `_extract_evidence_refs(tool_log)` walks every tool output for any `ref` key.
   - Update `state.active_entity` via `extract_entity_from_text(text)` regex (first canonical `Sheet!Ref`).
   - Cache if `audit_status == "passed"`.
   - Append assistant message to `state`.
   - Assemble `_tool_trail` (pseudocode-ish representation of the tool calls) for the "View Code" UI panel.

### 8.2 `COORDINATOR_SYSTEM_PROMPT` — the contract

Literally from lines 58–178 of `coordinator.py`:

> *"You are Rosetta's coordinator. You answer questions about a specific parsed Excel workbook by calling deterministic tools and, when needed, delegating to the FormulaExplainer specialist."*

**Seven CORE RULES — never violate:**
1. Every number or cell reference must come directly from a tool result.
2. Arithmetic is allowed only on values already fetched via a tool.
3. Named ranges must be cited by name **and** value together.
4. Ambiguous questions must list candidates rather than guess.
5. "I don't know" is preferred over fabrication.
6. Refs must be in canonical `Sheet!Ref` form.
7. Never fabricate refs, ranges, named ranges, or function names.

**MODE SELECTION** section — `formula` vs `tabular` vs `other` drives which tools to prefer.

**PLANNING GUIDANCE** — pattern → tool mapping, e.g.:
- *"How is X calculated?"* → `find_cells` → `backward_trace` → `delegate_to_formula_explainer`.
- *"What if X went to Y?"* → `scenario_recalc` (multi-var) or `what_if` (single-var).
- *"Top 5 by Y"* → `top_n`.
- *"Find outliers"* → `detect_outliers`.
- *"Are there any stale assumptions?"* → `list_findings(category='stale_assumption')`.

**OUTPUT STYLE**: backticks around refs/formulas/functions/named ranges/data types; `FloorPlanRate (5.8%)` style for named-range citations; one lead paragraph + one evidence paragraph.

**DELEGATION** via the `<<DELEGATE_FORMULA_EXPLAINER ref=...>>` marker.

### 8.3 `_tool_trail` — "View Code" pseudocode
The coordinator synthesizes a short readable trail of the tool calls it ran (names + args, truncated values) and returns it as `code_used`. This is surfaced to the user **not as real generated code** — Rosetta deliberately **never generates executable code**, which is why one of its trust principles is *"No string arithmetic."*

---

## 9. The Tool Registry (27+ Deterministic Tools)

File: `core/rosetta/tools.py` (1460 lines). Every tool has an Anthropic-compatible schema `{name, description, input_schema}` in the `TOOLS` list and a branch in `async execute_tool(wb, name, args, *, user_id, data_source_id) -> dict`. Any exception is caught and returned as `{"error": "<Type>: <message>"}`.

### 9.1 Graph / structural tools
| Tool | Purpose |
|---|---|
| `list_sheets` | Sheet name/rows/cols/formulas/hidden + region summaries |
| `list_named_ranges` | name, scope, resolves_to, current_value, is_dynamic |
| `get_cell(ref)` | value, formula, formula_type, semantic_label, depends_on, depended_by, named_ranges_used, is_hardcoded, is_volatile |
| `find_cells(keyword, has_formula?, tier)` | **3-tier**: `exact` (canonical ref/named range), `keyword` (substring on `semantic_label`), `semantic` (Qdrant `KnowledgeBaseService.search` filtered by `user_id`+`data_source_id`, score ≥ 0.5). `auto` tries all three. Backfills missing values via a shared `Evaluator` |
| `backward_trace(ref, max_depth=6)` | Tree of inputs (fills unevaluated leaf values via Evaluator) |
| `forward_impact(ref, max_results=100)` | Impacted cells grouped by sheet |
| `resolve_named_range(name)` | Full resolution with current value |
| `list_findings(category?)` | Stale / hardcoded / circular / volatile / hidden / broken / inconsistency |
| `what_if(target, new_value, max_results=30)` | Single-variable scenario (target = ref or named range) |
| `scenario_recalc(overrides, target_refs?)` | Multi-variable override + recompute; returns `recalculated` + `unsupported_formulas` |
| `get_workbook_summary` | Per-sheet classification (`formula` / `tabular` / `other`), per-tabular-sheet data shape via `_infer_dominant_type`, named ranges, circulars, finding counts |
| `list_pivot_tables` / `get_pivot_table(sheet, index)` | Pivot introspection (raw XML) |
| `join_on_key(sheet_a, key_column_a, sheet_b, key_column_b, select_a?, select_b?, filter_key?, max_rows=50)` | Inner join with header-or-letter column spec; uses Evaluator for formula cells |
| `compare_regions(ref_a, ref_b)` | Structural diff: `shape_match_pct`, `shape_diffs[]`, `functions_only_a/b/both`, `named_ranges_only_a/b` via `_formula_token_sequence` |
| `explain_circular(chain_index=0)` | Cycle walk + evidence (`author_comment` / `iterative_calc_setting` / `heuristic` / `none`) + prose template |

### 9.2 Analytics tools (merged from `core/rosetta/analytics/`)
| Family | Tools |
|---|---|
| Aggregators | `aggregate_column` (sum/avg/min/max/median/count/stddev), `unique_values`, `top_n`, `group_aggregate`, `histogram` |
| Filters | `filter_rows` (compact Predicate DSL: `=, !=, >, >=, <, <=, in, not_in, contains, startswith, endswith`), `lookup_row`, `scenario_filter`, `compare_scenarios` |
| **SQL (DuckDB)** | `sql_schema(wb)`, `sql_query(wb, query, limit=200, MAX=1000)` — every sheet lazily attached as an in-memory DuckDB table on `wb.__sql_conn__`. Claude can write arbitrary `SELECT … FROM "Sheet Name" WHERE … GROUP BY …` |
| Data quality | `count_missing`, `find_duplicates`, `detect_outliers (iqr/zscore)` |
| Time series | `date_range_aggregate`, `time_bucket_aggregate (daily/weekly/monthly/quarterly/annual)`, `trend_summary` (linear fit slope + R²) |
| Stats | `describe`, `correlate` (Pearson) |
| **Goal seek** | `goal_seek(target_ref, target_value, input_ref, bounds?, tolerance=1e-4, max_iter=60)` — bisection with auto-bracketing + **convergence chart data** + non-monotonicity warning |
| **Sensitivity** | `sensitivity(target_ref, input_refs?, delta=0.10, top=20)` → **tornado chart data**; `elasticity(target_ref, input_ref, delta=0.01)` → point elasticity with `_describe_elasticity` |

All analytics return a shared envelope via `build_envelope(result, evidence_range, row_count, refs, chart_data, warnings)` so the auditor can verify ranges were actually cited.

### 9.3 The `DataView` helper (analytics/view.py, 358 lines)
`DataView(sheet_name, wb, *, evaluator?)` owns: header detection, column resolution (accepts letter "B" or header label "Revenue"), row iteration, per-cell value resolution via `Evaluator`, filtering via the Predicate DSL, evidence-range serialization. Used under the hood by every tabular analytics tool.

---

## 10. The Citation Auditor — Why Rosetta Doesn't Hallucinate

File: `core/rosetta/auditor.py` (609 lines). This is the **independent gate** that runs **after** the coordinator produces a candidate answer. It does not trust the LLM's reasoning — it re-verifies every claim from first principles.

### 10.1 Public API
```python
audit(answer_text: str, tool_log: list[ToolCall], wb: WorkbookModel) -> AuditResult
# AuditResult: { status: "passed" | "failed", violations: list[str],
#                verified_numbers, verified_refs, verified_named_ranges,
#                verified_qualitative }
```

### 10.2 Extraction
Regex battery:
- `NUMBER_RE` — with/without commas, `%`, `$`.
- `DATE_RE` — masks `YYYY-MM-DD`, `M/D/YY`, and spelled-out dates (`"Jan 15, 2023"`) **before** number extraction (dates are not financial claims).
- `CELL_REF_QUOTED_RE`, `CELL_REF_SIMPLE_RE`, `RANGE_REF_QUOTED_RE`, `RANGE_REF_SIMPLE_RE`, `COORD_RE`.

### 10.3 Universe construction
- `_collect_values_from_tools(tool_log)` — walks every tool output recursively, gathering numeric values, strings containing `!` (cell refs), and `category` strings.
- `_collect_workbook_universe(wb)` — every cell value + every named-range value + every named-range name.
- `_collect_known_identifiers(wb)` — sheet names + column header labels from rows 1–3 (both original and whitespace-stripped variants).

### 10.4 Matching
- `TOLERANCE_RELATIVE = 0.005` (0.5%) and `TOLERANCE_ABSOLUTE = 0.5`.
- `_number_matches` is **sign-insensitive** — financial prose often says "loss of $93k" for a negative value; this avoids false violations.

### 10.5 Qualitative claims
Keyword → audit finding category:
- `stale` → `stale_assumption`
- `circular` → `circular`
- `hidden` → `hidden_dependency`
- `volatile` → `volatile`
- `hardcoded`/`hard-coded` → `hardcoded_anomaly`
- `deprecated` → `stale_assumption`
- `broken` → `broken_ref`

`NEGATION_TOKENS = {no, not, none, never, without, lacks, any, nothing, neither, nor, free, clean, zero, 0, can't, isn't, …}` + interrogative patterns (`"are there"`, `"is the"`, `"do any"`, `"could"`, `"would"`) trigger `_is_non_assertive(sentence)` — a qualitative claim inside a negated or interrogative sentence is **not** treated as an assertion, so "No stale assumptions" passes without a backing finding. This is covered by the regression test `core/rosetta/tests/test_auditor_negation.py`.

### 10.6 Retry loop integration
On `failed`, `format_violations_for_retry(violations)` produces a prompt fragment like:
> *"Your previous answer contained these unverified claims:\n- '5.8%' in sentence 2 not found in tool outputs or workbook universe\n- 'Sheet!XYZ99' in sentence 3 is not a valid cell reference\nPlease retry using ONLY values you have fetched via tools."*

This is injected back into `claude_messages` and the tool loop runs once more. Second failure → partial answer.

---

## 11. The Formula Explainer Specialist

File: `core/rosetta/specialists/formula_explainer.py`. A second Anthropic LLM call invoked by the coordinator via `<<DELEGATE_FORMULA_EXPLAINER ref=...>>`.

### 11.1 Style contract (8 rules)
1. Cite every number with its cell ref.
2. Resolve named ranges by name **and** value.
3. Walk the trace tree 1 level deep by default.
4. Never introduce values outside the trace.
5. Surface hardcoded / volatile / stale warnings.
6. Keep paragraphs short and scannable.
7. No string arithmetic — don't compose numbers out of parts.
8. Prefer "I can't see that in this trace" over fabrication.

### 11.2 API
```python
explain(trace: dict, original_question: str, model=None) -> {"prose": str, "warnings": []}
```
Steps: `_trim_trace(trace, max_depth=3, max_children=12)` → `_format_trace_for_prompt(trimmed)` → `anthropic.Anthropic().messages.create(max_tokens=1200, temperature=0, system=FORMULA_EXPLAINER_SYSTEM_PROMPT)`. On API key absence / SDK missing / transport failure, `_deterministic_fallback(trimmed)` produces grounded prose from the trace alone — no LLM required. This is why Rosetta degrades gracefully offline.

---

## 12. Multi-turn Memory — Sessions, Entities, Scenarios

File: `core/rosetta/conversation.py`.

### 12.1 Types
- `ChatMessage{role, content, turn_id, timestamp}`
- `ToolCall{turn_id, tool_name, input, output, latency_ms, error}`
- `CachedAnswer{question_hash, answer_text, evidence_refs, trace, confidence, audit_status, cached_at}`
- **`ConversationState{session_id, workbook_id, messages[], active_entity, scenario_overrides, answer_cache, tool_call_log, created_at, updated_at, turn_input_tokens, turn_output_tokens}`** with `append_user`, `append_assistant`, `log_tool_call`, `set_scenario`, `clear_scenario`.

### 12.2 Persistence
- In-process: `_ANSWER_CACHES: dict[conversation_id, dict[qh, CachedAnswer]]`.
- Durable: `active_entity` + `scenario_overrides` on the `conversations` table (Rosetta v2A migration).
- `async load_state(session, conversation, include_history=True)` hydrates state; `async persist_state(session, state, conversation)` writes back **only** `active_entity` + `scenario_overrides` (messages are persisted separately by `ConversationService.add_message`).
- `question_hash(question, scenario_overrides)` — sha-256 of normalized question + sorted JSON overrides, truncated to 16 hex chars.
- `extract_entity_from_text(text)` — first canonical ref via regex.

### 12.3 Why this enables composable questions
After asking *"How is Adjusted EBITDA calculated?"*, the coordinator sets `active_entity = "P&L!G32"`. The next question *"and what if FloorPlanRate went to 8%?"* comes in with `[Context: Active entity=P&L!G32]` prepended → the coordinator binds "it" to that cell and runs `what_if("FloorPlanRate", 0.08)` against it. A follow-up *"and 8.5%?"* layers another override — `scenario_overrides` grows, `scenario_recalc` reruns.

---

## 13. Pricing & Usage Tracking

File: `core/rosetta/pricing.py`.

### 13.1 Price table
```python
CLAUDE_PRICING = {
    "claude-sonnet-4-5":        (input=$3/M,  output=$15/M),
    "claude-sonnet-4-6":        (input=$3/M,  output=$15/M),
    "claude-opus-4-6":          (input=$15/M, output=$75/M),
    "claude-haiku-4-5-20251001":(input=$1/M,  output=$5/M),
}
```
`compute_cost_usd(model, input_tokens, output_tokens) -> (input_cost, output_cost, total_cost)` — all `Decimal`, quantized to 6 decimals.

### 13.2 Accounting
Every Claude call emits an `LLMUsage` row with `call_type=ASK_QUESTION`, a JSON `context` linking back to the data source, conversation, schema, and message. `ConversationService.get_user_usage_summary(user_id, days=30)` aggregates by `call_type` for the Dashboard usage card.

File-upload cost (metadata_extraction + semantic_mapping) is tracked separately in `file_upload_usage`.

---

## 14. API Surface — Every Route

All mounted under `/api/v1` via `core/api/v1/__init__.py`. Ops routes (`/health`, `/health/qdrant`, `/metrics`) are on the app root. Custom OpenAPI injects `HTTPBearer` security.

### 14.1 `/auth` (prefix `/auth`, tag `Authentication`)
| Method | Path | Body / Params | Response |
|---|---|---|---|
| GET | `/auth/google/url?redirect_uri=…` | — | `{url, redirect_uri}` |
| POST | `/auth/google/callback` | `GoogleAuthRequest{code, redirect_uri?}` | `AuthResponse{user: UserResponse, tokens: TokenResponse, message}` |
| POST | `/auth/refresh` | `RefreshTokenRequest{refresh_token}` | `TokenResponse{access_token, refresh_token, token_type='bearer', expires_in}` |

### 14.2 `/data-sources` (all `Depends(get_current_user)`)
| Method | Path | Body / Params | Response |
|---|---|---|---|
| POST | `/data-sources/upload` | multipart `name, file, auto_process=True` | `DataSourceResponse` (BackgroundTasks: process + index) |
| GET | `/data-sources` | `skip, limit` | `DataSourceListResponse{items, total}` |
| GET | `/data-sources/{id}` | — | `DataSourceResponse` |
| GET | `/data-sources/{id}/analysis` | — | `WorkbookAnalysisResponse | None` |
| POST | `/data-sources/{id}/index` | — | `IndexingResponse{chunks_indexed, status, analysis}` |
| POST | `/data-sources/search` | `KnowledgeSearchRequest{query, data_source_id?, limit}` | `KnowledgeSearchResponse` (Qdrant semantic search) |
| DELETE | `/data-sources/{id}/index` | — | `{chunks_deleted}` |
| DELETE | `/data-sources/{id}` | — | cascade delete (file + Qdrant + DB) |

### 14.3 `/excel-agent` (all auth)
| Method | Path | Body / Params | Response |
|---|---|---|---|
| POST | `/excel-agent/data-sources/{id}/process` | `ProcessDataSourceRequest{force_reprocess}` | `ProcessDataSourceResponse` (A→B→C) |
| GET | `/excel-agent/data-sources/{id}/schema` | — | `ExcelSchemaResponse` (full: manifest + semantic_schema + enrichment + query_routing) |
| GET | `/excel-agent/data-sources/{id}/schema/info` | — | `SchemaInfoResponse` |
| GET | `/excel-agent/data-sources/{id}/manifest` | — | `ManifestSummaryResponse` |
| GET | `/excel-agent/data-sources/{id}/enrichment` | — | `EnrichmentResponse` |
| **POST** | **`/excel-agent/data-sources/{id}/ask`** | `AskQuestionRequest{question, conversation_id?}` | **`AskQuestionResponse`** |
| GET | `/excel-agent/data-sources/{id}/questions/suggested` | — | `SuggestedQuestionsResponse` |
| GET | `/excel-agent/data-sources/{id}/queries/history` | `limit=50` | `QueryHistoryResponse` |
| GET | `/excel-agent/conversations` | `data_source_id?, skip, limit` | `ConversationListResponse` |
| GET | `/excel-agent/conversations/{id}` | — | `ConversationResponse` with messages |
| DELETE | `/excel-agent/conversations/{id}` | — | `204` |
| PATCH | `/excel-agent/conversations/{id}/title` | `title` query | `ConversationResponse` |
| GET | `/excel-agent/usage/summary` | `days=30` | `UsageSummaryResponse` |

### 14.4 `AskQuestionResponse` — the headline shape (`core/api/v1/schemas/excel_agent.py`)
```python
{
    # LLM core
    "success": bool, "answer": Any, "code_used": str | None,
    "iterations": int, "error": str | None,
    "execution_time_ms": int, "query_id": UUID,
    "conversation_id": UUID,
    "input_tokens": int, "output_tokens": int, "cost_usd": Decimal,

    # Rosetta extensions
    "trace": dict | None,           # TraceNode tree for FormulaModal
    "graph_data": {                  # React Flow payload
        "nodes": [...], "edges": [...],
        "focal_ref": str, "node_count": int, "edge_count": int
    } | None,
    "chart_data": {                  # Tornado / GoalSeek / Bar / Line
        "type": "tornado"|"line"|"bar"|…,
        "x"?: [...], "y"?: [...],
        "labels"?: [...], "high"?: [...], "low"?: [...],
        "baseline"?: float, "target_line"?: float,
        "x_label"?: str, "y_label"?: str
    } | None,
    "audit_status": "passed" | "partial" | "unknown",
    "evidence_refs": list[str],
    "active_entity": str | None,
    "scenario_overrides": dict
}
```

---

## 15. Frontend — Pages, Components, Styling

### 15.1 Entry points
- `src/main.tsx` — `createRoot(root).render(<StrictMode><App/></StrictMode>)` + `./index.css`.
- `src/App.tsx` — wraps router in `<AuthProvider>`:
  ```
  / → Home
  /login → Login
  /dashboard/* → Dashboard
  /data-source/:id → DataSourceDetail
  /auth/google/callback → GoogleCallback
  ```
  **No `<ProtectedRoute>` wrapper** — each protected page self-guards via `useAuth()` + `navigate('/')`.

### 15.2 `context/AuthContext.tsx`
State: `user, tokens, isLoading`. Persists to `localStorage` keys `auth_user` + `auth_tokens`. API: `login(user, tokens)`, `updateTokens(newTokens)`, `logout()`. `isAuthenticated = !!user`.

### 15.3 Pages
#### `pages/Home.tsx` (`/`)
Marketing landing. Light lavender bg (`#f5f3fb`) + `.cockpit-grid-light` overlay + two floating `.agentic-orb` blobs. Hero: *"Spreadsheets that explain themselves."* with three feature cards (Insight / Execution / Validator) and a 3-step pictogram (Upload · Reason · Trace).

#### `pages/Login.tsx` (`/login`)
Hardcoded `REDIRECT_URI = 'http://localhost:3003/auth/google/callback'`. On click → `getGoogleAuthUrl(REDIRECT_URI)` → browser redirect. Centered white card with Google G SVG button. *(Note: `vite.config.ts` runs on port 3000 — the 3003 URI is a known alignment item before demo.)*

#### `pages/GoogleCallback.tsx`
Consumes `?code=&error=`. Guarded by `useRef(false)` for React 19 StrictMode double-invocation. On success → `exchangeGoogleCode(code, REDIRECT_URI)` → `login(user, tokens)` → `/dashboard`.

#### `pages/Dashboard.tsx` (1084 lines — the workspace)
Three sections under `/dashboard/*` dispatched off `location.pathname.split('/')[2]`:

**`ask-ai` (default):**
- Header: "Rosetta" title, workbook dropdown (`dataSources`), conditional buttons — **Prepare** (triggers `processDataSource`), **Schema** (opens `<SchemaInspector>`, lazy-loads `getExcelSchema`), **New session** (clears chatHistory + conversationId).
- Metrics strip: workbook name · `sheet_count` sheets · `queryable_questions_count` suggestions · status pill.
- Empty state branches: (1) no source selected, (2) source + empty history + suggested questions (6-card grid), (3) source + empty history + no suggestions, (4) populated.
- Chat bubbles: user = right-aligned purple→blue gradient pill; assistant = left-aligned white card with "DI" avatar. Error messages in red. Assistant content via `<AnswerMarkdown>`; if `msg.trace` → "Visualise formula" button opens `<FormulaModal>` keyed on `formulaModalIdx`; if `msg.chartData` → `<AnalyticsChart>` below.
- In-flight: `.cockpit-active-pulse` ring on "DI" avatar + spinner + *"Reasoning…"*.
- Composer: auto-grow `<textarea>` (Enter=send, Shift+Enter=newline) + gradient **Send**. Disabled until a ready workbook is selected.

**`my-files`:** data-source table (Name · File · Size · Tabs · Sheet names · Created · Actions). Row click → `/data-source/:id`. Per-row **Delete** (confirm + `deleteDataSource`). **Create source** modal: name input + file input (`.xlsx,.xls,.xlsm`) → `uploadDataSource` via `withAuthRetry`.

**`conversations`:** usage summary card (total calls · input tokens · output tokens · total cost) + session list with **Continue** (`getConversation` → map messages → navigate to ask-ai) and **Delete**.

**State (exhaustive):** `dataSources`, `dataSourceTotal`, `isDataSourcesLoading`, `uploadError`, `uploadSuccess`, `dataSourceName`, `selectedFile`, `isCreateModalOpen`, `isUploadLoading`, `selectedDataSourceId`, `schemaInfo`, `workbookSchema`, `isSchemaOpen`, `isSchemaLoading`, `schemaLoadError`, `suggestedQuestions`, `question`, `isAskingQuestion`, `isProcessing`, `chatHistory`, `askError`, `currentConversationId`, `formulaModalIdx`, `conversations`, `conversationsTotal`, `isConversationsLoading`, `_selectedConversation`, `usageSummary`.

**`withAuthRetry<T>`:** runs `requestFn(access_token)`. On 401 → `refreshAuthTokens(refresh_token)` → `updateTokens` → retry. On refresh failure → `logout() + navigate('/')`. *(Duplicated verbatim in `DataSourceDetail.tsx` — flagged for refactor.)*

#### `pages/DataSourceDetail.tsx` (`/data-source/:id`)
`Promise.all([getDataSource(id), getDataSourceAnalysis(id)])`. Renders: file info stat grid, workbook analysis (purpose blockquote, formula-categories + error-types + column-purpose chips), sheet details list. CTA "Ask questions about this workbook" → `/dashboard/ask-ai`.

### 15.4 Components

| Component | Purpose |
|---|---|
| **`Layout.tsx`** | Flex row: `<Sidebar>` + main column (slim `h-12` header with user avatar, name, Sign out). Props: `children, activeNavItem?, onNavItemClick?, onNewChat?` |
| **`Sidebar.tsx`** | 256px wide lavender gradient. Brand block (glowing bulb + "Rosetta" + "Hackathon 2026"), **New session** gradient button → `onNewChat`, 3 nav items (**Workspace** `ask-ai` / **Sources** `my-files` / **History** `conversations`), **Trust principles** footer card |
| **`AnswerMarkdown.tsx`** | `react-markdown` + `remark-gfm`. Inline `<code>` → lavender pill; block code → off-white `<pre>`; `<a>` → purple underlined; `<table>` → bordered light theme |
| **`AnalyticsChart.tsx`** | Dispatcher: `type==='tornado'` → `<TornadoChart>`; `type==='line'` → `<GoalSeekConvergence>` (with/without `target_line`); `type==='bar'` → inline SVG horizontal bar |
| **`TornadoChart.tsx`** | Top 12 rows by |impact|, diverging horizontal bars around dashed baseline axis. Left bar red if `low<0` else green; right bar green if `high>0` else red. Header: `baseline <yLabel> = <value>` |
| **`GoalSeekConvergence.tsx`** | SVG polyline of iteration → target value. Purple line + deeper-purple point markers + dashed amber `target_line`. Axis labels, rotated y-label |
| **`FormulaModal.tsx`** | Portal popup, 92vw × 88vh, max 1400px. Segmented toggle **Map** (`<FormulaMap>`) / **Formula** (`<EquationChips>`) persisted in `localStorage['rosetta.formulaModal.view']`. Esc/backdrop-close, body scroll-lock |
| **`FormulaMap.tsx`** (~455 lines) | Horizontal `react-d3-tree` of rounded-rect nodes. Sign palette: focal=blue, positive=emerald, negative=red, zero=slate. Canvas `#faf7f2` cream. **`<foreignObject>` HTML-inside-SVG trick** so Inter/JetBrains-Mono render reliably. Per-depth sizing. Collapsed-count badge. Legend at bottom-left |
| **`EquationChips.tsx`** | Formula displayed + signed chips for each direct precedent (regex the parent formula's operator adjacent to child coord). +=emerald, –=rose, ×=indigo. Terminal-value state "no dependencies" |
| **`SchemaInspector.tsx`** (~442 lines) | ER-diagram modal (SVG). **Prefers backend `enrichment.cross_sheet_relationships`** (accepts multiple key shapes), falls back to column-name overlap inference (ignoring generic names `month,date,notes,type,name`). Column-dot colors by `semantic_role`. 3-column grid layout; Bézier edges with rounded pill labels |
| **`DependencyGraphCard.tsx`** | ReactFlow + Dagre LR auto-layout for the full dependency graph (`DependencyGraphData`). Custom `CellNode` with per-sheet palette. **Built but not yet wired into Dashboard** — low-risk add-in |

### 15.5 API client (`src/api/`)
- **`api/auth.ts`**: `API_BASE_URL = 'http://localhost:8000/api/v1'`. `User`, `Tokens{access_token, refresh_token, token_type, expires_in}`, `AuthResponse`. Functions: `getGoogleAuthUrl`, `exchangeGoogleCode`, `refreshAuthTokens`.
- **`api/dataSources.ts`**: `ApiError extends Error {status}`. Types: `DataSource`, `DataSourceListResponse`, `SheetInfo`, `WorkbookAnalysisSummary`, `WorkbookAnalysis`. Functions: `listDataSources`, `uploadDataSource` (multipart), `getDataSource`, `getDataSourceAnalysis`, `deleteDataSource`.
- **`api/excelAgent.ts`** — the core. Types: `ProcessDataSourceResponse`, `ExcelSchemaResponse`, `SchemaInfoResponse`, `DependencyGraphNodeData`, `DependencyGraphNode/Edge/Data`, `AnalyticsChartData`, **`TraceNode`**, **`AskQuestionResponse`**, `SuggestedQuestionsResponse`, `QueryHistoryItem`, `ConversationMessage`, `Conversation`, `UsageSummaryResponse`. Functions: `processDataSource`, `getExcelSchema`, `getSchemaInfo`, `askQuestion`, `getSuggestedQuestions`, `getQueryHistory`, `listConversations`, `getConversation`, `deleteConversation`, `getUsageSummary`.

### 15.6 Styling system (`src/index.css`)
Tailwind v4 (`@import "tailwindcss"`). **Design tokens in `:root`:**
```
--bg-page:       #f5f3fb      (lavender off-white)
--bg-card:       #ffffff
--bg-sidebar:    linear-gradient(180deg, #fdfcff, #f3f1fb)
--bg-subtle:     #f9f8fd
--border:        #e3e5ee
--border-strong: #d0d3df
--text-primary:  #0f1020
--text-muted:    #5a5c70
--text-subtle:   #7a7d92
--accent:        #8243EA     (signature purple)
--accent-2:      #2563EB     (blue)
--accent-deep:   #5b21b6
--accent-soft:   rgba(130,67,234,0.10)
--status-ok:     #10b981
--status-warn:   #f59e0b
--status-err:    #ef4444
```
**Signature gradient** `linear-gradient(135deg,#8243EA,#2563EB)` on brand icon, send button, user chat bubble.
**13 keyframes + utility classes** — `.agentic-orb` (floating lavender blob), `.agentic-slide-up` (420 ms entrance), `.bulb-glow` (filter drop-shadow oscillation), `.cockpit-grid-light` (24px dotted grid), `.cockpit-active-pulse` (1.6s expanding ring on reasoning avatar), `.cockpit-glow-border` (purple↔blue border animation), etc.
**Body:** font-family UI-sans-serif stack, `-webkit-font-smoothing: antialiased`, `text-rendering: optimizeLegibility`.

---

## 16. End-to-End Query Flow (Input → Output)

*This is the master flow — the one slide you want on your demo.*

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ 1. USER TYPES QUESTION                                                      │
│    e.g. "How is Adjusted EBITDA calculated, and what if FloorPlanRate       │
│          went to 8%?"                                                       │
└─────────────────────────────────────────────────────────────────────────────┘
                                     │
                                     ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ 2. FRONTEND                                                                 │
│    Dashboard.tsx → handleAskQuestion(text)                                  │
│    withAuthRetry(token => askQuestion(token, dataSourceId, text, convoId))  │
│    POST /api/v1/excel-agent/data-sources/{id}/ask                           │
└─────────────────────────────────────────────────────────────────────────────┘
                                     │
                                     ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ 3. FASTAPI MIDDLEWARE                                                       │
│    CORS → SecurityHeaders → LoggingMiddleware (X-Correlation-ID)            │
│    get_current_user → AuthService.verify_access_token(bearer)               │
└─────────────────────────────────────────────────────────────────────────────┘
                                     │
                                     ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ 4. ExcelAgentService.ask_question                                           │
│    • load/create Conversation                                               │
│    • rosetta.parser.parse_workbook(stored_file_path) → WorkbookModel        │
│    • rosetta.audit.audit_workbook(wb) → wb.findings[]                       │
│    • conversation.load_state(session, convo) → ConversationState            │
│      (includes active_entity, scenario_overrides from DB)                   │
│    • check state.answer_cache[question_hash] → maybe short-circuit          │
└─────────────────────────────────────────────────────────────────────────────┘
                                     │
                                     ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ 5. COORDINATOR (coordinator.answer)                                         │
│                                                                             │
│    a. Build Claude messages:                                                │
│       system = COORDINATOR_SYSTEM_PROMPT (7 core rules, mode selection,     │
│                planning guidance, output style, delegation marker)          │
│       messages = history + "[Context: Active entity=P&L!G32,                │
│                              Active scenario overrides={…}]\n\n{question}"  │
│                                                                             │
│    b. Tool loop (max 10 turns):                                             │
│       await AsyncAnthropic().messages.create(                               │
│         model="claude-sonnet-4-5", tools=TOOLS,                             │
│         temperature=0, max_tokens=2048)                                     │
│                                                                             │
│       Turn 1 → Claude thinks "I need to find the EBITDA cell"               │
│                tool_use: find_cells(keyword="Adjusted EBITDA", tier="auto")│
│                execute_tool → {candidates:[{ref:"P&L!G32", label:…}]}       │
│       Turn 2 → tool_use: backward_trace(ref="P&L!G32", max_depth=6)         │
│                execute_tool → TraceNode tree                                │
│       Turn 3 → tool_use: what_if(target="FloorPlanRate", new_value=0.08)    │
│                execute_tool → {deltas:[…], chart_data:None}                 │
│       Turn 4 → stop_reason="end_turn"                                       │
│                text: "Adjusted EBITDA (`P&L!G32`) is calculated as …        │
│                       At `FloorPlanRate` = 8%, it drops from $1.2M to $990k"│
│                                                                             │
│    c. Specialist delegation (if <<DELEGATE_FORMULA_EXPLAINER ref=…>>):      │
│       backward_trace(wb, ref, 3) →                                          │
│       formula_explainer.explain(trace, question) →                          │
│       anthropic.Anthropic().messages.create(system=FORMULA_EXPLAINER_…,     │
│         max_tokens=1200, temperature=0)                                     │
│       → splice prose into answer                                            │
│                                                                             │
│    d. Citation audit: auditor.audit(text, tool_log, wb)                     │
│       • extract every number/ref/named-range/qualitative claim              │
│       • build universe: (tool outputs) ∪ (wb.cells values) ∪                │
│                         (named-range values) ∪ (sheet+header identifiers)   │
│       • match each extracted number with 0.5% / 0.5 tolerance,              │
│         sign-insensitive                                                    │
│       • qualitative claims must be backed by a matching AuditFinding        │
│         category; negated/interrogative sentences auto-pass                 │
│       passed  → confidence 0.9, audit_status="passed", ship                 │
│       failed¹ → inject violation feedback, re-run tool loop                 │
│       failed² → _build_partial_answer, confidence 0.3, status="unknown"    │
│                                                                             │
│    e. Post-process:                                                         │
│       • extract evidence_refs from all tool outputs                         │
│       • active_entity = first canonical ref in answer                       │
│       • cache if passed (state.answer_cache[question_hash])                 │
│       • _tool_trail = pseudocode trail of tool calls (for "View Code")      │
└─────────────────────────────────────────────────────────────────────────────┘
                                     │
                                     ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ 6. POST-COORDINATOR                                                         │
│    • rosetta.pricing.compute_cost_usd(model, input_tokens, output_tokens)   │
│    • ConversationService.record_llm_usage(call_type=ASK_QUESTION, …)        │
│    • ConversationService.add_message(user_msg)                              │
│    • ConversationService.add_message(assistant_msg)                         │
│    • conversation.persist_state (writes active_entity, scenario_overrides)  │
│    • bridge.coordinator_to_service_result:                                  │
│      - graph_data = trace_to_graph(trace) if trace else None                │
│      - code_used = _tool_trail_from_result(…)                               │
│      - audit_status, evidence_refs, active_entity, scenario_overrides       │
└─────────────────────────────────────────────────────────────────────────────┘
                                     │
                                     ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ 7. RESPONSE TO BROWSER                                                      │
│    AskQuestionResponse = {                                                  │
│      success, answer, code_used, trace, graph_data, chart_data,             │
│      audit_status, evidence_refs, active_entity, scenario_overrides,        │
│      input_tokens, output_tokens, cost_usd, execution_time_ms,              │
│      query_id, conversation_id                                              │
│    }                                                                        │
└─────────────────────────────────────────────────────────────────────────────┘
                                     │
                                     ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ 8. RENDER                                                                   │
│    • AnswerMarkdown renders `answer` (backticked refs become lavender pills)│
│    • if trace → "Visualise formula" button → FormulaModal                   │
│       Map view:   FormulaMap (react-d3-tree + foreignObject HTML nodes)     │
│       Formula:    EquationChips (signed precedent breakdown)                │
│    • if chart_data → AnalyticsChart dispatches to Tornado / GoalSeek / Bar  │
│    • evidence_refs + audit_status available (future surfaces)               │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 17. Authentication & Security

### 17.1 Google OAuth flow
1. Frontend: user clicks "Continue with Google" → `getGoogleAuthUrl(redirectUri)` → `GET /api/v1/auth/google/url` returns the Google consent URL.
2. Google redirects to `redirect_uri?code=…`. Frontend posts `{code, redirect_uri}` → `POST /api/v1/auth/google/callback`.
3. `AuthService.authenticate_with_google_code` uses `httpx.AsyncClient` to hit `https://oauth2.googleapis.com/token` (exchange) then `userinfo` (profile), upserts a `User` with `auth_provider='google'`.
4. `AuthService.create_tokens(user)` issues HS256 JWT access (30 min) + refresh (7 d) with payloads `{sub, email, exp, iat, type}`.
5. Frontend persists to `localStorage` (`auth_user`, `auth_tokens`).
6. `POST /api/v1/auth/refresh` exchanges a refresh token for a fresh pair.

### 17.2 `get_current_user` dependency
`core/dependencies/auth.py` — extracts Bearer via `HTTPBearer(auto_error=False)` → `AuthService.verify_access_token` → loads User → raises `AuthenticationError` if missing or inactive.

### 17.3 Middleware
Order (outermost first): **CORS → SecurityHeaders → LoggingMiddleware → app**.
- `SecurityHeadersMiddleware`: `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `X-XSS-Protection: 1; mode=block`, HSTS (prod), full `Referrer-Policy`, `Content-Security-Policy` (relaxed for `/docs`, `/redoc`, `/openapi.json`), `Permissions-Policy` (locks geolocation/mic/camera/payment/usb/magnetometer/gyroscope/speaker), `X-Permitted-Cross-Domain-Policies: none`, removes `Server`.
- `LoggingMiddleware`: reads/sets `X-Correlation-ID` (ContextVar), logs method, URL, client IP, user-agent, computes `process_time_ms`, attaches `X-Correlation-ID` and `X-Trace-ID` (from OTel) to response.
- `CORSMiddleware`: env-driven origins via `CORS_ALLOWED_ORIGINS` / `CORS_ALLOW_ALL_ORIGINS`, credentials + expose-headers `X-Correlation-ID`, `X-Trace-ID`.

### 17.4 Rate limiting
`core/utils/rate_limit.py` — `slowapi.Limiter` with Redis storage, keyed by `get_user_identifier` (user_id from `request.state.user`, IP fallback), fixed-window strategy, enabled via `RATE_LIMIT_ENABLED`. Available as a decoration utility (not globally applied in `server.py`).

### 17.5 Exceptions (`core/exceptions/`)
`AIpalBaseException` + `ValidationError, NotFoundError, AuthenticationError, AuthorizationError, DatabaseError, CacheError, BusinessLogicError, ExternalServiceError, ConfigurationError`. Handlers: `aipal_exception_handler`, `validation_exception_handler`, `http_exception_handler`, `starlette_http_exception_handler`, `database_exception_handler` (IntegrityError), `database_operational_exception_handler` (OperationalError), `generic_exception_handler` (catch-all).

---

## 18. Observability Stack

### 18.1 `core/observability.py` (540 lines)
Full OpenTelemetry wiring (traces + metrics + logs).
- Sets `PROMETHEUS_MULTIPROC_DIR` **before** the first `prometheus_client` import for multi-worker mode.
- `init_observability()`:
  - Builds OTel `Resource` with service name/version.
  - `TracerProvider` with `TraceIdRatioBased(TRACE_SAMPLING_RATE)`.
  - OTLP HTTP trace exporter → `JAEGER_AGENT_URL` (default `http://localhost:4318`).
  - OTLP log exporter (conditionally — Jaeger all-in-one doesn't support OTLP logs fully, so `JAEGER_LOGS_ENABLED=False` default).
  - `PrometheusMetricReader` + `MeterProvider`.
- `instrument_app(app)` — `FastAPIInstrumentor.instrument_app(app)`, `SQLAlchemyInstrumentor`, `RedisInstrumentor`.
- `shutdown_observability()` flushes in reverse.

### 18.2 `core/logging.py`
`structlog` configured JSON (prod) / text (dev). `correlation_id_var: ContextVar[Optional[str]]` propagates across async boundaries. Processors add `correlation_id`, service info, and OTel `trace_id`/`span_id` to every log record.

### 18.3 Metrics
`GET /metrics` on app root (not under `/api/v1`) exposes Prometheus text via `generate_latest()`.

### 18.4 `monitoring/`
- `prometheus.yml` — scrape configs for `prometheus` (self), `aipal-backend` (port 8000 `/metrics`, 10s), `aipal-backend-internal-metrics` (port 8001, 15s).
- `grafana/datasources/` — provisioned datasources directory.
- `scripts/setup_jaeger.sh` — local Jaeger bootstrap.

---

## 19. Caching Strategy

Two distinct caches:

### 19.1 Service-layer Redis cache (`core/cache/`)
- `Cache = CacheManager()` singleton, initialized in `server.py` lifespan: `Cache.init(backend=RedisBackend, key_maker=CustomKeyMaker)`.
- `@Cache.cached(prefix, tag, ttl=60, fallback_on_error=True)` decorator.
- `RedisBackend`: lazy `redis.asyncio` pool, 30s health-check interval, pickle serialization (`ujson` imported but pickle used — documented in bandit skips).
- `CustomKeyMaker` (232 lines) builds deterministic keys from function signature + args (sha-256 hashed).
- `tenant_cache.py` (523 lines) provides multi-tenant helpers with per-tenant tag invalidation.
- `metrics.py` publishes Prometheus counters/histograms for hits/misses/latency.

### 19.2 Rosetta in-process answer cache
- `state.answer_cache: dict[question_hash, CachedAnswer]` on `ConversationState`.
- TTL = `ROSETTA_CACHE_TTL_SECS` (default 3600 s).
- Key = sha-256 of (normalized question + sorted JSON of `scenario_overrides`), truncated to 16 hex.
- Only `audit_status="passed"` answers are cached.
- Module-level `_ANSWER_CACHES: dict[conversation_id, dict[qh, CachedAnswer]]` persists across requests within a process.

The ask-question path currently uses **only** the Rosetta in-process cache. The Redis cache infrastructure is available for future service-layer decoration.

---

## 20. Configuration & Feature Flags

File: `core/config.py`. `Settings(BaseSettings)` reads `.env` with `case_sensitive=True`.

**App:** `APP_NAME, APP_VERSION=0.1.0, ENVIRONMENT ∈ {DEVELOPMENT, PRODUCTION, TESTING}, DEBUG, HOST=0.0.0.0, PORT=8000`.
**DB:** `DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/intellegent-excel, DATABASE_ECHO, DATABASE_POOL_SIZE=10, DATABASE_MAX_OVERFLOW=5, POOL_TIMEOUT=30, POOL_RECYCLE=1800, POOL_PRE_PING=True`.
**Redis:** `REDIS_URL`.
**Rate limit:** `RATE_LIMIT_ENABLED=True`.
**Cache:** `CACHE_ENABLED=True, CACHE_DEFAULT_TTL=300, CACHE_MAX_CONNECTIONS=50`.
**Log:** `LOG_LEVEL=INFO, LOG_FORMAT=json`.
**OTel:** `OTEL_SERVICE_NAME=excel-services, JAEGER_ENABLED=True, JAEGER_LOGS_ENABLED=False, JAEGER_AGENT_URL=http://localhost:4318, TRACE_SAMPLING_RATE=1.0`.
**Prometheus:** `ENABLE_METRICS=True, PROMETHEUS_MULTIPROC_DIR=/tmp/prometheus_multiproc_dir`.
**Security headers:** `X_FRAME_OPTIONS=DENY`, HSTS 1y `includeSubDomains`, `REFERRER_POLICY=strict-origin-when-cross-origin`, full CSP, permissions-policy locking geolocation/mic/camera/payment/usb/magnetometer/gyroscope/speaker.
**CORS:** `CORS_ALLOWED_ORIGINS=[…], CORS_ALLOW_ALL_ORIGINS=False, CORS_ALLOW_CREDENTIALS=True, CORS_EXPOSE_HEADERS=["X-Correlation-ID","X-Trace-ID"], CORS_MAX_AGE=86400`.
**JWT:** `JWT_SECRET_KEY, JWT_ALGORITHM=HS256, access=30min, refresh=7d`.
**Google OAuth:** `GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_REDIRECT_URI`.
**Data source:** `DATA_SOURCE_UPLOAD_DIR=./uploads/data_sources, DATA_SOURCE_MAX_FILE_SIZE_MB=25, DATA_SOURCE_ALLOWED_EXTENSIONS=[.xlsx,.xls,.xlsm,.csv]`.
**LLMs:** `GOOGLE_GEMINI_API_KEY, OPENAI_API_KEY, ANTHROPIC_API_KEY, ROSETTA_MODEL=claude-sonnet-4-5, AGENT_LLM_PROVIDER=gemini, AGENT_LLM_MODEL=gemini-1.5-pro, AGENT_MAX_ITERATIONS=10, AGENT_TIMEOUT_SECONDS=120`.
**Qdrant:** `QDRANT_HOST=localhost, QDRANT_PORT=6333, QDRANT_GRPC_PORT=6334, QDRANT_API_KEY, QDRANT_PREFER_GRPC=False, QDRANT_TIMEOUT=30`.
**Embeddings:** `EMBEDDING_PROVIDER=openai, EMBEDDING_MODEL=text-embedding-3-small, EMBEDDING_DIMENSION=1536, EMBEDDING_BATCH_SIZE=100`.
**Knowledge base:** `KNOWLEDGE_COLLECTION_NAME=excel_knowledge, KNOWLEDGE_CHUNK_SIZE=500, KNOWLEDGE_CHUNK_OVERLAP=50`.

**Coordinator-specific env flags** (read by `coordinator.py` directly):
- `ROSETTA_CACHE_TTL_SECS` (default 3600)
- `ROSETTA_SEMANTIC_DISABLED=1` to disable Qdrant-backed `find_cells(tier='semantic')`.

---

## 21. Deployment (Docker Compose)

`docker-compose.yml` — 4 services + 4 named volumes:

| Service | Image | Host port → Container | Volume |
|---|---|---|---|
| `excel-services` | (built from `Dockerfile`) | 8010 → 8000 | — |
| `postgres` | `postgres:16-alpine` (db `intellegent-excel`) | 5434 → 5432 | `postgres_data` |
| `redis` | `redis:7-alpine` | 6380 → 6379 | `redis_data` |
| `qdrant` | `qdrant/qdrant:v1.9.7` | 6335 (REST) / 6336 (gRPC) | `qdrant_data`, `qdrant_snapshots` |

**Dockerfile:** multi-stage `python:3.12-slim`, non-root `appuser`, healthcheck hits `/health`.

**Makefile targets:** `install`, `dev-setup`, `dev` (runs `main.py`), `test`, `test-cov`, `lint`, `typecheck`, `format`, `up`, `down`, `logs`, `shell`, `migrate`, `init-db`, `db-up`, `db-down`, `ui-install`, `ui-dev`, `ui-build`.

**`run-dev.sh`:** unsets `ANTHROPIC_API_KEY` (forces pydantic-settings to load from `.env`, avoiding Claude Desktop's inherited empty env) then `exec make dev`.

**`main.py`:** literally `uvicorn.run("core.server:app", host=settings.HOST, port=settings.PORT, reload=settings.DEBUG, ...)`.

---

## 22. User Journey

### 22.1 First-time user
1. Lands on `/` → sees hero + 3 feature cards → clicks **Login**.
2. `/login` → "Continue with Google" → `GET /api/v1/auth/google/url?redirect_uri=…` → Google consent.
3. Google redirects back to `/auth/google/callback?code=…` → `POST /api/v1/auth/google/callback` → localStorage gets `auth_user` + `auth_tokens` → `/dashboard/ask-ai`.
4. On arrival: `GET /api/v1/data-sources?skip=0&limit=50` → empty list → the chat canvas shows the "Ask a question. Get a defensible answer." hero with an **Upload a workbook** CTA.
5. Clicks CTA → section `my-files` → **Create source** modal → uploads `.xlsx` → `POST /api/v1/data-sources/upload` (multipart, `auto_process=True`) → background task runs A→B→C + Qdrant indexing.
6. Returns to `ask-ai` → picks the new source from the dropdown → `GET /excel-agent/data-sources/{id}/schema/info`. If status ≠ ready → **Prepare** button → `POST /excel-agent/data-sources/{id}/process` with `force_reprocess=false`.
7. Once ready → `GET /excel-agent/data-sources/{id}/questions/suggested` → 6 suggestion cards appear.
8. Optional: clicks **Schema** → `<SchemaInspector>` opens, lazy-fires `GET /excel-agent/data-sources/{id}/schema` → ER diagram renders.

### 22.2 Asking a question
9. Clicks a suggestion or types → `POST /excel-agent/data-sources/{id}/ask` with `{question, conversation_id}` → `AskQuestionResponse`.
10. Frontend: assistant bubble with `AnswerMarkdown`, plus optional buttons:
    - **Visualise formula** (if `trace`) → `<FormulaModal>` toggles Map ↔ Formula view.
    - `<AnalyticsChart>` (if `chart_data`) → tornado / goal-seek / bar.
11. `currentConversationId` updated from response; `active_entity` + `scenario_overrides` round-tripped.

### 22.3 Multi-turn follow-ups
12. *"And what if the floor-plan rate went to 8%?"* → next `/ask` carries the same `conversation_id` → backend loads state → `[Context: Active entity=P&L!G32, Active scenario overrides={}]` prepended to message → coordinator runs `what_if` and composes against prior turn.

### 22.4 Session management
13. **New session** button (Sidebar or header) → clears `chatHistory` + `currentConversationId` in state → next question starts a fresh `Conversation` row.
14. **History** section → `GET /excel-agent/conversations` + `GET /excel-agent/usage/summary?days=30` → cards list with **Continue** (loads messages back into chat) and **Delete** actions.

### 22.5 Data source browsing
15. Row click in `my-files` → `/data-source/:id` → `Promise.all([getDataSource, getDataSourceAnalysis])` → detailed sheet analysis surface. CTA jumps back to ask-ai.

### 22.6 Token refresh / sign out
16. Any 401 → `withAuthRetry` → `POST /api/v1/auth/refresh` → updates tokens → retries. Refresh failure → `logout()` + `/`.
17. Header **Sign out** → `AuthContext.logout()` (clears localStorage) → `/`.

---

## 23. Key Design Principles & Differentiators

1. **Refuses to hallucinate by architecture, not by prompting alone.** The citation auditor is an independent gate that re-verifies every number/ref/named-range/qualitative claim against the workbook + tool-output universe. Two strikes → partial answer with `confidence=0.3`, not a confident fake. Negation/interrogative detection avoids false negatives on "No, there are no stale assumptions."

2. **Tools, not code.** Rosetta **never asks the LLM to generate executable code**. All computation happens in 27+ deterministic Python tools. "No string arithmetic" — the model can only cite values it actually fetched. `code_used` in the API is a **pseudocode trail** for transparency, not something that was ever executed.

3. **Two LLM specialists, same API budget.** The coordinator (Claude Sonnet 4.5, tool loop) handles routing. The FormulaExplainer (same model, different system prompt) produces grounded prose explanations of formula trees. Both degrade gracefully — FormulaExplainer has a deterministic fallback when the API is unavailable.

4. **SQL bridge is real.** Every sheet becomes a DuckDB in-memory table attached to the `WorkbookModel`. Claude can write arbitrary `SELECT x, AVG(y) FROM "Sheet Name" WHERE CAST(col AS DOUBLE) > 100 GROUP BY x` — the audit gate ensures the results can't be manipulated in prose.

5. **Multi-turn memory is real memory.** `active_entity` and `scenario_overrides` persist to Postgres (Rosetta v2A migration). "And what if it were 8%?" composes against the prior turn's cell reference and accumulated overrides.

6. **Three-tier cell lookup.** `find_cells` tries `exact` (canonical ref or named range), `keyword` (substring on `semantic_label`), and `semantic` (Qdrant KNN filtered by tenant + workbook) — so "adjusted EBITDA" finds `P&L!G32` even when the header wording varies.

7. **Graph visualization is free.** `trace_to_graph` converts the backward-trace tree into a React Flow payload with no additional LLM call. The `FormulaMap` renders it with `react-d3-tree` and uses `<foreignObject>` to embed HTML text inside SVG so Inter/JetBrains-Mono render reliably.

8. **Analytics tools return renderable chart payloads.** `sensitivity` → tornado chart. `goal_seek` → convergence chart. The frontend dispatches on `chart_data.type` via `<AnalyticsChart>`.

9. **Defensibility scaffolding throughout.** `audit_status`, `evidence_refs`, `confidence` flow through the API — the frontend already consumes `trace`/`graph_data`/`chart_data`, and `audit_status`/`evidence_refs` are available for future surfaces (e.g. a "View reasoning" tab à la 3001).

10. **Design system baked in.** Lavender off-white theme (`#f5f3fb`) with signature purple→blue gradient (`#8243EA → #2563EB`). Inter / JetBrains Mono loaded at document level. 13 custom keyframes for subtle motion (orb float, bulb glow, active-pulse reasoning ring, progress shimmer, glow border). Trust principles pinned to the Sidebar footer: *"No black boxes · No string arithmetic · No orphan answers."*

---

## 24. Glossary

| Term | Meaning |
|---|---|
| **Manifest** (Phase A) | Pure-openpyxl `WorkbookManifest` — cells, merges, colors, sections, header rows. No LLM involved. |
| **Semantic schema** (Phase B) | Legacy LLM-produced JSON schema for the workbook. Retained as fallback. |
| **Enrichment** (Phase C) | Domain-aware JSON (time dim, key metrics, dimensions, tables, cross-sheet relationships, retrieval hints, context header). Feeds both the Q&A prompt and the ER diagram. |
| **Context header** | 3–5 sentence grounding paragraph injected into every Q&A prompt to orient the model to the workbook domain. |
| **Active entity** | Current cell ref the conversation is anchored on. Persisted on the `conversations` row. Enables pronoun resolution in follow-ups. |
| **Scenario overrides** | JSONB dict of name/value pairs currently applied by `scenario_recalc`. Persisted on the `conversations` row. |
| **Backward trace** | Tree of all input cells feeding a formula (up to `max_depth`). Renders as `FormulaMap` via `react-d3-tree`. |
| **Forward impact** | BFS over `depended_by` from a cell — "who else will break if this changes?" |
| **Citation auditor** | Independent gate (regex + workbook universe) that verifies every claim in the final answer. |
| **Coordinator** | Claude tool-calling loop (max 10 turns) over the deterministic tool registry. |
| **FormulaExplainer** | Claude specialist invoked via `<<DELEGATE_FORMULA_EXPLAINER ref=…>>` for prose formula explanations. |
| **Tool trail (`code_used`)** | Pseudocode-ish representation of the tools the coordinator called. Shown in the UI for transparency — **never executed**. |
| **Evidence refs** | Cell refs extracted from every tool output during a turn; used for the citation list. |
| **Trust principles** | Product-level rules: no black boxes (every claim traceable), no string arithmetic (numbers only from tools), no orphan answers (every claim has evidence). |
| **Qdrant semantic tier** | `find_cells(tier='semantic')` — queries the `excel_knowledge` collection with `user_id + data_source_id` filter, score_threshold 0.5. |
| **DuckDB SQL bridge** | Each sheet lazily attached as an in-memory DuckDB table on `WorkbookModel.__sql_conn__`. Powers the `sql_query` tool. |

---

*Document generated from live codebase recon on 2026-04-17.*
