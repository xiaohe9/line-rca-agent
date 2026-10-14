# Architecture decision records

Short, dated records of decisions that were not obvious and would be expensive to reverse.
Each one states the evidence, not just the conclusion — so a future reader can tell whether
the reasoning still holds.

| ADR | Decision | Status |
|---|---|---|
| [0001](0001-typescript-pinned-to-6.md) | Pin TypeScript to 6.0.3 instead of 7.x | accepted |
| 0002 | LangGraph vs. native orchestration, and how they stay interchangeable | planned (M3) |
| 0003 | pgvector instead of a separate vector store (ChromaDB / FAISS) | planned (M2) |
| 0004 | No Celery / Redis: `BackgroundTasks` + APScheduler is enough at this scale | planned (M5) |
| 0005 | Adopt `httpx2` for Starlette's TestClient, or hold on `httpx` | planned |
| 0006 | The trace event contract is versioned and treated as a public interface | planned (M4) |
