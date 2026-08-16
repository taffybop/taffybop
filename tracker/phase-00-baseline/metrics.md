# Phase 00 Metrics

Status: Phase 0 complete; P00-US01–P00-US10 Done.

| Metric | Before | Target | After |
|---|---:|---:|---:|
| Existing backend tests | 76 pass / 10 skip | No unexplained regression | 156 pass / 10 explicitly owned opt-in skips after P00-US03 |
| Catastrophe parse duration | One retained M0 run at 8,502 ms; older 3,365-ms planning snapshot stale | Reproducible reference distribution, not a single sample | 5 cold runs: p50 8,050.770 ms; p95/max 11,955.223 ms; mean 8,871.063 ms |
| Catastrophe peak RSS | One retained M0 run at approximately 1,427.5 MiB | p50/p95 captured on the reference hardware | p50 1,426.97 MiB; p95/max 1,428.33 MiB; mean 1,407.22 MiB |
| Catastrophe output sizes | One raw JSON/Markdown snapshot | Raw, semantic, backend, and frontend projections retained | 79,005–79,006 raw JSON; 38,325 semantic JSON; 2,008 backend/frontend Markdown; 112,013–112,014 frontend-normalized JSON; 1,965 frontend text bytes |
| Damaged sentence exact match | Fail | Baseline recorded with exact failed spans | 0/5; exact reviewed source span absent and raw/rejected/region-wrong evidence cannot pass |
| Exhibit 7 caption recall | 0/1 | Baseline recorded | 0/5 separate ordered captions; exact table remains 5/5 |
| Exhibit 8 separation | Fail | Baseline recorded | 0/5; title remains merged into chart OCR |
| Spatial year labels in diagnostics | 12/12 | Baseline recorded | 12 individual anchors plus a fused duplicate stream in 5/5; atomic structural check fails |
| Spatial year labels in primary chart text | Structure lost | Baseline recorded | Structure lost in 5/5 |
| Unsupported chart values emitted by our parser | 0 | Remain 0 until grounded analyzer exists | 0 in 5/5; synonym-shaped fabricated table negatives reject |
| Stable catastrophe quality findings | Ad hoc assessment | Complete atomic baseline | 5 pass / 10 fail in every run; signature `8507b5d0…998` |
| API/schema compatibility | Unpinned | Canonical API/schema identities and supported serializer gates pass | OpenAPI `3c71271b…983a`; ParseResult `706a1f63…a91f`; ErrorResponse `3fde7027…a5a6`; Node 24 typecheck/lint and 27 unit tests pass |
| Metric/manifest schema validation | Absent | 100% valid records accepted and invalid controls rejected | P00-US01/P00-US02 controls remain green; P00-US03 adds 26 dedicated/regression passes covering aggregation, artifacts, drift, partial/error/timeout states, runtimes, skips, quality, frontend projections, and immutability |
| Catastrophe source-truth coverage | Ad hoc assessment prose | 100% listed elements/relationships; 88/88 measurements carry method/tolerance | 11 elements, 5 relationships, 30 cells, 23 printed chart labels, 88/88 measured points, and 4 negative controls in one hash-pinned bundle |
| Immutable corpus registration | 15 triplets / 30 pages audited; not yet an approved benchmark contract | 15/15 triplets and 30/30 pages hash-, page-map-, custody-, and review-valid | 15/15 cases, 30/30 pages, 45/45 PDF/Markdown/JSON artifacts, all public/redistributable with no exceptions |
| Portable corpus registry | Frozen manifest has 15 cases/30 pages/45 artifacts but absolute paths and no executable custody record | 15/15 cases, 30/30 pages, and 45/45 artifacts validate with portable paths and explicit custody | 15/15 cases, 30/30 pages, 45/45 artifacts and all 3 pinned support records validate; canonical registry SHA `f7c3bdf4…e4ca`; 0 absolute paths/collisions/hash drift; 20.198 ms validation, 36.188 MiB process peak RSS |
| Reviewed claim inventory | One catastrophe-specific truth record; source audit confirms 210 narrative rows | 210/210 typed, reviewer-versioned claims with locators and inclusion masks | Batches A+B+C register 210/210 source rows across 15 cases with 271 locators, 109 literal and 162 semantic masks; canonical batches are pinned and independently reviewed |
| Benchmark control inventory | 25 primary gap/story mappings and 109 case-gap rows existed only in Markdown planning evidence | 25/25 complete four-role control sets, 100/100 assignments, and 109/109 rows resolved | 25/25 owners, 100/100 roles, and 109/109 rows resolve 209 exact claim locators with zero unresolved references; semantic/file SHA `d3c73495…8fce` / `a383938d…6b5`; 50-load p50/p95 71.899/75.652 ms and 41.484 MiB peak RSS |
| Scored claims with reviewed evidence class and inclusion mask | Analysis exists in 15 case reports | 100%; 0 unsupported expert claims in literal-truth denominators | 210/210 narrative rows classified; 109 literal, 162 semantic; 0 incorrect, potentially inferred, measured, inferred-evidence, or unverifiable claims in literal parity |
| Source custody/redistribution decisions | Unresolved for supplied sources | 15/15 explicit; unresolved rights fail closed for committed CI use | 15/15 approved public/redistributable with no exceptions as of 2026-07-29 |
| Cross-format M5 semantic twins | 0 source cases outside PDF | Limitation registered as `GAP-COVERAGE-001`; no unsupported cross-format claim | — |
| Immutable baseline completion | 15/15 cases, 30/30 pages in heterogeneous M0 analysis, not the story runner | 15/15 and 30/30 with 0 silent skips or overwritten run IDs | Final strict run: 15/15 cases, 30/30 pages, 0 partial/error/timeout/skip; all worker/coordinator records hash-bound |
| Semantic report dimensions | Token/string diagnostics plus case review | Separate text, layout/order, table, chart, diagram, serialization, provenance, diagnostics, hallucination, cost, and performance reports | 12/12 canonical dimensions; 210 reviewed claims, 109 literal, 162 semantic, 48 unsupported exclusions, 0 falsely scored |
| Document warnings on reviewed parser defects | 0 across 15 successful M0 cases | Every reviewed defect is represented by a scored finding or actionable diagnostic; no silent category omission | Final run still has 0 parser warnings; the semantic report explicitly retains this diagnostics limitation and does not count silence as a quality pass |
| Corpus parse latency | p50 9.06 s; p95/max 46.76 s; 212.67 s aggregate coordinator time | Reproducible within a declared reference-environment tolerance | Coordinator p50/p95 9.818/46.707 s; 216.712 s aggregate; parse aggregate 199.426 s; comparable and within 25% |
| Corpus peak RSS | median 1,437 MiB; p95/max 2,590 MiB | Reproducible within a declared reference-environment tolerance | p50 1,434.11 MiB; max 2,450.61 MiB; comparable and within 25% |
| Corpus output size | 5,289,462 JSON bytes; 116,260 Markdown bytes | Recorded per case and aggregate with immutable output hashes | 5,289,461 raw JSON bytes; 116,260 Markdown; 15/15 duration-masked JSON and exact Markdown identities stable |

Peak RSS, p50/p95 latency, output size, cost, and API/schema compatibility are
now retained in the immutable 15-case run and remain mandatory future
comparison fields.
