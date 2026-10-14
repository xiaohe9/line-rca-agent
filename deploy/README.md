# Deployment

The stack is designed so that the interesting part — the agent and its streamed trace — is
deployable without a credit card, a domain, or a filing (备案).

## Topology

```text
browser ──▶ Cloudflare Pages (static bundle)
                │
                └── /api, /health ──▶ Cloudflare Tunnel ──▶ this machine's docker compose
                                                              ├─ web   (nginx, unprivileged)
                                                              ├─ api   (uvicorn, non-root)
                                                              └─ postgres (pgvector)
```

Two properties matter and are already true in the compose file:

* **The browser only ever talks to one origin.** nginx reverse-proxies `/api` and `/health`,
  so there is no CORS preflight around the SSE stream and no second hostname to configure.
* **`proxy_buffering off` on `/api/`.** Without it nginx collects the whole stream and
  delivers it in one burst at the end, which quietly destroys the point of streaming.
  This is verified end-to-end: see the M1 verification report.

## Local (already verified)

```powershell
docker compose up --build
# UI        http://localhost:8080
# API docs  http://localhost:8000/docs
```

Verified in this repository: both images build, all four services start, the API reports
healthy, and seven checks pass through nginx — including an un-buffered 12-frame SSE stream.

## Public demo

| Piece | Where | Why |
|---|---|---|
| Frontend | Cloudflare Pages | Cloudflare is not in this machine's hosts hijack list (see the M1 report) |
| API | Cloudflare Tunnel → local compose | No port forwarding, no static IP, no filing |
| Fallback demo | A single container with `LRC_DEMO_MODE=1` | Works when this machine is off; no API key needed |
| Database | A managed Postgres with `pgvector` | Only needed from M2 onwards |
| Model | A remote provider in production, `fake` in the demo | The demo must never depend on a key or the network |

**Status: not deployed yet.** The images build and the stack runs locally; publishing is the
step that still requires the GitHub channel to work (see the M1 report section 13).
