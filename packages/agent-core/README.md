# line-rca-agent-core

Framework-free agent kernel. Zero runtime dependencies on purpose.

The kernel knows nothing about FastAPI, SQLAlchemy, HTTP or any LLM SDK. It talks to
`Protocol`s only, so every part — planner, executor, memory, tools, LLM provider — can be
swapped without touching the kernel, and the whole thing is testable with no network.

Import-direction rule (enforced in CI):

```
apps/api  ->  packages/agent-core  ->  (nothing)
```
