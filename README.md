# line-rca-agent

**Production-line yield anomaly root-cause analysis agent.**

Turns what the line already records — defect distributions, equipment telemetry, process
parameters — into an answer an engineer can act on: *most likely root cause, the evidence
that supports it, and the recommended action*. Every step of the reasoning is a streamed,
versioned event, so the whole decision is auditable rather than a black box.

```text
question ──▶ Plan-and-Execute planner ──▶ ReAct executor ──▶ tools (defects / telemetry / SOP / work orders)
                     │                            │
                     └──────── trace events ──────┴──▶ SSE ──▶ reasoning timeline UI
```

> **Runs offline.** The default configuration (`LRC_DEMO_MODE=1`) uses a scripted `fake`
> LLM provider and a **simulated** demo dataset. No API key, no network, full streaming trace.

---

## Status

Early. This repository is being built in stages; see [`docs/`](docs/) for the plan and the
[M1 compatibility report](docs/02-M1兼容性验证报告.md) for what is verified to work.

| Area | State |
|---|---|
| `packages/agent-core` — framework-free kernel (contracts, trace, planner, executor, memory, tools, fake provider) | ✅ implemented + tested |
| `apps/api` — FastAPI adapter, SSE streaming, config | ✅ implemented + tested |
| Persistence — SQLAlchemy 2 + Alembic migrations, seeded line data | ✅ implemented + tested |
| Real tools — defect distribution, telemetry, work orders, similar cases | ✅ implemented + tested |
| `apps/web` — React/TS reasoning-timeline UI (stream, replay, export) | ✅ implemented + tested |
| Docker images + compose stack | ✅ built + verified end to end (15 checks) |
| GitHub Actions CI | ✅ written — unverified until the repo exists on GitHub |
| MQTT telemetry ingest (collector + simulator) | ✅ implemented + tested |
| Real LLM providers, vector memory, dataset evaluation | ⏳ later |
| Public deployment | ⏳ next |

---

## Layout

```text
apps/api/                 FastAPI adapter: HTTP + SSE, configuration
apps/web/                 React + TypeScript UI: renders the streamed trace
packages/agent-core/      framework-free kernel (zero runtime dependencies)
docs/                     requirements analysis, dependency decisions, ADRs, verification reports
```

Dependency direction is enforced by a test, not by convention:

```text
apps/api  ──▶  packages/agent-core  ──▶  (nothing)
```

The kernel must never import FastAPI, SQLAlchemy, an HTTP client or an LLM SDK. If you add
such an import, `packages/agent-core/tests/test_contracts.py` fails and names the file.

---

## Quickstart

### Prerequisites

* **Python 3.12**, **Node 24**, **Docker** (for Postgres later).
* **`uv`** for Python and **`npm` workspaces** for the frontend.

### ⚠️ Environment notes for Windows + this machine

These will bite you if you skip them. They are all measured, not guessed.

1. **Do not use `pip`.** On this machine `pip install` fails with
   `Errno 13` / `WinError 5` inside its own temp directories. `uv` works fine. Use `uv` only.
   (Details: [verification report §9](docs/02-M1兼容性验证报告.md).)
2. **Do not use `pnpm` either.** pnpm 12 cannot open its store operation lock here
   (`ERR_PNPM_STORE_DIR_OPEN_OPERATION_LOCK`, `os error 5`), and elevating privileges does not
   help. This workspace uses **npm workspaces** instead.
   (Details: [verification report §10](docs/02-M1兼容性验证报告.md).)
3. **Keep package caches inside the repository.** The default cache locations live outside
   the sandboxed workspace and are refused, which makes even `npm view` fail:

   ```powershell
   $env:npm_config_cache = "$PWD\.npm-cache"
   $env:UV_CACHE_DIR     = "$PWD\.uv-cache"
   ```

4. **Frontend `build` / `test` may need full access.** Vite 8 runs `exec('net use')` on Windows
   to resolve real paths; the confined sandbox denies piped stdio (`spawn EPERM`). `tsc` and
   `eslint` are fine either way. Whether you hit this depends on your agent/session permission
   mode — with full access, all four gates run unelevated.
5. **TypeScript is pinned to 6.0.3, not 7.x.** TypeScript 7 is the native-compiler rewrite;
   `typescript-eslint` still caps at `<6.1.0`, so TS 7 breaks linting.
   See [ADR-0001](docs/adr/0001-typescript-pinned-to-6.md).

### Run the API (offline demo)

The agent's tools read a real database, so Postgres comes first. The whole stack — including
the migration and the seed — is one command:

```powershell
docker compose up -d --build     # UI on :8080, API docs on :8000/docs
```

Or run the API on the host against just the database:

```powershell
docker compose up -d postgres
$env:LRC_DATABASE_URL = "postgresql+asyncpg://lrc:lrc@localhost:5432/lrc"
$env:UV_CACHE_DIR     = "$PWD\.uv-cache"
uv sync
uv run python -m line_rca_api.db.bootstrap      # migrate, then seed if empty
uv run uvicorn line_rca_api.main:app --reload --port 8000
```

Then, in another shell:

```powershell
# full trace as JSON
curl -s -X POST http://127.0.0.1:8000/api/analyze/collect `
  -H "content-type: application/json" `
  -d '{"goal":"为什么 B-2041 批次良率下降？"}'

# the same run, streamed as Server-Sent Events
curl -N -X POST http://127.0.0.1:8000/api/analyze `
  -H "content-type: application/json" `
  -d '{"goal":"为什么 B-2041 批次良率下降？"}'
```

Interactive API docs: <http://127.0.0.1:8000/docs>

### What the agent can actually do

| Tool | Reads/writes |
|---|---|
| `query_defects` | defect rate and the per-station, per-type breakdown for a batch |
| `query_telemetry` | latest equipment readings, each against its baseline, deviations flagged |
| `find_similar_cases` | past work orders with a matching symptom or station |
| `create_work_order` | **writes** a maintenance order, linked to the run that recommended it |
| `list_work_orders` | recent orders, optionally filtered by status |

`create_work_order` closes over the current run id, so `work_orders.run_id` points back at the
reasoning that produced the recommendation — the decision stays auditable after the fact.

### Run the web UI

With the API still running:

```powershell
npm install
npm run dev            # http://127.0.0.1:5173
```

The dev server proxies `/api` and `/health` to `http://127.0.0.1:8000`, so the browser stays on
one origin. Point it elsewhere with `LRC_API_TARGET`.

The UI streams a run and renders it as a timeline. Three things are worth trying:

* **Expand an entry** — tool arguments and raw tool output are one click away.
* **播放回放 / 回放** — replay the run event by event. `Space`, `←` `→` and `End` drive it, so
  the timeline is fully keyboard-operable.
* **导出报告** — export the whole run (goal, answer, every step, every tool result) as
  Markdown. It is generated from accumulated events, so it works offline and mid-run.

### Run the whole stack with Docker

```powershell
docker compose up --build
# UI        http://localhost:8080
# API docs  http://localhost:8000/docs
```

Four services: `web` (unprivileged nginx), `api` (non-root uvicorn), `postgres` (pgvector) and
`mosquitto`. The database and broker are provisioned for M2 and the API does not use them yet —
they are there so the next milestone is one command away.

nginx serves the bundle and reverse-proxies `/api` and `/health`, so the browser stays on one
origin and the SSE stream needs no CORS handling. `proxy_buffering off` is what keeps the stream
incremental rather than delivered in one burst at the end; both are verified — see
[the M1 report](docs/02-M1兼容性验证报告.md) §13.

### Live telemetry over MQTT

The default stack is deterministic: seeded data, a scripted model, identical numbers every run.
To watch real messages flow instead:

```powershell
docker compose --profile live up -d --build
```

That adds two services. `simulator` stands in for an edge gateway reading a PLC and publishes
`line/<station>/telemetry`; `collector` subscribes and writes what it receives, labelled
`source="mqtt"`. The agent then reasons over live readings — and says so, because the provenance
line in each observation is derived from the rows rather than hard-coded:

```text
query_telemetry -> (source: mqtt)
  vibrationMm: 0.1934 vs baseline 0.06 (3.22x) at 2026-10-14T09:44:51  <-- deviation
```

Either side can run on its own:

```powershell
uv run python -m line_rca_api.ingest.collector     # broker -> Postgres
uv run python -m line_rca_api.ingest.simulator     # simulated PLC -> broker
```

The collector is a separate process rather than an API background task: in a plant it sits at
the edge next to the equipment, and a broker outage should not take the API down with it.

### Tests, lint, types

```powershell
# backend — the API tests are integration tests and need a database
docker compose up -d postgres
$env:LRC_TEST_DATABASE_URL = "postgresql+asyncpg://lrc:lrc@localhost:5432/lrc"
uv sync
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run mypy

# frontend
npm run typecheck
npm run lint
npm run test
npm run build
npm run budget          # fails if a JS bundle exceeds 300 kB gzip
```

Without `LRC_TEST_DATABASE_URL` the integration tests **skip with a stated reason** rather
than passing silently. The kernel and tool-layer tests need no database at all.

---

## Data: simulated, and labelled as such

Every observation returned by the demo tools carries
`(simulated demo dataset — not real production data)`, and the demo answer repeats it.
This is a portfolio project: it must never be mistaken for a real production deployment.

Real data enters the picture through public industrial datasets — see
[the data section of the analysis](docs/00-需求与差距分析.md). Note that these carry **no
root-cause labels**, which is why root-cause metrics are measured on *controlled fault
injection* on top of a real baseline rather than on the dataset's own pass/fail column.

---

## License

[MIT](LICENSE)
