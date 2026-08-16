# P03-US08 Hardened Phase 04 Tables Renewal — Independent Review 10 (Blocked)

Status: **BLOCKED — no approval granted**  
Reviewed: 2026-08-04  
Scope: Static-guard correctness, boundary, lexer, and resource review after
review 09 remediation

## Candidate reviewed

| Artifact | Raw SHA-256 |
|---|---|
| Executable custody guard | `2a1ab360b0ae722a2c08c8a24860b0c96f4ef7f555cbc370ed0c31f3f574e867` |
| Focused guard tests | `364ede916fbb46e3464623e8c23611c7f2e9310e8d327b22ca7a456d7489da9b` |

The decision, machine-readable renewal, administrative metrics/custody
contract, and attempt-48 facts were unchanged. This was a pre-seal review of
the evolving executable guard and its focused regressions; no final approval
was requested or granted for these identities.

## Blocking findings

1. **IR10-BE-SCOPE-01 — admitted string transformations.** The complete
   nine-function table-semantics validator accepted forbidden output created
   through allowed methods: `"xrunningRegion".strip("x")`,
   `"metaphase05".strip("meta")`, and
   `"xrunningRegion".split("x")[1]`. Allowed `re.sub` and Unicode
   `normalize("NFKC", ...)` forms likewise transformed lexically benign or
   compatibility text into `phase05`.
2. **IR10-FE-SCOPE-01 — cross-literal selection/reordering.** Both frontend
   validators admitted `P05` assembled by selecting characters across several
   literals with numeric indexing, `at`, or `slice`; an equivalent split
   `slice` construction produced `runningRegion`. Per-literal checks did not
   compose selected characters across the complete expression surface.
3. **IR10-FE-LEX-01 — regex/comment ambiguity.** The hand lexer treated `//`
   inside a valid JavaScript regex character class as a line-comment opener.
   A regex placed before split `"Ph" + "ase05"` literals therefore hid the
   forbidden reconstruction from both the table-branch and exact-helper
   validators.
4. **IR10-RESOURCE-01 — limits applied after allocation.** Static multiplication,
   format width, old-style `%` formatting, `str.format`, replacement, numeric
   shifts, and Cartesian products could allocate or materialize results before
   the 65,536-byte or 256-variant ceilings were checked. Compact candidate
   source could therefore request memory far beyond the stated fail-closed
   guard bounds.

## Execution evidence

- The reviewers' focused existing-control slice passed **68 tests, 446
  deselected, 1** documented Starlette/httpx warning.
- Controlled evaluation was limited to small reviewer-authored examples; the
  administrative scanner itself did not execute candidate Python or
  JavaScript. Catastrophic-width cases were identified by code audit and were
  not executed.
- No files were edited by either reviewer.

Attempt 48 remained failed at **0.050946750 seconds** against the unchanged
**0.050000000-second** ceiling (**0.000946750 seconds / 1.8935%**, maximum
**5%** candidate-specific). Canonical strict-final evidence remained absent,
the companion remained quarantined, every non-waived gate remained stated,
and the 55-artifact failed-history manifest remained
`bca401f2207619ba84422e020104b9a609e0be0f4dc2b42f3ae4fb53d315ceff`.
No production, configuration, frontend runtime, story-status, or Phase 05
change occurred.

## Required disposition

This review grants no approval and must never be reclassified. Remediation
requires bounded handling or fail-closed rejection for every admitted string
transform; NFKC-aware scope scanning; unambiguous regex/comment handling;
cross-literal index/`at`/`slice` composition; operation-specific allocation
preflight before multiplication, formatting, replacement, shifts, or
Cartesian products; permanent regressions; complete reruns; resealed exact
identities; and a new independent review.
