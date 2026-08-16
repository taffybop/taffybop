# P00-US06 Verification

Status: Done  
Date: 2026-07-29  
Scope: reviewed claims Batch A only

## Identity and reconciliation

| Dimension | Result |
|---|---:|
| Cases | 5 |
| Expert-validation rows / claims | 71 / 71 |
| Registered locators | 75 |
| `catastrophe-recap` | 15 |
| `esg-metrics` | 13 |
| `finance-10k` | 11 |
| `manufacturing-report` | 21 |
| `purchase-agreement` | 11 |
| Verified | 44 |
| Partially verified | 17 |
| Not independently verifiable | 6 |
| Incorrect | 4 |
| Literal-parity included | 41 |
| Semantic-parity included | 61 |
| Measured derivations | 1 |

Every Markdown validation-table row maps to exactly one claim. Grouped item
ranges remain one row; they are not expanded into individual expert items.
The canonical loader reads only the exact `## Expert element validation`
section from the frozen case review, stops at the next level-two heading, and
does not treat the raw expert Markdown as source review.

## Evidence and type classifications

| Evidence class | Claims |
|---|---:|
| `visible_text` | 42 |
| `native_data` | 14 |
| `inferred` | 10 |
| `unknowable` | 4 |
| `measured` | 1 |

| Primary claim type | Claims |
|---|---:|
| `text` | 33 |
| `table` | 10 |
| `page_identity` | 5 |
| `metadata` | 5 |
| `chart` | 4 |
| `geometry` | 4 |
| `text_style` | 4 |
| `structure` | 2 |
| `image` | 1 |
| `relationship` | 1 |
| `link` | 1 |
| `artifact_inventory` | 1 |

Partially verified rows are semantic-only. Incorrect and
not-independently-verifiable rows enter neither denominator. Inferred,
unknowable, and measured evidence never enters literal parity. Three verified
structural/geometry rows use inferred evidence and therefore remain
semantic-only. The only measured row is the known incorrect catastrophe
numeric series; it records the existing PDF-vector calibration method,
`1 2025_USD_billions` tolerance, and is excluded from both scoring masks.

## Locator and provenance evidence

All 71 claims have one or more locators using the P00-US05 displayed-page
coordinate convention. Finance's two document-wide rows each use three
locators, producing 75 locators in total. Physical pages and printed labels
match the P00-US04 registry, including purchase agreement's explicit `null`
printed label and ESG's displayed `792 × 612` page after source rotation.

Exact bboxes remain `null` because these narrative rows do not establish
claim-wide coordinate truth. This avoids fabricating geometry; region scope,
stable region ID, physical page, printed page, and coordinate convention
remain explicit and validated.

| Frozen case review | SHA-256 |
|---|---|
| `catastrophe-recap.md` | `99b2110820d01d6a63e3677c0b49a3b17d3b5958ec186df0df552009ba976770` |
| `esg-metrics.md` | `174180aa1cb2b42dd2a7deb8692b2c12e69d3edbb3c3d91b3c9934edb07da563` |
| `finance-10k.md` | `3a2a661df038536eb95d72febe43189248df37b243194bfede441e1d38c61aff` |
| `manufacturing-report.md` | `4c38cafd256c090fc9d4041a4465d12f34c0855f8568d25c66fe7eb896a11dd1` |
| `purchase-agreement.md` | `715e14ee37fd5263939d01dd9090b30d2a3c1f6ea6fc703bbb7ca80e529213a4` |

The P00-US04 custody record remains approved public/redistributable with no
exceptions and explicitly covers derived annotations. Tests also rehash all 15
Batch A PDF/Markdown/JSON artifacts against that registry.

## Canonical identities

| Artifact | Result |
|---|---|
| Canonical semantic Batch A SHA-256 | `f6f0ef58f4cb1379f808e8d5bb7253f260a8f643a83e98e75e4d2e1a3fff01ee` |
| Newline-terminated evidence-file SHA-256 | `f987d84ca1b0d08dfd304d7ea3164a78366643f4b42ef03bc4975d4d09548de4` |
| Canonical characters | 76,924 |
| Canonical UTF-8 bytes | 77,089 |

Fresh construction, persisted reload, schema validation, registry validation,
and a second construction are identical. Evidence changes that remain
schema-valid still fail because reload compares them with the source-row build.
Review-file hash drift fails before claim construction.

## Commands and results

| Gate | Exact command | Result |
|---|---|---|
| Dedicated + contract + regression | `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -p no:cacheprovider tests/stories/phase_00/test_p00_us06_reviewed_claims_batch_a.py tests/contract/test_p00_us06_reviewed_claim_batch_a.py tests/regression/phase_00/test_p00_us06_reviewed_claims_batch_a_regression.py` | 22 passed; 1 pre-existing warning |
| Phase 0 regression | `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -p no:cacheprovider tests/regression/phase_00` | 22 passed; 1 pre-existing warning |
| Impacted Phase 0 + contract + API/serializer | `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -p no:cacheprovider tests/stories/phase_00 tests/regression/phase_00 tests/contract tests/test_api.py tests/test_serializer.py` | 222 passed; 1 pre-existing warning |
| API/schema/serializer | `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -p no:cacheprovider tests/test_api.py tests/test_serializer.py tests/contract` | 55 passed; 1 pre-existing warning |
| Full backend | `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -p no:cacheprovider` | 276 passed; 10 explicit opt-in skips; 1 pre-existing warning |
| Frontend typecheck | `/opt/homebrew/opt/node@24/bin/node node_modules/typescript/bin/tsc --noEmit --pretty false` from `frontend/` | Pass |
| Frontend lint | `/opt/homebrew/opt/node@24/bin/node node_modules/eslint/bin/eslint.js . --ignore-pattern dist --ignore-pattern .next --ignore-pattern public/pdf.worker.min.mjs` from `frontend/` | Pass |
| Frontend unit | `/opt/homebrew/opt/node@24/bin/node --experimental-strip-types --test tests/*.test.mts` from `frontend/` | 27 passed |
| Python compile | `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m compileall -q tests/benchmarks tests/stories/phase_00 tests/contract tests/regression/phase_00` | Pass |

The warning is the pre-existing Starlette `httpx` test-client deprecation. The
10 skips retain the same explicit real-model, full-pipeline, and cross-format
opt-in conditions. Frontend commands reported the existing non-failing pyenv
rehash warning and exited zero.

## Resource observation

One fresh process loaded the P00-US04 registry, parsed the five pinned review
sections, built and validated all 71 claims, compared the persisted evidence,
and serialized the canonical batch in **11.716 ms**. Process maximum RSS was
**36.156 MiB** (`37,912,576` bytes). This is a single contract-validation
observation; it ran no parser, OCR engine, model, network call, or hosted
service.

## Compatibility, rollback, and independent review

Production imports remain zero. OpenAPI, `ParseResult`, and `ErrorResponse`
retain their pinned canonical hashes. No parser, public serializer, dependency,
configuration, feature flag, source triplet, frozen case review, registry, or
prior evidence changed.

Rollback removes the additive Batch A inventory module, evidence, tests, and
documentation while retaining the P00-US05 contracts and all immutable source
and review artifacts. It has no production runtime effect.

Independent review passed with no blockers. The reviewer reproduced 71 claims,
75 locators, the exact case/status/mask totals, one measured derivation, both
canonical hashes, all five report hashes, public/redistributable custody,
fail-closed drift controls, production isolation, and 22 focused passes.
