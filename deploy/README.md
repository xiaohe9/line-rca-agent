# Deployment

Three shapes, in increasing order of what they need from you:

| Shape | Needs | Verified |
|---|---|---|
| **Single container** | Docker | ✅ 8 checks, embedded SQLite, no external services |
| **Compose stack** | Docker | ✅ 15 checks through nginx, Postgres + MQTT |
| **Public demo** | An account somewhere | ⏳ not done |

---

## 1. Single container (the demo artifact)

One image carries the API, the built frontend and an embedded SQLite database. No second
service, no database server, no API key, no network.

```powershell
docker build -f deploy/Dockerfile.demo -t line-rca-demo .
docker run --rm -p 8080:8080 line-rca-demo
# UI + API on http://localhost:8080
```

This is the shape a free host wants, and it is what the public demo will point at. What was
verified, in one container on a mapped port:

```text
ok  the container became ready
ok  GET / serves the UI from the same origin as the API
ok  GET /health reports the wired composition          — provider=fake, tools=5
ok  GET /ready confirms the embedded database          — {"status":"ready"}
ok  the seed data made it into the embedded database   — B-2041=40.98%
ok  a full analysis runs and reaches an answer         — 18 events
ok  the run opened a work order in the embedded database — WO-20261014-001
ok  GET /assets/index-*.js is served
```

It runs as UID 10001 and the image is 365 MB.

Two things had to change for this to be possible, and both were real blockers rather than
polish:

* **the migration was Postgres-only.** `server_default=sa.text("now()")` compiles only on
  Postgres; `sa.func.now()` compiles per dialect. Until that changed, a single-container demo
  could not exist. The whole integration suite now passes against SQLite as well as Postgres.
* **the API did not serve the frontend.** `LRC_WEB_DIST` mounts the built bundle at `/`, so one
  process serves both halves on one origin — no reverse proxy and no CORS between them.

### Deploying shape 1 to a free host

Hugging Face Spaces (Docker SDK) is the least friction: create a Space, point it at this
repository, set the Dockerfile path to `deploy/Dockerfile.demo`, and it builds. Nothing needs a
key, because the demo provider is the scripted `fake` one.

## 2. Compose stack

```powershell
docker compose up --build
# UI        http://localhost:8080
# API docs  http://localhost:8000/docs
```

Four services: `web` (unprivileged nginx), `api` (non-root uvicorn), `postgres` (pgvector) and
`mosquitto`. Verified: both images build, all four start, the API reports healthy, and 15 checks
pass through nginx — including a 12-frame SSE stream that arrives un-buffered.

Two properties are what make the stream work and are easy to lose:

* **the browser only talks to one origin.** nginx reverse-proxies `/api`, `/health`, `/live`,
  `/ready` and `/config`. Anything not proxied falls through to the SPA fallback and answers
  `200` with HTML, which is how a probe ends up looking healthy while never reaching the API.
* **`proxy_buffering off` on `/api/`.** Without it nginx collects the whole stream and delivers
  it in one burst at the end, which quietly destroys the point of streaming.

Add live telemetry with `docker compose --profile live up -d`.

## 3. Public demo

| Piece | Where | Why |
|---|---|---|
| The demo | A single container (shape 1) | No database service to pay for, no key to leak |
| Frontend, if split | Cloudflare Pages | Cloudflare is not in this machine's hosts hijack list (see the M1 report) |
| API, if split | Cloudflare Tunnel → local compose | No port forwarding, no static IP, no filing |
| Model | `fake` for the demo, a real provider for production | The demo must never depend on a key or the network |

**Status: not deployed.** The artifact is built and verified; publishing needs an account, and
the repository itself still needs the GitHub channel to work (M1 report, section 13).
