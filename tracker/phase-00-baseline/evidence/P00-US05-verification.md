# P00-US05 Verification

Status: Done  
Date: 2026-07-29  
Scope: reviewed-claim and inclusion-mask contracts only

## Identity and acceptance evidence

| Check | Result |
|---|---|
| Versioned records | `ReviewedClaimRecord` and `ReviewBatch` require schema `1.0`; all nested models are frozen and reject extra fields |
| Claim vocabulary | 15 claim types, the unchanged 6 P00-US01 truth classes, and all 5 normalized review statuses are closed enums |
| Review identity | Every claim requires a trimmed reviewer ID/version and a portable, SHA-256-pinned review path/row identity |
| Source locators | One or more case/page/printed-page/region locators; bbox optional but strictly validated when present |
| Coordinates | Top-left points, `[x,y,width,height]`, displayed after source rotation; all locators reconcile with P00-US04 |
| Scoring masks | Literal implies semantic; literal requires a fully verified literal evidence class |
| Unsupported claims | Incorrect, potentially inferred, and not-independently-verifiable expert claims cannot enter either denominator |
| Derived claims | All measured evidence requires method, finite non-negative tolerance, and tolerance unit; measured evidence cannot enter literal parity |
| Invalid controls | Unknown enums, missing reviewers, duplicate IDs/rows/locators, count drift, bad paths, impossible pages/regions, label drift, unsupported coordinates, contradictory masks, and truth promotion reject |
| Determinism | Canonical compact JSON, canonical claim order, reconciled counts, and semantic SHA-256 are stable |
| Production imports | 0 production imports or textual references to the test-only claim contracts |

## Catastrophe backward-read evidence

The adapter reads all 163 frozen P00-US02 claims and produces one generalized
batch without changing the source file or its P00-US01 projections.

| Dimension | Result |
|---|---:|
| Claims | 163 |
| `visible_text` | 32 |
| `native_data` | 33 |
| `measured` | 89 |
| `inferred` | 8 |
| `unknowable` | 1 |
| Literal-parity included | 62 |
| Semantic-parity included | 163 |
| Derivation records | 89 |
| Lossless P00-US01 projections | 163/163 |
| Registry-valid locators | 163/163 claims |

The measured claims retain the existing method, tolerance, and unit. The
source-reviewed inferred relationships and synthetic rejection controls remain
semantic expectations but are not promoted to literal truth.

## Pinned identities

| Artifact or contract | SHA-256 |
|---|---|
| Frozen P00-US02 truth file | `d14d9f4bdbbffee24961d731b7bca75227eaec6bac77cce7508ded4252c9b4ac` |
| Frozen P00-US04 registry file | `f8024ab7a47df2cedf2d10b996fc8eb140404cdafea0b0a0a9ae2bb059263ceb` |
| Canonical P00-US04 registry | `f7c3bdf460f64c51a7d7e29765ab1e621dc5f59224ddeba8c8a66959c901e4ca` |
| Catastrophe generalized batch | `225fc37091849cc4ab7535b7e1dd51c9c1aa390fa2cb50feba051299ae14da71` |
| `ReviewedClaimRecord` schema | `49c43ce26b4f2cb3b0f602441a1c04f12ecd55ca9731ea9d78f7473ce3f3f8a5` |
| `ReviewBatch` schema | `c3f86ca181cf02fda6c7a395ec3d44d65ac6de8010b1db145588e08b0e5ed346` |
| Unchanged P00-US01 `Annotation` schema | `914e787b8d0475a2ac56278564575cad5b149999f0319b90caf129e283d10268` |

The canonical generalized catastrophe payload is 182,506 Unicode characters
and 182,598 UTF-8 bytes. It is a backward-read projection, not a replacement
for or mutation of the frozen P00-US02 file.

## Commands and results

| Gate | Exact command | Result |
|---|---|---|
| Dedicated + contract + regression | `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -p no:cacheprovider tests/stories/phase_00/test_p00_us05_reviewed_claim_contracts.py tests/contract/test_p00_us05_reviewed_claim_schema.py tests/regression/phase_00/test_p00_us05_reviewed_claim_contracts_regression.py` | 48 passed; 1 pre-existing warning |
| Phase 0 regression | `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -p no:cacheprovider tests/regression/phase_00` | 17 passed; 1 pre-existing warning |
| Impacted Phase 0 + contract + API/serializer | `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -p no:cacheprovider tests/stories/phase_00 tests/regression/phase_00 tests/contract tests/test_api.py tests/test_serializer.py` | 200 passed; 1 pre-existing warning |
| API/schema/serializer | `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -p no:cacheprovider tests/test_api.py tests/test_serializer.py tests/contract` | 47 passed; 1 pre-existing warning |
| Full backend | `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -p no:cacheprovider` | 254 passed; 10 explicit opt-in skips; 1 pre-existing warning |
| Frontend typecheck | `/opt/homebrew/opt/node@24/bin/node node_modules/typescript/bin/tsc --noEmit --pretty false` from `frontend/` | Pass |
| Frontend lint | `/opt/homebrew/opt/node@24/bin/node node_modules/eslint/bin/eslint.js . --ignore-pattern dist --ignore-pattern .next --ignore-pattern public/pdf.worker.min.mjs` from `frontend/` | Pass |
| Frontend unit | `/opt/homebrew/opt/node@24/bin/node --experimental-strip-types --test tests/*.test.mts` from `frontend/` | 27 passed |
| Python compile | `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m compileall -q tests/benchmarks tests/stories/phase_00 tests/contract tests/regression/phase_00` | Pass |

The pytest warning is the pre-existing Starlette `httpx` test-client
deprecation. The 10 full-suite skips retain the same explicit real-model,
full-pipeline, and cross-format opt-in conditions. The frontend commands also
reported the existing non-failing `pyenv` shim rehash warning; all exited zero.

## Quality and resource measurement

One fresh process loaded the registry and frozen catastrophe truth, projected
and validated all 163 claims, generated both primary JSON schemas, and
serialized the canonical batch in **14.416 ms**. The process maximum resident
set size was **37.406 MiB** (`39,223,296` bytes); total process wall time,
including interpreter imports, was 0.18 s. This is a single contract-validation
observation, not a parser performance distribution. It executed no parser,
OCR engine, model, network call, or hosted service.

## Public compatibility and rollback

The regression suite reasserted the unchanged public identities:

- OpenAPI: `3c71271be81fc55e8f85229e1ffdf01ef6a7977c4638a87449617749a1a2983a`
- `ParseResult`: `706a1f63bf77eaa6cc3f114b9b5c976d07d764de04a8beffa45cd2b04aafa91f`
- `ErrorResponse`: `3fde7027b8452307282b52870914475672aed4b4326018867fdf467922d1a5a6`

Rollback removes the additive claim-contract module/tests from active use. The
production tree has no dependency on them, so rollback has no parser, API,
serializer, output, dependency, configuration, or feature-flag effect. The
immutable sources and P00-US01–P00-US04 evidence remain retained.

## Downstream denominator audit

The contract story does not populate corpus claims. While checking whether its
batch rules can represent the next stories one-to-one, the audit counted
**210** current expert-validation table rows:

- Batch A cases: 71 rows; `manufacturing-report` has 21, not the planned 23.
- Batch B cases: 76 rows.
- Batch C cases: 63 rows.

Normalized row statuses are 121 verified, 41 partially verified, 21 incorrect,
17 not independently verifiable, and 10 potentially inferred. At P00-US05
completion, the approved P00-US06/P00-US08 target remained 73/212, so this was
a P00-US06 Definition-of-Ready issue. The requester subsequently approved the
source-aligned 71/210 correction without mutating the frozen review reports;
see
[`P00-US06-claim-denominator-correction.md`](../decisions/P00-US06-claim-denominator-correction.md).

## Independent review

**Pass — no P00-US05 blockers.** Independent review reproduced all six
acceptance criteria, all 10 Definition-of-Done gates, the full
evidence/status/mask policy matrix, 163 lossless catastrophe projections, 168
registry-valid locators, 89 derivations, 62 literal masks, 163 semantic masks,
all pinned hashes/sizes, production isolation, and rollback.

The reviewer reran 48 focused, 17 Phase 0 regression, 200 impacted, 47
API/schema, and 254 full-backend tests with the same 10 owned skips, plus
frontend typecheck/lint and 27/27 unit tests. An independent resource
observation measured 13.345 ms and 37.219 MiB. The 210-versus-212 denominator
finding was independently confirmed as a P00-US06 readiness blocker rather
than a P00-US05 defect.
