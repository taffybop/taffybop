# Phase 0 Completion and Exit Summary

Status: Complete — exit criteria Pass  
Date: 2026-07-29  
Authorization boundary: Phase 0 only; Phase 1 not started

## Outcome

All ten Phase 0 stories and all **44/44 story points** are Done. Phase 0 now
has a reproducible, source-grounded, legally redistributable PDF baseline with
strict contracts for fixtures, truth classes, reviewed masks, control roles,
immutable execution, compatibility, resources, diagnostics, and cost.

The phase did not change production parsing behavior. It did not start
P01-US01, install or upgrade dependencies, download a model, call a network or
hosted service, change a public API/schema, commit, push, or open a PR.

## Story outcomes

| Story | Points | Outcome |
|---|---:|---|
| P00-US01 | 3 | Versioned fixture, annotation, metric, and run contracts |
| P00-US02 | 5 | Hash-pinned catastrophe source truth and negative controls |
| P00-US03 | 5 | Five isolated catastrophe reference runs and compatibility report |
| P00-US04 | 3 | Portable 15-case, 30-page, 45-artifact registry and custody decision |
| P00-US05 | 3 | General reviewed-claim, locator, derivation, and mask contracts |
| P00-US06 | 5 | Batch A: 71 reviewed claims |
| P00-US07 | 5 | Batch B: 76 reviewed claims |
| P00-US08 | 5 | Batch C: 63 claims; complete 210-claim corpus |
| P00-US09 | 5 | 25 gap owners, 100 role controls, and 109 case-gap rows |
| P00-US10 | 5 | Immutable offline corpus runner and 12-dimension semantic report |
| **Total** | **44** | **10/10 Done** |

Every story passed its fresh Definition of Ready, dedicated and impacted
tests, compatibility gates, resource/evidence requirements, rollback check,
completion report, and independent review before the next story started.

## Phase exit criteria

| Exit criterion | Result | Evidence |
|---|---|---|
| Manifest and metric schemas tested | Pass | Strict v1 contracts and negative schema tests |
| Explicit/measured/unsupported truth separated | Pass | Catastrophe bundle plus reviewed evidence classes and masks |
| Current JSON/Markdown/quality/time/memory baseline retained | Pass | Five-run catastrophe and final corpus evidence |
| 15 triplets and 30 page maps complete | Pass | 15/15 cases, 30/30 pages, 45/45 artifacts |
| Custody and redistribution resolved | Pass | All triplets and derived annotations public/redistributable, no exceptions |
| Reviewed corpus complete | Pass | 210 claims, 271 locators, 109 literal and 162 semantic masks |
| Reusable controls complete | Pass | 25 owners, 100 assignments, 109 case-gap rows, zero unresolved |
| Immutable corpus run complete | Pass | 15/15 success, 30/30 pages, zero partial/error/timeout/skip |
| Semantic dimensions separate | Pass | 12/12 canonical reports; no composite quality score |
| Unsupported truth excluded | Pass | 48 exclusions and 25 safety controls; zero false automatic scores |
| Repeatability and performance declared | Pass | All stable output hashes; matching environment within 25% |
| Errors, collisions, partials, skips, timeouts tested | Pass | Dedicated synthetic and retained-evidence contract/regression tests |
| API/schema/production isolation preserved | Pass | Pinned identities and zero production benchmark imports |
| Complete phase regression rerunnable | Pass | Commands and installed local environment recorded |

Phase exit result: **13/13 Pass**.

## Final verification

| Gate | Result |
|---|---:|
| P00-US10 dedicated + contract + regression | 79 passed |
| Complete Phase 0 story + contract + regression | 384 passed |
| API/serializer compatibility | 22 passed |
| Full backend | 460 passed, 10 explicit opt-in skips |
| Python compile | Pass |
| Frontend typecheck and lint | Pass |
| Frontend build | Pass |
| Frontend unit / built-output | 27 / 1 passed |
| P00-US10 independent review | Pass, no blockers |

The backend warning is the pre-existing Starlette `httpx` test-client
deprecation. The ten skips remain explicitly owned real-model/integration
opt-ins. Frontend checks retain the pre-existing non-failing pyenv rehash
warning and vinext dynamic-route classification notice.

## Final benchmark and performance

The authoritative P00-US10 completion baseline is
`evidence/p00-us10-corpus-20260729-03/`.

| Measure | Result |
|---|---:|
| Run cases/pages | 15/15; 30/30 |
| Run failure states | 0 partial, error, timeout, or skip |
| Reviewed claims | 210 |
| Literal / semantic eligible | 109 / 162 |
| Unsupported exclusions | 48 |
| Automatic semantic scores | 0 |
| Diagnostic-only eligible claims | 162 |
| Stable semantic JSON / Markdown | 15/15 / 15/15 |
| Coordinator latency p50 / p95 | 9,817.816 / 46,706.960 ms |
| Coordinator total | 216,711.552 ms |
| Parse total / worker CPU total | 199,426.172 / 182,206.879 ms |
| Peak RSS p50 / maximum | 1,434.11 / 2,450.61 MiB |
| Raw JSON / Markdown bytes | 5,289,461 / 116,260 |
| Performance comparison | Matching environment; all 25% bounds pass |
| Hosted requests / tokens / billed USD | 0 / 0 / 0.00 |

Run tree identity: 94 files, 5,922,586 bytes,
`a145ac7e2b56a0631c27b565a131e7ec83061ebf69e7c8c66692f383126541da`.
Run/report semantic identities are
`e9037328dbd5f61fb770c69cc0f6acbd4ec7f64a80896cd50136d7f5b24a3ba7`
and
`ceb8765bb06ad4c60bbaeb39f69fff932595163da1811611ff2f86ea2c7fb4cb`.

## Source custody

The user confirmed all 15 PDF/Markdown/JSON triplets and all derived
annotations are public and redistributable with no exceptions. The approved
uses cover workspace retention, repository commit, benchmark redistribution,
local validation, private CI, and committed CI. Every current artifact still
matches the portable registry's exact hash and byte size.

The original custody questions existed to prevent accidental repository or CI
redistribution without authority. The user's no-exceptions confirmation
closed that gate; no private-reference or synthetic-replacement branch is
needed for this corpus.

## Files and contracts changed

Phase 0 added only test/reporting contracts, evidence, tests, and tracker
documentation:

- benchmark contracts, source truth, portable registry, reviewed claims,
  control registry, and corpus runner under `tests/benchmarks/`;
- dedicated story, contract, and regression tests under `tests/`;
- immutable evidence and completion reports under
  `tracker/phase-00-baseline/`;
- tracker status, metrics, and benchmark documentation.

No production file or public runtime contract changed. OpenAPI,
`ParseResult`, and `ErrorResponse` retain
`3c71271b…983a`, `706a1f63…a91f`, and `3fde7027…a5a6`.

## Remaining limitations and blockers

No Phase 0 completion blocker remains. The retained limitations are explicit:

- the 15-case corpus is native-text PDF only; it has no fully scanned,
  direct-image, image-only-PDF, DOCX, PPTX, or XLSX semantic twins;
- the 210 review rows classify expert claims but do not contain executable
  expected-value predicates, so Phase 0 truthfully reports 162 eligible claims
  as diagnostic-only rather than fabricating semantic passes;
- the postal page row retains the one documented mask-false metadata locator
  proxy until a dedicated reviewed page-identity claim exists;
- the parser still emits no document warnings for many reviewed defects; this
  is retained as a diagnostics limitation, not normalized into success;
- the performance baseline is reference-environment evidence, not a production
  release or concurrency service-level gate.

Cross-format twins remain a later Phase 7 readiness dependency. Executable
claim-specific evaluators and production instrumentation belong to later,
separately authorized stories.

## Rollback readiness

Rollback is additive and does not require a production deployment reversal.
The active test-only modules/tests can be removed from validation while all
source triplets, annotations, registries, legacy runs, and immutable Phase 0
run directories remain retained as audit evidence. No public consumer or
production request path depends on Phase 0 code.

## Readiness recommendation

**Phase 0 exit: Pass. Phase 1 dependency readiness: Pass.**

P01-US01 may be evaluated for a fresh Definition of Ready only after a new
explicit Phase 1 authorization. This recommendation is not authorization:
Phase 1 has not started, and no Phase 1 file or status was changed.
