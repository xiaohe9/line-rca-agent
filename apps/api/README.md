# line-rca-api

The adapter layer. It owns everything the kernel deliberately refuses to know about:
HTTP, SSE transport, configuration, and (from M2) persistence.

```
apps/api  ->  packages/agent-core  ->  (nothing)
```
