# ADR-0001 — Pin TypeScript to 6.0.3 instead of 7.x

* Status: **accepted**
* Date: 2026-10-14
* Deciders: project owner
* Evidence: [`docs/02-M1兼容性验证报告.md`](../02-M1兼容性验证报告.md) §2

## Context

The original dependency plan took the newest stable version of everything, which meant
`typescript@7.0.2`. Installation failed immediately:

```
npm error ERESOLVE unable to resolve dependency tree
npm error Found: typescript@7.0.2
npm error Could not resolve dependency:
npm error peer typescript@">=4.8.4 <6.1.0" from typescript-eslint@8.71.2
```

`typescript-eslint@8.71.2` is the current `latest`, and its peer range excludes TypeScript 7.
The `canary` (8.71.3-alpha.4) carries the **same** `<6.1.0` range, so this is not a release-lag
problem that resolves itself in a patch.

The cause is structural, and verifiable from the package metadata:

```
$ npm view typescript@7.0.2 optionalDependencies
{
  "optionalDependencies": {
    "@typescript/typescript-win32-x64": "7.0.2",
    "@typescript/typescript-linux-x64": "7.0.2",
    ... one entry per platform ...
  }
}
```

TypeScript 7 ships **platform-native compiler binaries**. `typescript-eslint` is built on the
JavaScript compiler API; supporting the native compiler is a rewrite of its type layer, not a
version bump.

## Decision

Pin `typescript@6.0.3` (the newest 6.x) and keep everything else on its newest stable major.
Revisit only when `typescript-eslint`'s peer range admits TypeScript 7.

## Consequences

**Good**

* The whole toolchain works today, and was verified rather than assumed: `tsc --noEmit`,
  `eslint`, `vitest` and `vite build` all pass with TypeScript 6.0.3 alongside Vite 8,
  ESLint 10, Tailwind 4 and React 19.
* The failure surfaced in the first minutes of M1 rather than after the frontend was written.

**Costs**

* We forgo TS 7's compile speed.
* We carry an explicit upgrade task: when the peer range opens up, bump TypeScript, re-run the
  M1 verification matrix, and supersede this ADR.

## Alternatives considered

* **Drop `typescript-eslint`, lint with plain ESLint.** Rejected: type-aware linting is most of
  the value, and requirement 5 of the target role is explicitly about interface discipline.
* **Use the `canary` of `typescript-eslint`.** Rejected: its peer range is identical, so it
  would not even install, and pinning a canary in a portfolio project is a poor signal.
* **Stay on TypeScript 5.9.3.** Rejected as unnecessarily conservative — 6.0.3 is supported by
  every tool in the stack and is what the verification matrix was run against.
