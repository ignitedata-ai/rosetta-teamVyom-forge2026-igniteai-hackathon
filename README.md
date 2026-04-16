# Intelligent Excel Services

**Ask natural-language questions about complex Excel workbooks and get grounded answers — every number cited, every cell reference verified, no hallucinations.**

## What this is

A production-grade web service + React UI that answers questions about uploaded `.xlsx` workbooks. Built around a **citation-audited agentic coordinator** (Claude Sonnet 4.5) that calls deterministic tools over a parsed workbook graph instead of generating Python code. If the coordinator cannot verify a claim against tool outputs, the system says *"I don't know"* — never a guess.

Core capabilities:
- **Formula understanding** — "How is Adjusted EBITDA calculated?" → traces the full dependency chain across sheets with named-range resolution
- **Dependency analysis** — "Which cells depend on Floor Plan Rate?" → forward impact graph
- **What-if scenarios** — "What if FloorPlanRate went to 7%?" → real recomputation of all impacted cells, multi-scenario composable
- **Structural audit** — stale assumptions, circular references, hardcoded anomalies, volatile functions
- **Grounded narrative** — a FormulaExplainer specialist writes prose answers constrained by the tool-returned trace

## Quickstart

```bash
# 1. Prerequisites
#    - Docker Desktop running
#    - Python 3.12+ available (uv will install if needed)
#    - Node 18+ for the UI

# 2. Install uv
pip install uv

# 3. Python deps (creates .venv)
uv sync --frozen --python 3.12

# 4. Env file
cp .env.example .env
#    Edit .env to add your real values:
#      - ANTHROPIC_API_KEY  (from https://console.anthropic.com/settings/keys)
#      - OPENAI_API_KEY     (for embeddings + workbook pre-processing)
#      - GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET (for OAuth login)

# 5. Start DBs
make db-up
uv run alembic upgrade head

# 6. Start backend (port 8000)
make dev

# 7. In another terminal, start UI (port 3000)
make ui-install
make ui-dev

# 8. Open http://localhost:3000 → log in with Google → upload a workbook → ask.
```

See `docs/runbook.md` for full setup, ports, troubleshooting, and deployment.

## Architecture in one diagram

```
┌─ Frontend (React + Vite, port 3000) ──────────────────┐
│  Google OAuth • Upload • Ask AI • Conversations       │
└───────────────────────┬───────────────────────────────┘
                        │ JWT-authenticated REST
┌───────────────────────▼────────────────────────────────┐
│ FastAPI backend (port 8000)                            │
│                                                         │
│ Upload path (one-time per workbook):                   │
│   /ingest → parse → extract → map → enrich → Qdrant    │
│                                                         │
│ Q&A path (every question):                             │
│   /ask → ExcelAgentService.ask_question()              │
│         ↓                                               │
│   core.rosetta.coordinator                             │
│     • Claude Sonnet 4.5, tool-calling loop             │
│     • deterministic tools over parsed workbook         │
│     • FormulaExplainer specialist (optional)           │
│     • Citation auditor (post-answer gate)              │
└────┬───────────────────────────────────────────┬───────┘
     │                                            │
┌────▼─────────┐  ┌────────────┐  ┌─────────────▼──────┐
│ PostgreSQL   │  │ Redis      │  │ Qdrant             │
│ users/files/ │  │ cache      │  │ OpenAI embeddings  │
│ conversations│  │            │  │ workbook chunks    │
└──────────────┘  └────────────┘  └────────────────────┘
```

Full architecture details in `docs/architecture.md`.

## Layout

```
├── main.py                  # uvicorn entry
├── pyproject.toml           # Python deps (uv)
├── Makefile                 # common commands (dev, db-up, migrate, ui-dev)
├── Dockerfile               # multi-stage build
├── docker-compose.yml       # postgres + redis + qdrant + app
├── alembic/                 # DB migrations
├── core/
│   ├── api/v1/              # FastAPI routes (auth, data_sources, excel_agent)
│   ├── agents/              # upload pipeline: extractor, mapper, enricher, orchestrator
│   ├── rosetta/             # Q&A engine: coordinator + auditor + tools + specialists
│   │   ├── coordinator.py
│   │   ├── auditor.py
│   │   ├── tools.py
│   │   ├── bridge.py
│   │   ├── pricing.py
│   │   ├── specialists/formula_explainer.py
│   │   └── tests/
│   ├── services/            # ExcelAgentService, ConversationService, etc.
│   ├── models/              # SQLAlchemy models
│   ├── vector/              # OpenAI embedder + Qdrant wrapper
│   ├── security/, cache/, middlewares/, exceptions/, ...
│   └── server.py            # FastAPI app factory
├── ui/                      # React + Vite frontend
├── data/                    # sample workbooks for demos
├── uploads/                 # user-uploaded files (gitignored when populated)
└── docs/
    ├── architecture.md
    └── runbook.md
```

## License

Internal / hackathon project. No external license.
