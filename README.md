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
| `apps/web` — React/TS reasoning-timeline UI | ⏳ next |
| Docker / CI / deployment | ⏳ next |
| Real LLM providers, pgvector memory, SECOM evaluation, work orders | ⏳ later |

---

## Layout

```text
apps/api/                 FastAPI adapter: HTTP + SSE, configuration
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
* **`uv`** for Python and **`pnpm`/`npm`** for the frontend.

### ⚠️ Environment notes for Windows + this machine

Four things will bite you if you skip them. They are all measured, not guessed.

1. **Do not use `pip`.** On this machine `pip install` fails with
   `Errno 13` / `WinError 5` inside its own temp directories. `uv` works fine. Use `uv` only.
   (Details: [verification report §9](docs/02-M1兼容性验证报告.md).)
2. **Keep package caches inside the repository.** The default cache locations live outside
   the sandboxed workspace and are refused, which makes even `npm view` fail:

   ```powershell
   $env:npm_config_cache = "$PWD\.npm-cache"
   $env:UV_CACHE_DIR     = "$PWD\.uv-cache"
   ```

3. **Frontend `build` / `test` need full access.** Vite 8 runs `exec('net use')` on Windows to
   resolve real paths; the confined sandbox denies piped stdio (`spawn EPERM`). `tsc` and
   `eslint` are fine either way.
4. **TypeScript is pinned to 6.0.3, not 7.x.** TypeScript 7 is the native-compiler rewrite;
   `typescript-eslint` still caps at `<6.1.0`, so TS 7 breaks linting.
   See [ADR-0001](docs/adr/0001-typescript-pinned-to-6.md).

### Run the API (offline demo)

```powershell
$env:UV_CACHE_DIR = "$PWD\.uv-cache"
uv sync
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

### Tests, lint, types

```powershell
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run mypy
```

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
