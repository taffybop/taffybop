# P00-US09 Verification

Status: Done  
Date: 2026-07-29  
Scope: benchmark control registry only

## Identity and reconciliation

| Dimension | Result |
|---|---:|
| Frozen primary gap/story rows | 25 |
| Gap owners | 25 |
| Roles per owner | 4 |
| Role assignments | 100 |
| Frozen case reports | 15 |
| Frozen case-gap rows | 109 |
| Represented case-level gaps | 21 |
| Corpus-only owner gaps | 4 |
| Referenced reviewed-claim corpus | 210 |
| Exact role/row locator references | 209 |
| Unresolved references | 0 |

The matrix has one owner per primary gap. Every owner has the canonical
`target`, `related_positive`, `non_target_regression`, and
`negative_or_ambiguous` quartet. All 109 ordered `## Mapped gaps` rows are
retained losslessly, including their source row SHA-256 and original
three-/four-column table shape.

Independent source parsing pins:

- matrix file SHA-256
  `b89373d7a790de3edac5a38ade1af36ae45085b7f056c2515f1b463b5592542c`;
- 25 raw matrix rows SHA-256
  `85e871613bcf788e220af80659f94bbd30b626d935db35e6cedb60498c3d4c86`;
- 109 raw case-gap rows SHA-256
  `994f3e963e1e51b03dc288814052679841a2a0dca96a7096f7a70e211f35605c`;
- ordered case/gap sequence SHA-256
  `4fafc3d37d621d7187d400e914fb826f40d8821cd03f20818dbb6b13c8d12292`.

The 109 case-row counts in canonical case order are
`5, 5, 7, 6, 5, 9, 7, 9, 9, 12, 6, 9, 5, 6, 9`. Their represented-gap
frequencies are provenance 13, bbox 13, serialization 12, page 10, table
recovery 6, visual 6, chart structure 6, OCR 6, order 6, chart derivation 5,
text 5, cross-view table consistency 4, diagram 3, link 3, false-table
suppression 2, layout 2, diagnostics 2, redline 2, and one each for Unicode,
form, and list behavior. `GAP-BENCHMARK-001`, `GAP-BENCHMARK-002`,
`GAP-COVERAGE-001`, and `GAP-PERFORMANCE-001` are valid corpus-level owners
without case-report rows.

## Role and truth policy

| Role | Assignments | Reviewed status policy/result |
|---|---:|---|
| `target` | 25 | 18 verified, 7 partially verified |
| `related_positive` | 25 | 20 verified, 5 partially verified |
| `non_target_regression` | 25 | 25 verified |
| `negative_or_ambiguous` | 25 | 13 incorrect, 7 not independently verifiable, 5 potentially inferred |

All 75 positive/non-target assignments have semantic-parity masks and
verified or partially verified status. All 25 negative/ambiguous assignments
have neither literal nor semantic parity and use only incorrect,
not-independently-verifiable, or potentially-inferred claims. A quartet uses
four distinct claims, and all role, behavior, assignment-ID, rationale,
claim-ID, and exact first-locator policies fail closed on drift.

The 100 roles use 56 reviewed claims. Cross-gap reuse is deliberate because
one source-grounded claim can be a target for one capability and a non-target
guard for another.

## Case-row anchor audit

The deterministic case-local scorer resolves every row to a reviewed claim.
An independent audit of all 109 rows identified 32 cases where shared gap
vocabulary selected a less specific claim. Explicit finite overrides now bind
those rows to the decisive reviewed region, including:

- the blank insurance signature to the rejected fabricated-signature claim
  while keeping the ACORD logo on its separate image claim;
- the manufacturing `4.3.` heading to its exact visible text claim;
- the NY timetable page-3 shifted row to the exact incorrect table claim;
- repeated ESG serialization rows to separate donut and footer/navigation
  evidence;
- serialization, provenance, OCR, layout, and bbox rows to the claims that
  actually cover the source region described by each frozen row.

The overrides are benchmark-only references, not parser rules. They are keyed
by case, gap, and one-based occurrence, validated against the 210-claim
corpus, and reproduced during both construction and validation.

One bounded limitation remains explicit: `postal-10k` has no reviewed
`page_identity` claim. Its `GAP-PAGE-001` row therefore uses the all-page
metadata/confidence claim as the narrowest available locator proxy. The
original row still preserves the exact printed-page evidence, and the proxy
does not promote unsupported truth.

## Canonical identities and prior-evidence compatibility

| Artifact | Result |
|---|---|
| Control-registry semantic SHA-256 | `d3c734957b507f07508f8eeffe43ac450f50f53d5f42f8cf63e354fe60738fce` |
| Newline-terminated file SHA-256 | `a383938d41d067e0b3e01729d12def7b573764092100ef76228e4c23707c86b5` |
| Canonical characters / UTF-8 bytes | 119,067 / 119,200 |
| Persisted characters / UTF-8 bytes | 119,068 / 119,201 |
| Unchanged Batch A semantic / file | `f6f0ef58…f01ee` / `f987d84c…48de4` |
| Unchanged Batch B semantic / file | `9afe6c09…0d0f` / `7e4728c1…814e` |
| Unchanged Batch C semantic / file | `69c58b8a…eb89` / `1411d75d…5be1` |

Fresh construction, validation, canonical serialization, persisted reload,
and a second construction are identical. Matrix, report, batch, role-policy,
gap/story, case-row, claim, case, region, and persisted-payload drift fail
closed. Batch A/B/C bytes and semantics remain pinned.

All PDFs, expert Markdown/JSON files, frozen reviews, and derived annotations
are approved public and redistributable with no exceptions. The earlier
custody question was a repository/CI execution-boundary gate; that gate is now
resolved and no private-reference or synthetic-replacement branch is needed.

## Commands and results

| Gate | Exact command | Result |
|---|---|---|
| Dedicated + contract + regression | `.venv/bin/pytest -q tests/stories/phase_00/test_p00_us09_control_registry.py tests/contract/test_p00_us09_control_registry_schema.py tests/regression/phase_00/test_p00_us09_control_registry_regression.py` | 57 passed; 1 pre-existing warning |
| Completed Phase 0 + contract + regression | `.venv/bin/pytest -q tests/stories/phase_00 tests/contract tests/regression/phase_00` | 305 passed; 1 pre-existing warning |
| API/serializer | `.venv/bin/pytest -q tests/test_api.py tests/test_serializer.py` | 22 passed; 1 pre-existing warning |
| Full backend | `.venv/bin/pytest -q` | 381 passed; 10 explicit opt-in skips; 1 pre-existing warning |
| Python compile | `.venv/bin/python3 -m compileall -q app tests tracker/benchmarks/llamaparse-15/tools` | Pass |
| Frontend lint (Node 22.18.0) | `/Users/vignesh/.nvm/versions/node/v22.18.0/bin/node node_modules/eslint/bin/eslint.js . --ignore-pattern dist --ignore-pattern .next --ignore-pattern public/pdf.worker.min.mjs` from `frontend/` | Pass |
| Frontend typecheck (Node 22.18.0) | `/Users/vignesh/.nvm/versions/node/v22.18.0/bin/node node_modules/typescript/bin/tsc --noEmit --pretty false` from `frontend/` | Pass |
| Frontend build (Node 22.18.0) | `/Users/vignesh/.nvm/versions/node/v22.18.0/bin/node node_modules/vinext/dist/cli.js build` from `frontend/` | Pass |
| Frontend unit (Node 22.18.0) | `/Users/vignesh/.nvm/versions/node/v22.18.0/bin/node --experimental-strip-types --test tests/*.test.mts` from `frontend/` | 27 passed |
| Frontend built-output (Node 22.18.0) | `/Users/vignesh/.nvm/versions/node/v22.18.0/bin/node --test tests/built-output.test.mjs` from `frontend/` | 1 passed |

The warning is the existing Starlette `httpx` test-client deprecation. The 10
backend skips retain explicit local-model/integration opt-ins. Frontend
commands emit the existing non-failing pyenv rehash warning. The default
`npm run check` selected unsupported Node 20.19.6 even when npm itself was
started through Node 22; all check components passed when invoked directly
with the project-compatible installed Node 22.18.0 runtime.

## Resource observation

Fifty consecutive canonical persisted reloads, each including strict frozen
source reconciliation and a fresh build comparison, completed with p50
**71.899 ms**, p95 **75.652 ms**, and maximum **75.987 ms**. The process peak
RSS was **41.484 MiB** (`43,499,520` bytes) on Darwin. This benchmark-only path
executed no parser, OCR engine, model, network call, or hosted service.

Before P00-US09 there was no control registry (0 owners, 0 role assignments,
and 0 case-gap bindings). After it, the finite result is 25/100/109 with zero
unresolved references. Production request latency and memory are unchanged
because the production tree cannot import this test/reporting module.

## Compatibility and rollback

Production imports remain zero. OpenAPI, `ParseResult`, and `ErrorResponse`
retain canonical SHA-256 values
`3c71271b…983a`, `706a1f63…a91f`, and `3fde7027…5a6`.
No parser, serializer, dependency, configuration, feature flag, source
triplet, frozen case review, portable registry, or reviewed-claim evidence
changed.

Rollback removes only the additive control module, canonical evidence, tests,
and documentation. P00-US04 and Batches A/B/C remain loadable and byte-stable.

## Independent review

Pass — no blocking findings. The reviewer independently ran the 57 focused
tests and 22 API/serializer tests; reproduced the 25/100/109/210 totals, 209
owned references, all role/status/mask counts, three source-row checksums, and
both registry hashes; resolved all 33 overrides; and verified the bounded
postal proxy remains mask-false.

The review also rehashed the matrix, all 15 case reports, all three review
batches, and all 45 triplet artifacts; confirmed 15/15 public-redistributable
custody with no exceptions; reproduced the three public API schema hashes;
found no production imports or embedded registry references; and verified
additive rollback isolation. The postal page-identity proxy remains the only
residual limitation and is not a Definition-of-Done blocker.
