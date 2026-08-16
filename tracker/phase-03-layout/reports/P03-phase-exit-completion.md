# Phase 03 Exit Completion Report

Status: Complete with approved, active, time-bounded metrics exception renewal  
Phase: 03 — Layout  
Stories: 8/8 Done  
Points: 38/38 Done  
Completed: 2026-08-03

## Exit decision

Phase 03 is complete under requester-approved, candidate-specific renewal
`P03-US08-LATENCY-EXCEPTION-RENEWAL-20260803-FRONTEND-BBOX`. P03-US01–P03-US07
retain their strict passing evidence. P03-US08 is Done with an approved active
exception for one near-boundary latency observation, renewed only across the
frontend bbox compatibility correction. The original decision and waiver
remain immutable historical records.

This is **not a strict current-artifact metrics pass**. Attempt 48 remains an
immutable `failed_measurement_candidate`, the complete companion remains at its
post-seal-invalid quarantine path, and no canonical strict final P03-US08
artifact exists. The exception neither changes the v1 metrics contract nor
relabels either source artifact.

## Exit criteria

| Criterion | Result |
|---|---|
| External table and visual captions remain distinct from owned content | Pass — retained P03-US01/P03-US02 evidence |
| Source notes and footnotes are grounded and explicitly related | Pass — retained P03-US03 evidence |
| Relationship-aware order and bbox ownership remain coherent | Pass — retained P03-US04 evidence |
| Source-visible redline/text-run semantics remain non-destructive | Pass — retained P03-US05 evidence |
| Form controls and key-value relationships remain explicit | Pass — retained P03-US06 evidence |
| Lists and legal clauses preserve hierarchy and continuation | Pass — retained P03-US07 evidence |
| Physical and printed page identity remain distinct | Pass — P03-US08 exact 30-page reviewed denominator |
| Running regions are typed, ordered, and serialized once | Pass — P03-US08 exact 47-region and Body/Full result |
| P03-US08 strict latency ceiling | Exception — attempt 48 New York projection p95 is 1.8935% over; approved candidate-specific boundary is at most 5% |
| P03-US08 RSS and all non-latency gates | Pass / not waived — strict companion evidence and executable waiver guard |
| Default-off rollback | Pass — exact configured predecessor is returned with zero P03-US08 work |

## P03-US08 exception adjudication

The primary evidence is immutable
[attempt 48](../evidence/P03-US08-running-region-metrics-attempt-48-failed.json),
158,921 bytes with raw SHA-256
`1289f186c1cd6ee7f99eaa843f66e5416f15c0215e205e0ed5936737cd2a7123`.
It passes Uber source/projection and New York source extraction. Its sole
failure is New York projection p95: **0.050946750 seconds** against the strict
**0.050000000-second** ceiling, an overrun of **0.000946750 seconds / 1.8935%**.
Its fail-fast campaign contains no paired-worker result, so it is not used to
claim paired latency or memory acceptance.

The companion
[post-seal-invalid campaign](../evidence/P03-US08-running-region-metrics-attempt-31-post-seal-invalid.json)
remains quarantined and is not a canonical final artifact. It completed all
20 paired workers and passed every strict aggregate gate. Its peak RSS deltas
are **12,877,824 bytes** for Uber and **47,316,992 bytes** for New York, both
below the 64 MiB ceiling. Its paired p95 latencies are **0.267703208 seconds**
and **1.447505041 seconds**, respectively, and pass their strict gates. Peak
RSS, paired-parser latency, and every other non-excepted gate are not waived.

Current code has renewed 86-path manifest
`b5bfab2739f231a57abddf787a6c566c5fddec5b2128bd4892f3682622a06fcc`.
Exactly two frontend paths differ from attempt 48, leaving **84/86** required
paths identical. `measured_backend_parser_runtime_paths_match_original` is
true: all **29** `app/**` backend paths remain identical, with manifest
`3f60c9b297760cf5fc0b1e89cd0ef02666f35c77ccc474202b80e26915703bb7`.
Current code differs from the companion at exactly four paths: the authorized
frontend validator/test pair plus the companion's historical retained-artifact
validator/test pair, leaving **82/86** paths identical. The signed renewal
verifies this exact chain rather than treating either retained candidate as
current strict-final evidence.

## Renewal custody, expiry, and reversion

The active approved decision is
[P03-US08-frontend-bbox-latency-exception-renewal.md](../decisions/P03-US08-frontend-bbox-latency-exception-renewal.md),
and the active executable record is
[P03-US08-frontend-bbox-latency-waiver-renewal.json](../evidence/P03-US08-frontend-bbox-latency-waiver-renewal.json).
They bind the original immutable records, exact frontend-only delta, current
manifest, candidates, failed history, default-off rollback, expiry, exclusions,
and zero hosted use.

The original decision remains 3,476 bytes with raw SHA-256
`7bea63acad8403e442362edd8aabe0f4db084e6abd0cdd59e2b148b40a8b0d25` at
[P03-US08-provisional-latency-exception.md](../decisions/P03-US08-provisional-latency-exception.md).
The original executable waiver remains 4,873 bytes with raw SHA-256
`1fe75bc3d749730938653030052d463340eb2e856b810e0586e9afb12e9a72c8`
and semantic SHA-256
`0d3cd13942dd465c537dd7075baf0d2e8b30bc5dd891af55622c07f493610554` at
[P03-US08-provisional-latency-waiver.json](../evidence/P03-US08-provisional-latency-waiver.json).
It binds the failed ledger through attempt 55, whose manifest SHA-256 is
`bca401f2207619ba84422e020104b9a609e0be0f4dc2b42f3ae4fb53d315ceff`.
Attempts 52–55 are history only and are not the exception basis.
Attempts 54–55 completed from an older disconnected Codex thread, which has
now ended. Their final reconciliation changed no product/runtime byte. The
2,383-test complete-backend run below is retained pre-renewal evidence: it
predates the frontend compatibility correction and renewal guard/test changes,
so it is not described as a fresh current-required-code full-suite run. All 29
`app/**` backend/parser paths are unchanged, and the fresh 291-test focused gate
plus 28-test renewal guard cover the active renewal chain.

The renewal must be reviewed by **2026-09-02**. It expires earlier on any
further required-code custody change, production enablement of running regions,
or Phase 04 exit. Expiry or revocation returns P03-US08 to In Progress and
blocks dependent exit claims until a strict current-code final campaign passes
or a new explicit decision is approved.

`PARSER_LAYOUT_RUNNING_REGIONS_ENABLED` remains false by default. Setting it to
false is the rollback: the module is not loaded, extraction and projection are
skipped, and the exact configured predecessor is returned.

## Verification

- Fresh active-renewal six-file Phase 03/US08 gate: **291 passed, 1 intentional
  strict-final skip, 1 warning in 65.87 seconds**.
- Focused active-renewal guard: **28/28 passed, 1 pre-existing Starlette warning
  in 16.88 seconds**.
- Retained pre-renewal complete-backend regression: **2,383 passed, 11 skipped,
  163 warnings in 892.68 seconds (14:52)**. All 29 `app/**` backend/parser paths
  remain identical; this is not claimed as a fresh current-required-code run.
- Python compilation: **Pass**. `uv lock --check --offline`: **Pass — 140
  packages resolved with no lock drift**.
- Frontend Node **24.14.0** lint, typecheck, production build, **106/106 unit
  tests**, and **1/1 bundle test**: **Pass** after the compatibility correction;
  responsive checks are **22/22**.
- Live `clinical-study.pdf` UI verification: **Pass** — four physical pages,
  printed label `1/21`, 22 canonical blocks, and working Body/Full views.
- Strict canonical-final test: the single skip is expected and remains
  disclosed because the canonical strict final artifact is absent.
- Hosted requests, tokens, and cost: **0 / 0 / $0**.

Counts belong to their named invocations and must not be summed across
overlapping reruns.

## Limitations and next boundary

The exception is narrow: only attempt 48's New York projection p95 is accepted
for P03-US08 and Phase 03 exit adjudication. It does not waive correctness,
quality, security, API/schema compatibility, allocation, peak RSS,
paired-parser latency, source-extraction latency, Uber projection latency,
resource/deadline limits, output sizes, dependency/input/code custody,
rollback, or hosted-use gates. It does not authorize production enablement and
cannot be reused by another candidate, story, or phase.

The deferred task is to replace this renewed exception with a strict
current-code final campaign, or explicitly renew it before expiry. Phase 04
remains Proposed and unstarted. Starting it or changing its status requires
separate authorization.

## Hardened superseding renewal — 2026-08-03

The preceding frontend-only renewal and Phase 04 boundary statements remain
the historical Phase 03 exit checkpoint. Current applicability is governed by
[`P03-US08-LATENCY-EXCEPTION-RENEWAL-20260803-PHASE04-TABLES-HARDENED`](../decisions/P03-US08-phase04-tables-latency-exception-hardened-renewal.md)
and its
[executable record](../evidence/P03-US08-phase04-tables-latency-waiver-hardened-renewal.json),
bound to
[the independent approval](../evidence/P03-US08-phase04-tables-hardened-renewal-independent-approval.md).
The decision is **25,343 bytes** with raw SHA-256
`bb3107b29f5a01876a64ee0179e1bff32b16bb93ecffa51da2f54c2d65510682`;
the record is **22,113 bytes** with raw SHA-256
`5d0ac8411fd785eda1db1cbc01d2082ea09d65482ddba4796982cf0f60db4655`
and semantic SHA-256
`a8e38c8269e5faf1e03f5bff942dd97b74bea87f6ae26f9c6c175e50ed6eba87`.
All earlier byte identities and evidence claims remain unchanged.

Attempt 48 is still failed: `ny-timetable` /
`running_region_projection` p95 is **0.050946750 seconds** against the unchanged
**0.050000000-second** ceiling, **0.000946750 seconds / 1.8935%** over within
the maximum **5%** candidate-specific authorization. The companion remains
quarantined, no canonical strict-final artifact exists, and Phase 03 is not a
strict current-artifact metrics pass. Only default-off Phase 04 table changes
admitted and structurally sealed by the executable record are removed from the
former blanket required-code/Phase-04-exit trigger; Phase 04 exit within that
unchanged scope does not itself expire the renewal. Production enablement,
admitted-scope expansion, or any protected running-region semantic, runtime,
or custody change requires a new explicit decision and expires the renewal
before the change. Review is due no later than **2026-09-02**. Exact-predecessor
default-off rollback and every non-waived RSS, paired/source/Uber latency,
correctness, security, compatibility, custody, resource/deadline, output,
rollback, and hosted-use gate remain mandatory.
