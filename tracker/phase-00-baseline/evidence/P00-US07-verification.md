# P00-US07 Verification

Status: Done  
Date: 2026-07-29  
Scope: reviewed claims Batch B only

## Identity and reconciliation

| Dimension | Result |
|---|---:|
| Cases | 5 |
| Expert-validation rows / claims | 76 / 76 |
| Registered locators | 121 |
| `clean-energy` | 14 |
| `clinical-study` | 21 |
| `component-datasheet` | 18 |
| `insurance-acord` | 13 |
| `ny-timetable` | 10 |
| Verified | 43 |
| Partially verified | 15 |
| Incorrect | 8 |
| Potentially inferred | 5 |
| Not independently verifiable | 5 |
| Literal-parity included | 36 |
| Semantic-parity included | 58 |
| Measured derivations | 0 |

Every bounded expert-validation table row maps to one claim. The reader handles
both four-column reviews and the timetable's five-column review by locating
the `Status` header, retains additional evidence text, and stops at the next
level-two heading. Grouped items, 50-row table assertions, and multi-page rows
remain one claim each.

## Evidence and type classifications

| Evidence class | Claims |
|---|---:|
| `visible_text` | 36 |
| `inferred` | 18 |
| `native_data` | 16 |
| `unknowable` | 5 |
| `embedded_data` | 1 |

| Primary claim type | Claims |
|---|---:|
| `text` | 21 |
| `table` | 12 |
| `page_identity` | 9 |
| `metadata` | 9 |
| `structure` | 5 |
| `geometry` | 5 |
| `image` | 4 |
| `diagram` | 3 |
| `chart` | 2 |
| `form` | 2 |
| `relationship` | 1 |
| `link` | 1 |
| `text_style` | 1 |
| `artifact_inventory` | 1 |

Incorrect, potentially inferred, and not-independently-verifiable rows enter
neither denominator. Partial rows are semantic-only. Inferred evidence never
enters literal parity. The clean-energy exact bar values remain inferred and
excluded because six panels use different units/scales and the expert review
provides no derivation or tolerance. Batch B therefore contains no measured
evidence and no fabricated derivation.

## Locator and provenance evidence

The 76 claims use 121 registered locators. Aggregate clinical, component,
timetable, header/footer, confidence, geometry, and metadata rows retain one
locator per applicable source page. Physical and printed pages match P00-US04,
including insurance's explicit `null` printed page and clinical's slash-form
labels.

Exact claim-wide bboxes remain `null` where the review does not establish
coordinate truth. Stable regions, page identity, coordinate convention, and
source/derived scope remain explicit.

| Frozen case review | SHA-256 |
|---|---|
| `clean-energy.md` | `1345fc03e3f55f415dd7682c827e24b6022d25b46ef0ee68e8437bc145f0ca5a` |
| `clinical-study.md` | `fa5c1e863b7cee50ca4eea4b6c2debd042c7d9bbe143663cad64a26a07f5806f` |
| `component-datasheet.md` | `6e41940bd8ffd61dbf7fce8ec4882f8935f6a94c481c844d7dc828812c4b53fe` |
| `insurance-acord.md` | `327e9ed62a2703075e00434d5b02bead11525692d43178198a9377ca0adeaddb` |
| `ny-timetable.md` | `68e1ce268850da1fa09180c0bd0262976ba983dcc5de039c21b1bbde91c7822b` |

The no-exceptions public/redistributable custody decision covers every triplet
and derived annotation. Regression tests rehash all 15 Batch B
PDF/Markdown/JSON artifacts and verify their registered sizes.

## Canonical identities and Batch A compatibility

| Artifact | Result |
|---|---|
| Batch B canonical semantic SHA-256 | `9afe6c098adcd32e3a8370af5ecb2b27ac4730f098e39128e787eef991990d0f` |
| Batch B newline-terminated file SHA-256 | `7e4728c1c5d76a6453d42c640de8a25c24989ed3a160cac2fe4640b22a55814e` |
| Batch B canonical characters | 93,896 |
| Batch B canonical UTF-8 bytes | 94,074 |
| Unchanged Batch A semantic SHA-256 | `f6f0ef58f4cb1379f808e8d5bb7253f260a8f643a83e98e75e4d2e1a3fff01ee` |
| Unchanged Batch A file SHA-256 | `f987d84ca1b0d08dfd304d7ea3164a78366643f4b42ef03bc4975d4d09548de4` |

Fresh Batch B construction, persisted reload, schema/registry validation, and
a second construction are identical. The 147 Batch A+B claim IDs are unique
and case sets are disjoint. Schema-valid evidence drift and frozen-review drift
both fail closed.

## Commands and results

| Gate | Exact command | Result |
|---|---|---|
| Dedicated + contract + regression | `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -p no:cacheprovider tests/stories/phase_00/test_p00_us07_reviewed_claims_batch_b.py tests/contract/test_p00_us07_reviewed_claim_batch_b.py tests/regression/phase_00/test_p00_us07_reviewed_claims_batch_b_regression.py` | 23 passed; 1 pre-existing warning |
| Batch A compatibility | `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -p no:cacheprovider tests/stories/phase_00/test_p00_us06_reviewed_claims_batch_a.py tests/contract/test_p00_us06_reviewed_claim_batch_a.py tests/regression/phase_00/test_p00_us06_reviewed_claims_batch_a_regression.py` | 22 passed; 1 pre-existing warning |
| Phase 0 regression | `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -p no:cacheprovider tests/regression/phase_00` | 27 passed; 1 pre-existing warning |
| Impacted Phase 0 + contract + API/serializer | `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -p no:cacheprovider tests/stories/phase_00 tests/regression/phase_00 tests/contract tests/test_api.py tests/test_serializer.py` | 245 passed; 1 pre-existing warning |
| API/schema/serializer | `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -p no:cacheprovider tests/test_api.py tests/test_serializer.py tests/contract` | 63 passed; 1 pre-existing warning |
| Full backend | `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -p no:cacheprovider` | 299 passed; 10 explicit opt-in skips; 1 pre-existing warning |
| Frontend typecheck | `/opt/homebrew/opt/node@24/bin/node node_modules/typescript/bin/tsc --noEmit --pretty false` from `frontend/` | Pass |
| Frontend lint | `/opt/homebrew/opt/node@24/bin/node node_modules/eslint/bin/eslint.js . --ignore-pattern dist --ignore-pattern .next --ignore-pattern public/pdf.worker.min.mjs` from `frontend/` | Pass |
| Frontend unit | `/opt/homebrew/opt/node@24/bin/node --experimental-strip-types --test tests/*.test.mts` from `frontend/` | 27 passed |
| Python compile | `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m compileall -q tests/benchmarks tests/stories/phase_00 tests/contract tests/regression/phase_00` | Pass |

The warning remains the pre-existing Starlette `httpx` test-client
deprecation. The 10 skips retain their explicit integration/model
requirements. Frontend commands emitted only the existing non-failing pyenv
rehash warning.

## Resource observation

One fresh process loaded the registry, fully loaded/compared both Batch A and
Batch B, and serialized Batch B in **21.561 ms** with **37.156 MiB**
(`38,961,152` bytes) maximum RSS. It executed no parser, OCR engine, model,
network call, or hosted service.

## Compatibility, rollback, and independent review

Batch A bytes and semantics remain pinned. Production imports remain zero and
OpenAPI, `ParseResult`, and `ErrorResponse` retain their canonical hashes. No
parser, serializer, dependency, configuration, feature flag, triplet, case
review, registry, or prior evidence changed.

Rollback removes only the additive Batch B policies, evidence, tests, and
documentation. Batch A and P00-US05 contracts remain loadable and unchanged.

Independent review passed with no blockers. It reproduced the 76/121 totals,
all case/status/evidence/type/mask counts, no measured or derived claims,
review/triplet hashes, both Batch B hashes, Batch A stability, source/evidence
drift rejection, production isolation, the 10/10 readiness gate, and 23
focused passes.
