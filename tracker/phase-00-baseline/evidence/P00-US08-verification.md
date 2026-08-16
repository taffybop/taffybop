# P00-US08 Verification

Status: Done  
Date: 2026-07-29  
Scope: reviewed claims Batch C only

## Identity and reconciliation

| Dimension | Result |
|---|---:|
| Cases | 5 |
| Expert-validation rows / claims | 63 / 63 |
| Registered locators | 75 |
| `egov-survey` | 12 |
| `health-report` | 12 |
| `postal-10k` | 12 |
| `settlement-agreement` | 10 |
| `uber-earnings` | 17 |
| Verified | 34 |
| Partially verified | 9 |
| Incorrect | 9 |
| Potentially inferred | 5 |
| Not independently verifiable | 6 |
| Literal-parity included | 32 |
| Semantic-parity included | 43 |
| Measured derivations | 3 |

Every bounded expert-validation row maps to one claim. The independent test
reader handles four- and five-column review tables, preserves the inline-code
pipe in health's ``Header `| 103` ``, and stops at the next level-two heading.
Grouped item ranges and multi-page review rows remain one claim each.

## Evidence and type classifications

| Evidence class | Claims |
|---|---:|
| `visible_text` | 29 |
| `native_data` | 12 |
| `inferred` | 12 |
| `unknowable` | 5 |
| `measured` | 3 |
| `embedded_data` | 2 |

| Primary claim type | Claims |
|---|---:|
| `text` | 17 |
| `table` | 8 |
| `chart` | 8 |
| `metadata` | 8 |
| `page_identity` | 5 |
| `image` | 4 |
| `artifact_inventory` | 3 |
| `link` | 2 |
| `geometry` | 2 |
| `structure` | 2 |
| `diagram` | 2 |
| `text_style` | 1 |
| `relationship` | 1 |

Incorrect, potentially inferred, and not-independently-verifiable rows enter
neither denominator. Partial rows are semantic-only. Inferred, measured, and
unknowable evidence never enters literal parity.

Only Uber rows 06, 08, and 10 carry measured derivations. They use PDF-vector
interpolation against printed endpoints with tolerances of 2 USD billions,
0.25 USD billions, and 0.25 percentage points respectively. The health bubble
chart remains `incorrect` plus `inferred`, has no derivation, and is excluded
from both masks because its review does not establish a quantified
same-unit tolerance.

## Locator and provenance evidence

The 63 claims use 75 registered locators. Physical-to-printed page identities
are:

| Case | Physical page | Printed page | Locators |
|---|---:|---:|---:|
| `egov-survey` | 1 | 37 | 12 |
| `health-report` | 1 | 103 | 12 |
| `postal-10k` | 1 / 2 / 3 | 2 / 46 / 49 | 5 / 8 / 7 |
| `settlement-agreement` | 1 | 24 | 10 |
| `uber-earnings` | 1 / 2 / 3 | 1 / 5 / 6 | 5 / 11 / 5 |

Claim-wide bboxes remain `null` where the frozen review does not establish
coordinate truth. Page, source-region, and derived-artifact scopes are
explicit. The five review files retain these SHA-256 identities:

| Frozen case review | SHA-256 |
|---|---|
| `egov-survey.md` | `bbdb74c3c05204006c67d5868ad9f7229221c469d6e31a04906a67ac4980bc25` |
| `health-report.md` | `13e74b08061571472993123e5bcfa1ac00ca96a5191a4887bcb94589ccc876f5` |
| `postal-10k.md` | `e0eb3d81b012018a1b1a2d4d37a17f5c9f62c0014e52bd652845d6ac7fc9cce7` |
| `settlement-agreement.md` | `1e1680bd2b28eca6c68c364a32e1381d64ae7d5c8155325ac03c10e4d8addba9` |
| `uber-earnings.md` | `344aa02fc3e0315b912e42489331951c39f6bdbb9b7e0e4fdfc17ebb44018567` |

The no-exceptions public/redistributable custody decision covers all source
PDFs, expert Markdown/JSON files, and derived annotations. Tests rehash and
size-check all 15 Batch C triplet artifacts against the portable registry.

All nine Batch C source pages were rendered through `pdfplumber`/PDFium and
visually inspected. The pages were legible and complete. Uber page 2 visibly
contains the printed endpoints used by the three bounded interpolation
methods; health page 1 visibly contains chart axes and bubbles but not the
expert output's exact latent row values.

## Canonical identities and complete-corpus compatibility

| Artifact | Result |
|---|---|
| Batch C canonical semantic SHA-256 | `69c58b8ab7a3b9bdd21bc49183fb5334ee88bee1a4850061820b551ae416eb89` |
| Batch C newline-terminated file SHA-256 | `1411d75d2701e51b815f9f3c0e0e5ba5f799f6ec32ca2788cd31ee4f69f05be1` |
| Batch C canonical characters / UTF-8 bytes | 71,202 / 71,379 |
| Unchanged Batch A semantic / file SHA-256 | `f6f0ef58…f01ee` / `f987d84c…48de4` |
| Unchanged Batch B semantic / file SHA-256 | `9afe6c09…0d0f` / `7e4728c1…814e` |

Fresh Batch C construction, persisted reload, schema/registry validation, and
a second construction are identical. Schema-valid evidence drift and frozen
review drift fail closed.

Across Batches A, B, and C, all 210 claim IDs and all 210 provenance row
identities are unique across 15 cases. The complete corpus has 271 locators;
statuses 121 verified, 41 partial, 21 incorrect, 17 unverifiable, and 10
potentially inferred; evidence classes 107 visible, 42 native, 40 inferred, 14
unknowable, 3 embedded, and 4 measured; 109 literal masks, 162 semantic masks,
and 4 bounded derivations.

## Commands and results

| Gate | Exact command | Result |
|---|---|---|
| Dedicated + contract + regression | `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -p no:cacheprovider tests/stories/phase_00/test_p00_us08_reviewed_claims_batch_c.py tests/contract/test_p00_us08_reviewed_claim_batch_c.py tests/regression/phase_00/test_p00_us08_reviewed_claims_batch_c_regression.py` | 25 passed; 1 pre-existing warning |
| Batch A+B compatibility | `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -p no:cacheprovider tests/stories/phase_00/test_p00_us06_reviewed_claims_batch_a.py tests/contract/test_p00_us06_reviewed_claim_batch_a.py tests/regression/phase_00/test_p00_us06_reviewed_claims_batch_a_regression.py tests/stories/phase_00/test_p00_us07_reviewed_claims_batch_b.py tests/contract/test_p00_us07_reviewed_claim_batch_b.py tests/regression/phase_00/test_p00_us07_reviewed_claims_batch_b_regression.py` | 45 passed; 1 pre-existing warning |
| Phase 0 regression | `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -p no:cacheprovider tests/regression/phase_00` | 32 passed; 1 pre-existing warning |
| Impacted Phase 0 + contract + API/serializer | `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -p no:cacheprovider tests/stories/phase_00 tests/regression/phase_00 tests/contract tests/test_api.py tests/test_serializer.py` | 270 passed; 1 pre-existing warning |
| API/schema/serializer | `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -p no:cacheprovider tests/test_api.py tests/test_serializer.py tests/contract` | 73 passed; 1 pre-existing warning |
| Full backend | `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -p no:cacheprovider` | 324 passed; 10 explicit opt-in skips; 1 pre-existing warning |
| Frontend typecheck | `/opt/homebrew/opt/node@24/bin/node node_modules/typescript/bin/tsc --noEmit --pretty false` from `frontend/` | Pass |
| Frontend lint | `/opt/homebrew/opt/node@24/bin/node node_modules/eslint/bin/eslint.js . --ignore-pattern dist --ignore-pattern .next --ignore-pattern public/pdf.worker.min.mjs` from `frontend/` | Pass |
| Frontend unit | `/opt/homebrew/opt/node@24/bin/node --experimental-strip-types --test tests/*.test.mts` from `frontend/` | 27 passed |
| Python compile | `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m compileall -q tests/benchmarks tests/stories/phase_00 tests/contract tests/regression/phase_00` | Pass |

The warning is the pre-existing Starlette `httpx` test-client deprecation. The
10 skips retain their explicit integration/model requirements. Frontend
commands emitted only the existing non-failing pyenv rehash warning.

## Resource observation

One fresh process loaded the registry, fully loaded and source-compared Batches
A, B, and C, and serialized Batch C in **26.920 ms** with **37.203 MiB**
(`39,010,304` bytes) maximum RSS. It executed no parser, OCR engine, model,
network call, or hosted service.

## Compatibility and rollback

Batch A and Batch B bytes and semantics remain pinned. Production imports
remain zero and OpenAPI, `ParseResult`, and `ErrorResponse` retain their
canonical hashes. No parser, serializer, dependency, configuration, feature
flag, triplet, frozen case review, registry, or prior evidence changed.

Rollback removes only the additive Batch C policies, evidence, tests, and
documentation. Batches A/B and P00-US05 contracts remain loadable and
unchanged.

## Independent review

Pass - no blocking or actionable findings. The reviewer independently reloaded
all three batches, reproduced Batch C's 63 claims, 75 locators, exact
status/evidence/type/mask totals and three Uber-only derivations, verified
health row 07 remains uncalibrated, and reconciled the complete 210-claim,
15-case, 271-locator corpus. It also rehashed all Batch C triplets and all
three evidence files, confirmed A/B stability, exercised the 25 focused tests,
and checked drift rejection, production/API isolation, rollback, custody, and
single-story concurrency.
