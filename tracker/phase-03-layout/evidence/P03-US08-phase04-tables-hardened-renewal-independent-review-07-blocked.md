# P03-US08 Hardened Phase 04 Tables Renewal — Independent Review 07 (Blocked)

Status: **BLOCKED — no approval granted**  
Reviewed: 2026-08-04  
Scope: Final contract, Phase-boundary/security, and metrics/custody review of
the frozen hardened renewal bundle

## Frozen bundle reviewed

| Artifact | Bytes | Raw SHA-256 |
|---|---:|---|
| Decision | 23,396 | `f3b02772501140e1ca6b7fbd865fc91733a7d39bbcfabb8770289ee580d27318` |
| Machine-readable renewal | 20,439 | `5b8894f40c6082465b0f00f1b39aaba6ec496776ae4fd83ff33d92f15c0282e3` |
| Executable custody guard | 301,252 | `932b850e15b5fc457c592847716060c916bebd3ffbe6f9d0a9354c0493cef052` |
| Focused guard tests | 174,491 | `4858937e23057f00d40ca154575eeef27ecd49bad6a62f6e8e5696f5d9926983` |
| Verification record | 9,815 | `724aaf98e46bbaa014b25ba4d4f0684fd11cbe0ca9e33d3f26cd509546e8be8d` |

The renewal JSON semantic SHA-256 independently recomputed to
`a63e635ead65ddff1a3aa49356393fabaefd687e53b6b8ae5ac063a2400894b6`.
Blocked reviews 03 through 06 matched their recorded identities and remained
blocked history.

## Blocking findings

1. **IR07-SCOPE-01 — split constant reconstruction.** The backend scanner
   accepted enabled-path output containing `"Phase " + "05"`, `"P" + "05"`,
   `"running" + "Region"`, or `"running" + "_regions"`. Inspecting each AST
   constant separately did not close the resulting Phase 05 or running-region
   value.
2. **IR07-SCOPE-02 — embedded compact identifiers.** The shared backend and
   frontend checks accepted `tablephase05enabled`, `runningregionenabled`,
   `runningregionsenabled`, `tablerunningregionenabled`, and
   `RUNNINGREGIONSENABLED`, contrary to the claimed compact/plural/case
   closure.
3. **IR07-FE-01 — default-parameter and coercion cycles.** Named-function
   default expressions could call themselves or mutually recurse before body
   entry. Object-literal `toString`, `valueOf`, and `toJSON` hooks also escaped
   callback provenance; controlled execution reproduced recursive
   `RangeError` outcomes.
4. **IR07-FE-02 — property-only global capabilities.** The frontend scanner
   rejected selected external calls but admitted reads through `process.env`,
   `Deno.env`, `Bun.env`, `fs.promises`, `sessionStorage`, `localStorage`,
   `indexedDB`, `caches`, `cookieStore`, `performance.memory`, and
   `crypto.subtle`. These capabilities contradict the stated process/browser/
   storage closure.
5. **IR07-CUSTODY-01 — legacy code-closure mismatch.** The non-waived P03
   metrics/custody suite failed because existing
   `frontend/tests/p04-us01-table-readiness.test.mts` (2,156 bytes, SHA-256
   `ffc15e1ed0511b20a34bdead5342345b521f25e644b705806e2d9060a7d1f817`)
   was outside both the frozen 86-path P03 manifest and the renewal's
   enumerated Phase 04 paths. Future admitted Phase 04 helper/test paths would
   trigger the same legacy assertion unless separately and exactly
   reconciled. The frozen P03 manifest must not be rewritten or treated as if
   it contained Phase 04 files.

## Execution evidence

- Complete focused renewal guard, independently repeated: **376 passed**, zero
  failed or skipped, **1** documented Starlette/httpx deprecation warning
  (observed review runtimes 26.85–27.57 seconds).
- Positive Phase 04 expressibility slice: **9 passed, 367 deselected, 1
  warning** in 0.36 seconds.
- P03 running-region metrics/custody contract: **119 passed, 1 failed, 1
  expected strict-final skip, 1 warning**. The sole failure was
  `test_default_code_custody_closes_parser_frontend_and_frozen_policy` and is a
  blocking non-waived custody result.
- Python compilation of both renewal guard files passed.

Attempt 48 remained failed at **0.050946750 seconds** against the unchanged
**0.050000000-second** ceiling (**0.000946750 seconds / 1.8935%**, maximum
**5%** candidate-specific). Canonical strict-final evidence remained absent,
the companion remained quarantined, the 55-artifact failed-history manifest
remained
`bca401f2207619ba84422e020104b9a609e0be0f4dc2b42f3ae4fb53d315ceff`,
and every non-waived gate remained stated. All seven production surfaces were
still at their predecessor identities. P04-US01 remained Ready and held;
later Phase 04 and all Phase 05 stories remained Proposed.

## Required disposition

This review grants no approval and must never be reclassified. Remediation
requires permanent adjacent regressions for every finding, an exact separate
Phase 04 custody distinction that preserves the frozen 86-path P03 manifest,
a resealed decision/record/guard/verification bundle, the complete focused and
metrics/custody suites, and new independent approval of those final
identities. No production or story-status change may rely on this reviewed
bundle.
