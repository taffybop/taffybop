# P03-US08 Hardened Phase 04 Tables Renewal — Independent Review 11 (Blocked)

Status: **BLOCKED — no approval granted**  
Reviewed: 2026-08-04  
Scope: Pre-seal correctness and resource review after review 10 remediation

## Candidate identification

This review covered two explicitly evolving pre-seal snapshots, not a frozen
approval bundle. The resource reviewer recorded the exact executable-guard
SHA-256
`80c2f18a40824b941ce99e7087cf2a26d75793f06d7728c89bfec9d195c0a3bd`.
The correctness reviewer recorded later guard/test identity prefixes
`fb16ace9…` / `a1b0fb9…` before another remediation mutation. Because the
candidate changed during review and the latter full identities were not
retained by that reviewer, this record makes no stronger identity claim. That
identity discontinuity independently prevents approval and is preserved here
rather than retroactively attaching either verdict to later files.

## Blocking findings

1. **IR11-FE-LEX-01 — regex after a control head.** A JavaScript regex literal
   immediately following an `if (...)` control head was not recognized. Its
   `[//]` character class was then treated as a line comment and hid later
   split literals that reconstructed forbidden scope.
2. **IR11-FORMAT-01 — dynamic widths.** Static `%` and `str.format` evaluation
   rejected large literal widths but did not preflight `*` widths or nested
   replacement-field widths. Compact constant tuples could therefore request
   very large formatting allocations before the result ceiling.
3. **IR11-RESOURCE-01 — frontend limits after construction.** The frontend
   lexer accumulated and joined a decoded literal before enforcing its
   262,144-byte limit, and masking copied the complete source into a character
   list before a local source-size preflight.
4. **IR11-RESOURCE-02 — backend limits after construction.** Static `split`,
   `%` formatting, `casefold`, generic call joins, and selected Cartesian
   paths materialized intermediate results before the 65,536-byte or
   256-variant ceiling. The scope collector also materialized the complete AST
   walk before its 8,192-node threshold.
5. **IR11-RESOURCE-03 — literal materialization.** The top-level
   literal-only predicate used `ast.literal_eval`, creating literal containers
   before the later 32,768-node syntax ceiling. Although no candidate code was
   executed, this contradicted the administrative guard's pre-allocation
   resource claim.

## Execution evidence

- Correctness slice: **105 passed, 425 deselected, 1** documented
  Starlette/httpx warning.
- Resource slice: **14 passed, 1** documented warning.
- Non-execution inspection was clean: no candidate `eval`, `exec`, `compile`,
  import, subprocess, Python invocation, or JavaScript execution path was
  found. A benign sentinel call produced no output.
- Reviewers did not execute catastrophic-width examples and edited no files.

Attempt 48 remained failed at **0.050946750 seconds** against the unchanged
**0.050000000-second** ceiling (**0.000946750 seconds / 1.8935%**, maximum
**5%** candidate-specific). Canonical strict-final evidence remained absent,
the companion remained quarantined, all non-waived gates remained stated,
and the 55-artifact failed-history manifest remained
`bca401f2207619ba84422e020104b9a609e0be0f4dc2b42f3ae4fb53d315ceff`.
No production, configuration, runtime, story-status, or Phase 05 change
occurred.

## Required disposition

This review grants no approval and must never be reclassified. Remediation
requires regex detection after control heads; rejection of dynamic format
widths; incremental source/literal/node/result accounting; preflight for
split, casefold, formatting, joins, multiplication, replacement, shifts, and
Cartesian products; AST-only literal validation; permanent regressions;
complete reruns; resealed identities; and a fresh independent review.
