## What this changes

<!-- One or two sentences. Link the issue if there is one. -->

## JD coverage

<!--
This repository exists to demonstrate specific capabilities from the target job description.
Fill this in so `docs/jd-coverage.md` can be assembled from the PR history instead of memory.
-->

| JD requirement | How this PR covers it |
|---|---|
|  |  |

## How it was verified

<!-- Paste the commands you actually ran and their outcome. "It should work" is not evidence. -->

```text
uv run pytest
npm run test
```

## Checklist

- [ ] Tests added or updated for the behaviour change
- [ ] `uv run ruff check . && uv run ruff format --check . && uv run mypy` pass
- [ ] `npm run typecheck && npm run lint && npm run test && npm run build` pass
- [ ] No secret, credential, résumé material or real production data added
- [ ] Docs updated if this changes a contract, a decision or the dev setup
