# P03-US08 Phase 04 Operative Administrative Renewal — Independent Review

Status: **APPROVED — exact frozen administrative bundle only**  
Reviewed: 2026-08-07  
Reviewer role: Independent policy/custody review lane; not the bundle author  
Scope: Administrative classifier for unrelated, default-off Phase 04 table
development only

## Exact reviewed bundle

| Artifact | Bytes | Raw SHA-256 |
|---|---:|---|
| Decision | 10,226 | `93b95e2d07b4e58a6f8f9a8ae43e587ec199d4fbaaeac4d59c8770702fd32504` |
| Machine-readable renewal | 9,722 | `99ac85518d573cb64abd4127444e45d631e767ec8ee236104c389fc420619c41` |

The decision is
`tracker/phase-03-layout/decisions/P03-US08-phase04-tables-latency-exception-operative-administrative-renewal.md`.
The machine-readable renewal is
`tracker/phase-03-layout/evidence/P03-US08-phase04-tables-latency-waiver-operative-administrative-renewal.json`.
The exact `change_classifier`, canonicalized as the UTF-8 output of
`jq -j -S -c '.change_classifier'`, has SHA-256
`a776f175759752777cbc4db465386b8af17737552750b0c5411d6ca1622f3a30`.

The immutable review request was also observed at **3,561 bytes**, raw
SHA-256
`6af5710ea4ce0305f00bcbda49faeb87f0576c3edc0dca72ca41fc132288466a`.
It remains a request record and is not treated as approval.

## Independent methods and execution

- `wc -c` and `shasum -a 256` recomputed the decision, renewal, request,
  attempt-48, and attempt-55 raw identities. The decision and renewal matched
  both the review request and the renewal's embedded decision identity.
- `jq -j -S -c '.change_classifier' ... | shasum -a 256` independently
  reproduced the classifier digest above.
- The project's strict duplicate-rejecting JSON loader parsed the renewal,
  and an exact top-level-field check passed. A `jq -e --slurpfile attempt ...`
  comparison bound the renewal's observation, ceilings, status, classifier,
  expiry, default-off constraints, and Phase 05 prohibition to attempt 48 and
  the closed renewal record.
- Every failed artifact from attempts 01 through 55 was read as a regular
  file, checked for canonical retained-artifact bytes and a valid recomputed
  semantic SHA-256, reduced to its ordered path/size/raw/status/semantic
  identity, and hashed with the project's canonical JSON method. The result
  was exactly
  `bca401f2207619ba84422e020104b9a609e0be0f4dc2b42f3ae4fb53d315ceff`.
- Decimal arithmetic independently reproduced `0.000946750` seconds,
  fraction `0.018935`, and `1.8935%` from the exact observed and ceiling
  values, and confirmed the result is within the maximum `5%` bound.
- The canonical strict-final path was checked directly and remained absent.
  All ten Phase 05 story records and the Phase 05 phase record remained
  Proposed.
- The focused inherited exception command selected the immutable-ancestry,
  exact-observation, running-region rollback, non-waiver, expiry, and Phase 05
  controls in
  `tests/performance/test_p03_us08_provisional_latency_exception.py`: **11
  passed, 1 documented Starlette deprecation warning in 0.39 seconds**.
- The focused default-off and rollback command selected the Phase 04 flag
  topology/policy, table hook identity, P04-US01 flag-off witness, and P03-US08
  configuration/predecessor controls across the Phase 03/04 contract and
  story suites: **7 passed, 1 documented Starlette deprecation warning in
  0.27 seconds**.

## Required checks

| # | Result | Independent finding |
|---:|---|---|
| 1 | **Pass** | The sole exception remains failed attempt 48 for `ny-timetable` / `running_region_projection` / `latency_p95_seconds`: exactly `0.050946750` seconds observed versus the unchanged `0.050000000`-second ceiling, delta `0.000946750`, fraction `0.018935` (`1.8935%`), within but not redefining the maximum `5%` candidate-specific bound. |
| 2 | **Pass** | Attempt 48 is unchanged at 158,921 bytes and raw SHA-256 `1289f186c1cd6ee7f99eaa843f66e5416f15c0215e205e0ed5936737cd2a7123`; its recomputed semantic SHA-256 is `51433843638d69a2d09ced0d96a44a34323b1f5ece9c890c7c91088bac2df2e5`. Attempt 55 is unchanged at 161,497 bytes and raw SHA-256 `62fff75d28fcc666a606a755b677e20720ebfd76b50d1940f29687e012257b6e`. Exactly 55 failed artifacts reproduce the sealed manifest above. |
| 3 | **Pass** | Attempt 48 remains `failed_measurement_candidate`; the canonical strict-final artifact is absent. The decision and renewal explicitly prohibit a Phase 03 strict current-artifact metrics-pass claim and do not promote the quarantined companion. |
| 4 | **Pass** | The conjunctive classifier admits only exclusively table-owned, default-off work for `P04-US01`, `P04-US02`, `P04-US04`, and `P04-US03`, in that order, with at most one story In Progress. Shared-file placement, indirection, mixed effects, and ambiguity do not qualify and fail closed before reliance. |
| 5 | **Pass** | The renewal expires before production enablement/reliance; any relevant P03 running-region semantic, runtime, reachability, metrics, dependency, benchmark, input, evidence-custody, or rollback change; any ceiling/non-waived-gate change; scope expansion; classifier relaxation; or any Phase 05 work/status transition. |
| 6 | **Pass** | Peak RSS/allocation, paired-parser and source/Uber latency, correctness/quality/source fidelity/non-fabrication, security/malformed/timeout/fail-closed, API/schema/serializer/frontend/predecessor compatibility, all named custody classes, memory/CPU/file-descriptor/process/deadline resources, output/diagnostic bounds, rollback/default-off, hosted-use/request/token/cost, and every other story/exit gate remain unwaived. |
| 7 | **Pass** | `PARSER_LAYOUT_RUNNING_REGIONS_ENABLED` and the four ordered table switches remain false by default. The running-region rollback performs zero P03-US08 work and returns the exact configured predecessor; disabling the table chain independently restores the predecessor with no table-stage work. Focused executable controls passed. |
| 8 | **Pass** | Review is due no later than 2026-09-02 and absolute expiry is `2026-09-02T23:59:59Z` if no earlier trigger applies. Production is never authorized; expiry returns P03-US08 to In Progress and blocks dependent completion and exit claims. |
| 9 | **Pass** | Sponsor authorization is explicitly distinct from independent review (`sponsor_authority_is_independent_review=false`, with no approval claimed by the request). This leaf supplies the independent classifier review and does not reinterpret the sponsor as its own reviewer. |

## Disposition

The exact frozen administrative bundle identified above is **approved for its
closed classifier only**. No blocking, Major, correctness, security, custody,
compatibility, performance, or boundary finding was identified in this
administrative review.

This approval permits the already sponsor-authorized development continuity
only when every classifier predicate remains true. It is not a strict current-
artifact P03-US08 metrics pass and cannot substitute for exact final-code,
story, production/security, metrics/custody, retained-evidence, Phase 04 exit,
or production-enablement approval. Any change to either reviewed bundle
artifact invalidates this exact-bundle approval; every declared early-expiry
condition remains fail-closed. Phase 05 remains unauthorized and Proposed.
