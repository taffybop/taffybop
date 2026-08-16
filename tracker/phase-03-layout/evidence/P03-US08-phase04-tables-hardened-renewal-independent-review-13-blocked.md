# P03-US08 Hardened Phase 04 Tables Renewal — Independent Review 13 (Blocked)

Status: **BLOCKED — no approval granted**  
Reviewed: 2026-08-04  
Scope: Fresh scope/security pre-seal after review 12 remediation

## Candidate identification

- executable custody guard: **384,792 bytes**, raw SHA-256
  `898a49d90283095485d411ed0cd31b4ee7bacebd9402eeb238ab1e237330c485`;
- focused guard tests: **199,792 bytes**, raw SHA-256
  `b5b44b4391ebe21cb49bc8ce584fffbebdf47a470203772ab48d2c8aa4ad9a50`.

All identities matched at review start and remained stable through the
finding. Separate compatibility and resource reviewers returned clean
pre-seal verdicts on these bytes, but neither verdict can override the scope
blocker below.

## Blocking finding

**IR13-FE-LEX-01 — generic JSX-close exception in plain TypeScript.** The
literal lexer treated any slash preceded by `<` and followed by an alphabetic
character as a JSX close. Both the table-branch and exact helper validators
therefore admitted:

```ts
return Boolean(item)</a[//]/.test("x");
return String("Ph" + "ase05");
```

In the `.ts` helper this is valid TypeScript lexical structure, not invalid
JSX: the TypeScript compiler reported no diagnostics and emitted the first
line as a relational `<` followed by `/a[//]/`. The lexer then treated `//`
inside the regex character class as a comment and hid the forbidden
split-literal reconstruction.

## Execution evidence

- Permanent bounded scope/security suite: **151 passed, 1** documented
  Starlette/httpx warning in **1.15 seconds**.
- Existing closing-block, control-head, comment-interposed, arrow, Unicode,
  transform, arithmetic, and indexing probes rejected as intended.
- Python Phase 04 controls and proven frontend division controls remained
  accepted.
- The new relational/regex reproducer was incorrectly accepted by both
  frontend surfaces.
- TypeScript syntax confirmation returned diagnostics `[]`; no project file
  was executed or edited by the reviewer.

Attempt 48 remained failed at **0.050946750 seconds** against the unchanged
**0.050000000-second** ceiling (**0.000946750 seconds / 1.8935%**, maximum
**5%** candidate-specific). Canonical strict-final evidence remained absent,
the companion remained quarantined, and the 55-artifact failed-history
manifest remained
`bca401f2207619ba84422e020104b9a609e0be0f4dc2b42f3ae4fb53d315ceff`.
Every non-waived gate remained unchanged. No production, configuration,
runtime, story-status, or Phase 05 change occurred.

## Required disposition

This review grants no approval and must never be reclassified. Remediation
must disable JSX exceptions for the `.ts` helper and admit a closing slash in
the TSX branch only when it exactly closes a matching, allowlisted, previously
opened JSX tag. The reproducer and mismatch adjacencies must be permanent
regressions, followed by complete reruns, resealed identities, and another
fresh independent review.
