# P03-US08 Hardened Phase 04 Tables Renewal — Independent Review 12 (Blocked)

Status: **BLOCKED — no approval granted**  
Reviewed: 2026-08-04  
Scope: Pre-seal scope, compatibility, and resource review after review 11 remediation

## Candidate identification

The three-way review began on this exact candidate:

- executable custody guard: **366,908 bytes**, raw SHA-256
  `80f882d42aa6fe86b5fc42c4221527c502cea83bc5f2f65481f2c507153bd677`;
- focused guard tests: **192,938 bytes**, raw SHA-256
  `2ff2204049840de5f3f4a77e195160c6b7906a3773f576e7ce72a5b82963e789`.

The resource reviewer also observed later, already-mutating candidates with
guard/test identity prefixes `8319…` / `30c4…`, followed by guard identity
`9c4b41445cfee2f7bcec274751013ea0560f5f82e107ac81a22ebc99be14bc66`.
Those observations were remediation snapshots, not approval candidates. No
review result is attached retroactively to their later bytes.

## Blocking findings

1. **IR12-FE-LEX-01 — regex after a closing block.** Both frontend validators
   admitted `if (Boolean(item)) { }\n/[a//]/.test("x")`; the `//` inside the
   regex character class was then treated as a comment and hid a later
   split-literal `Phase05` reconstruction.
2. **IR12-RESOURCE-01 — aggregate format variants.** Seventeen static receiver
   variants and seventeen scalar variants materialized 289 `str.format`
   results before the 256-candidate ceiling.
3. **IR12-RESOURCE-02 — aggregate split variants.** Seventeen receiver and
   seventeen separator variants materialized 867 split pieces and derived
   joins before aggregate count and byte checks.
4. **IR12-RESOURCE-03 — aggregate replacement variants.** A
   5-by-4-by-4-by-4 receiver/old/new/count product materialized 320 replacement
   results before the candidate ceiling.
5. **IR12-RESOURCE-04 — legacy joins before bounds.** List and binary literal
   reconstruction joined large child results before aggregate byte
   validation.
6. **IR12-RESOURCE-05 — syntax-limit fail-open.** More than 8,192 AST nodes
   disabled static evaluation and allowed the common-scope scan to continue
   instead of rejecting fail-closed.
7. **IR12-RESOURCE-06 — incomplete width projection.** Percent and
   `str.format` projections did not add static field widths to prefix/value
   bytes, so a bounded prefix plus a 65,536-character field could allocate
   beyond the claimed result ceiling.
8. **IR12-RESOURCE-07 — quadratic slash scan.** Every candidate slash built
   and searched `source[:index]`; measured slash-heavy inputs scaled from
   approximately 0.038 seconds at 2,000 units to 0.169 at 4,000, 0.614 at
   8,000, and 2.327 at 16,000.

## Execution evidence

- Compatibility controls on the opening exact candidate were clean:
  **49 passed**, **209 passed**, **5 passed**, and **5 passed** across the four
  reviewed slices, each with only the documented Starlette/httpx warning.
- The bounded scope/security subset was **128 passed, 1 warning in 1.02
  seconds**, but the direct closing-block reproducer above was accepted.
- Independent resource probes reproduced all seven resource findings without
  executing catastrophic-width examples. Reviewers edited no files.

Attempt 48 remained failed at **0.050946750 seconds** against the unchanged
**0.050000000-second** ceiling (**0.000946750 seconds / 1.8935%**, maximum
**5%** candidate-specific). Canonical strict-final evidence remained absent,
the companion remained quarantined, and the 55-artifact failed-history
manifest remained
`bca401f2207619ba84422e020104b9a609e0be0f4dc2b42f3ae4fb53d315ceff`.
RSS, allocation, paired/source/Uber latency, correctness, security,
compatibility, custody, resource/deadline, output, rollback, and hosted-use
gates remained non-waived. No production, configuration, runtime, story
status, or Phase 05 change occurred.

## Required disposition

This review grants no approval and must never be reclassified. Remediation
requires a linear, fail-closed slash lexer; exact AST-node rejection;
pre-allocation count and byte checks for every static Cartesian, join,
formatting, split, replacement, and transform path; permanent adversarial
regressions; complete reruns; resealed identities; and a fresh independent
review of the final immutable bundle.
