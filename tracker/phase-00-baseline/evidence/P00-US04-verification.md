# P00-US04 Verification

Status: Done  
Date: 2026-07-29  
Scope: portable 15-case corpus registry only

## Identity and acceptance evidence

| Check | Result |
|---|---|
| Registry cases | 15/15 in canonical case-ID order |
| Physical pages | 30/30, contiguous and one-based per case |
| Artifacts | 45/45; one PDF, expert Markdown, and expert JSON per case |
| Current artifact bytes | 45/45 sizes and SHA-256 values match |
| Artifact bytes | 11,430,689 total |
| Support records | Frozen manifest, custody decision, and rights evidence all hash-valid |
| Portable paths | 0 absolute, traversal, backslash, root, role, or ownership errors |
| Custody | 15/15 public/redistributable; no exceptions; derived annotations covered; all six uses retained |
| Printed pages | 28 reviewed labels retained; `insurance-acord` and `purchase-agreement` explicitly `null` |
| Raw rotation | ESG retains displayed `792 × 612` points and raw PDF rotation `90`; all others `0` |
| P00-US01 projection | 15/15 cases project to the unchanged `FixtureManifest` |
| P00-US02 compatibility | Catastrophe fixture, triplet, and page identity match exactly |
| Production imports | 0 production imports or textual references to the test-only registry |

## Pinned hashes

| Artifact | SHA-256 |
|---|---|
| Portable registry file | `f8024ab7a47df2cedf2d10b996fc8eb140404cdafea0b0a0a9ae2bb059263ceb` |
| Canonical registry payload | `f7c3bdf460f64c51a7d7e29765ab1e621dc5f59224ddeba8c8a66959c901e4ca` |
| Frozen analysis manifest | `16736d189fa38ed10de9755abc181743d87d3199e8cb6275afa32ee39c96a052` |
| Corpus custody decision | `d6ae0e9dd15aeab2ef9d585ac3242d3941ef2988c3ebc6343e74166e30292d1f` |
| All-corpus rights evidence | `f4b2bff08889186572c477ecba19b8b2d6244d046288b79f0786be116f872c3e` |
| P00-US02 catastrophe truth | `d14d9f4bdbbffee24961d731b7bca75227eaec6bac77cce7508ded4252c9b4ac` |

The registry contains no timestamp, host name, absolute corpus root, reviewed
claim, scoring mask, control role, parser output, or production schema.

## Commands and results

| Gate | Exact command | Result |
|---|---|---|
| Dedicated + contract + regression | `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -p no:cacheprovider tests/stories/phase_00/test_p00_us04_corpus_registry.py tests/contract/test_p00_us04_corpus_registry_schema.py tests/regression/phase_00/test_p00_us04_corpus_registry_regression.py` | 50 passed; 1 pre-existing warning |
| Phase 0 regression | `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -p no:cacheprovider tests/regression/phase_00` | 12 passed; 1 pre-existing warning |
| Impacted Phase 0 + contract + API/serializer | `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -p no:cacheprovider tests/stories/phase_00 tests/regression/phase_00 tests/contract tests/test_api.py tests/test_serializer.py` | 152 passed; 1 pre-existing warning |
| API/schema/serializer | `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -p no:cacheprovider tests/test_api.py tests/test_serializer.py tests/contract` | 38 passed; 1 pre-existing warning |
| Full backend | `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -p no:cacheprovider` | 206 passed; 10 explicit opt-in skips; 1 pre-existing warning |
| Frontend typecheck | `/opt/homebrew/opt/node@24/bin/node node_modules/typescript/bin/tsc --noEmit --pretty false` from `frontend/` | Pass |
| Frontend lint | `/opt/homebrew/opt/node@24/bin/node node_modules/eslint/bin/eslint.js . --ignore-pattern dist --ignore-pattern .next --ignore-pattern public/pdf.worker.min.mjs` from `frontend/` | Pass |
| Frontend unit | `/opt/homebrew/opt/node@24/bin/node --experimental-strip-types --test tests/*.test.mts` from `frontend/` | 27 passed |
| Python compile | `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m py_compile tests/benchmarks/corpus_registry.py tests/stories/phase_00/test_p00_us04_corpus_registry.py tests/contract/test_p00_us04_corpus_registry_schema.py tests/regression/phase_00/test_p00_us04_corpus_registry_regression.py` | Pass |

The only pytest warning is the pre-existing Starlette `httpx` test-client
deprecation. The 10 full-suite skips retain the same explicit real-model,
full-pipeline, and cross-format opt-in conditions recorded by P00-US03.

## Quality and resource measurement

The metadata-only load plus byte verification completed in 20.198 ms and the
validation process reported 36.188 MiB peak RSS on the current arm64 reference
environment. It executed no parser, OCR engine, model, network call, or hosted
service.

## Compatibility and rollback

The existing P00-US03 regression reasserted the unchanged public identities:

- OpenAPI: `3c71271be81fc55e8f85229e1ffdf01ef6a7977c4638a87449617749a1a2983a`
- `ParseResult`: `706a1f63bf77eaa6cc3f114b9b5c976d07d764de04a8beffa45cd2b04aafa91f`
- `ErrorResponse`: `3fde7027b8452307282b52870914475672aed4b4326018867fdf467922d1a5a6`

Rollback is removal of the registry module/data/tests from active use. The
production tree has no dependency on them, so rollback has no parser/API/output
effect. Immutable sources, the frozen manifest, custody decisions, and prior
P00-US01–P00-US03 evidence remain retained.

## Review

Independent review: **Pass — no blockers.** The reviewer independently
reconciled all current bytes, PDFs, expert page arrays, review-page maps,
custody, P00-US02 compatibility, negative controls, schema/canonical hashes,
production isolation, rollback, tracker status, and selected local links.
Independent reruns reproduced 50 focused, 12 Phase 0 regression, 152 impacted,
38 API/schema, and 206 full-backend passes, plus the recorded frontend gates.
