# Runbook

## Ports

| Service | Port | Image / process |
|---|---|---|
| Backend (FastAPI) | **8000** | `uv run python main.py` |
| Frontend (Vite) | **3000** | `npm run dev` in `ui/` |
| Postgres | 5432 | `postgres:16-alpine` in Docker |
| Redis | 6379 | `redis:7-alpine` in Docker |
| Qdrant REST | 6333 | `qdrant/qdrant:v1.9.7` in Docker |
| Qdrant gRPC | 6334 | (same container) |

If any of these conflict on your machine, either stop the other process or override via `.env` (`PORT=...`) and Vite config (`ui/vite.config.ts`).

## Prerequisites

- macOS / Linux
- Docker Desktop running
- Python 3.12+ (uv will download if absent)
- Node 18+
- `uv` package manager (`pip install uv`)

## Environment file

```bash
cp .env.example .env
```

Edit `.env` and fill in:

| Variable | Where from | Required? |
|---|---|---|
| `ANTHROPIC_API_KEY` | https://console.anthropic.com/settings/keys | **Yes** — Rosetta coordinator |
| `OPENAI_API_KEY` | https://platform.openai.com/api-keys | **Yes** — embeddings + upload-pipeline agents |
| `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` | Google Cloud Console → OAuth credentials | **Yes** — login |
| `JWT_SECRET_KEY` | Generate any strong random string | **Yes** — local JWTs |
| `QDRANT_API_KEY` | Blank for local; set for Qdrant Cloud | No |

`.env` is gitignored. `.env.example` is safe to commit.

> **Note on shell environment variables.** Some shells have `ANTHROPIC_API_KEY=""` exported globally (empty string). Pydantic Settings prefers shell env over `.env`, so the empty shell value wins and `.env` gets ignored. If you hit *"ANTHROPIC_API_KEY not set"* despite having it in `.env`, run `unset ANTHROPIC_API_KEY` before launching the backend, or remove the empty export from `~/.zshrc`.

## First-time setup

```bash
# 1. Install backend deps (creates .venv/)
uv sync --frozen --python 3.12

# 2. Install UI deps
make ui-install    # or: cd ui && npm install

# 3. Start database services (runs Postgres + Redis + Qdrant in Docker)
make db-up

# 4. Apply migrations
uv run alembic upgrade head

# 5. Start backend (port 8000)
unset ANTHROPIC_API_KEY   # only needed if your shell exports it empty
make dev

# 6. In another terminal, start the UI (port 3000)
make ui-dev
```

Open http://localhost:3000, log in with Google, upload an `.xlsx` from `data/` or your own, ask a question.

## Make targets

| Target | What it does |
|---|---|
| `make install` | `uv sync --frozen` — install Python deps |
| `make db-up` | Start postgres + redis + qdrant containers |
| `make db-down` | Stop those containers (keeps volumes) |
| `make dev` | Run backend via `uv run python main.py` |
| `make migrate` | `alembic upgrade head` |
| `make ui-install` | `cd ui && npm install` |
| `make ui-dev` | `cd ui && npm run dev` |
| `make ui-build` | Production build of UI |
| `make up` | Full Docker stack (app + DBs + Qdrant). Alternative to `make dev` + `make db-up`. |
| `make down` | Stop full Docker stack |
| `make test` | Run pytest suite |

## Canonical smoke-test questions

After setup, upload `data/dealership_financial_model.xlsx` in the UI and try these:

1. **Value:** *"What was the total gross profit in March?"* — expect a specific number with a cell ref like `P&L Summary!D18`.
2. **Formula:** *"How is Adjusted EBITDA calculated?"* — expect a multi-component narrative citing cells + named ranges.
3. **Dependency:** *"Which cells depend on Floor Plan Rate?"* — expect grouped list.
4. **Audit:** *"Are there any stale assumptions?"* — expect either findings or an honest "No".
5. **What-if:** *"What if FloorPlanRate went to 7%?"* — expect recomputed EBITDA / gross profit with delta.

Each answered turn records an `LLMUsage` row. Check `conversations.active_entity` and `conversations.scenario_overrides` in Postgres to confirm state persistence.

## Tests

```bash
# Auditor negation tests (Rosetta)
uv run python -m core.rosetta.tests.test_auditor_negation

# Akash's backend suite
uv run pytest tests/
```

## Deployment

### Render.com (recommended, ~30 min)

1. **Qdrant**: create a free-tier cluster at https://cloud.qdrant.io/. Copy URL + API key.
2. **Postgres**: Render Postgres addon (or any managed Postgres). Copy connection string.
3. **Redis**: Render Key-Value addon (or skip — optional for production).
4. **Web service**:
   - Build command: `pip install uv && uv sync --frozen`
   - Start command: `uv run python main.py`
   - Instance type: Standard (≥2GB RAM)
   - Environment variables (from `.env.example`): `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `QDRANT_URL`, `QDRANT_API_KEY`, `DATABASE_URL` (from Render Postgres), `REDIS_URL`, `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REDIRECT_URI=https://<service>.onrender.com/api/v1/auth/google/callback`, `JWT_SECRET_KEY`.
5. **Migrations**: after first deploy, open a Shell in Render and run `uv run alembic upgrade head`.
6. **UI**: separate Render Static Site pointing at the `ui/` directory. Build: `npm install && npm run build`. Publish: `ui/dist`. Add env var `VITE_API_BASE_URL=https://<backend>.onrender.com/api/v1` — and in `ui/src/api/auth.ts` replace the hardcoded `API_BASE_URL` with `import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000/api/v1'`.

### Docker Compose (local or VPS)

```bash
make up       # builds app image + starts 4 services
# logs: make logs
# stop: make down
```

The app image binds port 8000. Proxy via nginx or Caddy for HTTPS in production.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `pydantic-core` fails to build during `uv sync` | uv picked Python 3.14; PyO3 maxes at 3.13 | `uv sync --frozen --python 3.12` |
| Backend returns *"ANTHROPIC_API_KEY not set"* even with `.env` populated | Shell has `ANTHROPIC_API_KEY=""` exported | `unset ANTHROPIC_API_KEY` before `make dev`, or remove the empty export from your shell rc |
| Docker containers refuse to start: "port already allocated" | Another project's containers hold 5432/6379/6333 | `docker stop <their-container>` or change ports in `docker-compose.yml` |
| `/ask` returns "anthropic SDK not installed" | Environment out of sync | `uv sync --frozen --python 3.12` |
| UI can't reach backend (Failed to fetch) | Backend not running or CORS issue | Check `curl http://localhost:8000/health`; inspect browser Network tab |
| "Process File" button times out | GPT-4o upload processing is slow on big workbooks | First process can take 30–60s. Logs at `make logs` show progress |
| Audit returns "partial" unexpectedly | LLM fabricated a number/ref | Expected behavior — this is the anti-hallucination guarantee. If you disagree with the flag, inspect `core/rosetta/auditor.py` thresholds |

## Observability

Structured JSON logs via `structlog`. Backend logs every tool call and audit outcome:

```
{"event": "Query executed via Rosetta coordinator",
 "data_source_id": "...",
 "conversation_id": "...",
 "audit_status": "passed",
 "tool_calls": 3,
 "execution_time_ms": 8421,
 "cost_usd": "0.05515"}
```

Enable OpenTelemetry tracing with `JAEGER_ENABLED=true` and run Jaeger separately (`scripts/setup_jaeger.sh`).

## Known limitations

- Upload processing is synchronous — blocks UI for 5–30s on large workbooks
- Answer cache is in-memory — lost on restart
- No per-user rate limiting (only global via `RATE_LIMIT_ENABLED`)
- `find_cells` semantic tier depends on Akash's upload-time chunks, which are workbook-scoped; it won't find cells outside the chunks the upload pipeline created
