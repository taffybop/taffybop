# LlamaParse-15 functional-fidelity comparison

Run: `functional-fidelity-20260813`  
Candidate artifacts: `service-final-20260813`  
Analyzer schema: `functional-fidelity-comparison-v1`  
Story mapping: `tracker/benchmarks/llamaparse-15/gap-to-story-matrix.md`
Reference selection: `tracker/benchmarks/llamaparse-15/runs/functional-fidelity-20260813/reference-selection.json`

This is a functionality/output-quality comparison. It does not make latency, CPU, memory, or exhaustive hardening claims.

Finding totals are conservative counts of reproducible discrepancy signals, not counts of unique root causes. A missing or regrouped item can create correlated Markdown, JSON, table, visual, and DOM signals. The source-grounded adjudication ledgers must be consulted before treating signals as separate production defects or forcing parity with model-generated, inferred, or source-contradicted baseline content.

## Release readiness

**NOT READY** — 277 functional regression(s), 9 manual-review signal(s), 0 evidence gap(s), 55 accepted/harmless difference(s), and 2 hash-validated resolved discrepancy/discrepancies.

A `pending` case lacks one or more service artifacts or rendered-page captures; it is not a fidelity pass. A `fixed` case requires a hash-bound resolution ledger and a clean rerun. A hash-bound prior issue may be resolved while unrelated current findings keep the PDF at `discrepancy_found`.

## Per-PDF status

| PDF | Status | Critical | Major | Minor | Functional | Review | Evidence gaps | Evidence |
|---|---|---:|---:|---:|---:|---:|---:|---|
| `catastrophe-recap.pdf` | **discrepancy_found** | 6 | 3 | 5 | 10 | 1 | 0 | [`evidence.json`](catastrophe-recap/evidence.json) |
| `clean-energy.pdf` | **discrepancy_found** | 6 | 3 | 4 | 9 | 1 | 0 | [`evidence.json`](clean-energy/evidence.json) |
| `clinical-study.pdf` | **discrepancy_found** | 8 | 25 | 10 | 34 | 1 | 0 | [`evidence.json`](clinical-study/evidence.json) |
| `component-datasheet.pdf` | **discrepancy_found** | 10 | 9 | 6 | 20 | 0 | 0 | [`evidence.json`](component-datasheet/evidence.json) |
| `egov-survey.pdf` | **discrepancy_found** | 6 | 3 | 4 | 10 | 1 | 0 | [`evidence.json`](egov-survey/evidence.json) |
| `esg-metrics.pdf` | **discrepancy_found** | 4 | 12 | 5 | 17 | 1 | 0 | [`evidence.json`](esg-metrics/evidence.json) |
| `finance-10k.pdf` | **discrepancy_found** | 9 | 12 | 7 | 24 | 0 | 0 | [`evidence.json`](finance-10k/evidence.json) |
| `health-report.pdf` | **discrepancy_found** | 7 | 5 | 3 | 12 | 1 | 0 | [`evidence.json`](health-report/evidence.json) |
| `insurance-acord.pdf` | **discrepancy_found** | 11 | 3 | 4 | 15 | 1 | 0 | [`evidence.json`](insurance-acord/evidence.json) |
| `manufacturing-report.pdf` | **discrepancy_found** | 16 | 20 | 9 | 37 | 1 | 0 | [`evidence.json`](manufacturing-report/evidence.json) |
| `ny-timetable.pdf` | **discrepancy_found** | 12 | 7 | 10 | 24 | 0 | 0 | [`evidence.json`](ny-timetable/evidence.json) |
| `postal-10k.pdf` | **discrepancy_found** | 5 | 17 | 5 | 24 | 0 | 0 | [`evidence.json`](postal-10k/evidence.json) |
| `purchase-agreement.pdf` | **discrepancy_found** | 0 | 3 | 5 | 7 | 0 | 0 | [`evidence.json`](purchase-agreement/evidence.json) |
| `settlement-agreement.pdf` | **discrepancy_found** | 0 | 5 | 5 | 9 | 0 | 0 | [`evidence.json`](settlement-agreement/evidence.json) |
| `uber-earnings.pdf` | **discrepancy_found** | 13 | 11 | 8 | 25 | 1 | 0 | [`evidence.json`](uber-earnings/evidence.json) |

## Findings

### catastrophe-recap

Status: **discrepancy_found**

| Physical page | Page status | JSON text recall | JSON text precision | Sequence ratio | Reference DOM | Service DOM | Findings |
|---:|---|---:|---:|---:|---|---|---:|
| 1 | discrepancy_found | 61.04% | 95.72% | 67.88% | yes | yes | 14 |

Resolved discrepancy evidence:

- Prior IDs: `FID-CATASTROPHE-RECAP-80d905db1393`
- Code changes: `["app/services/pipeline.py: rebind non-target visual canonical blocks to exact public layout relationships and exclusions", "app/models.py: require complete context-free public overlay validation"]`
- Validation: `["local: .venv/bin/pytest -q tests/regression/phase_04/test_p04_us01_public_projection_regression.py -> 2 passed", "agent-verified: P03/P04 custody suites -> 187 passed", "agent-verified: API/model/visual suites -> 139 passed", "agent-verified: opt-in exact two-case corpus drift -> 2 passed", "agent-verified: compileall passed", "fresh LlamaParse Agentic job pjb-7zcmu6esqvbzn6dxsc5lefxs2qa3", "fresh post-fix HTTP JSON and Markdown 200 responses", "fresh reference and service rendered-DOM capture"]`
- Validation scope: `Public API parse-blocking defect only; unrelated fidelity differences remain open.`
- Remaining evidence: `["See comparison/catastrophe-recap/evidence.json for current Markdown, JSON, visual, table, and rendered differences."]`
- Current raw artifacts are bound by SHA-256 in the case evidence.

- `FID-CATASTROPHE-RECAP-23d2441a9f50` — **critical / functional_regression** — markdown, page(s) 1: Raw Markdown has missing, added, replaced, duplicated, or reordered visible text. Owner: `GAP-TEXT-001` / `P02-US04`; test: `test_p02_us04_text_reconciliation.py`.
- `FID-CATASTROPHE-RECAP-327194d1001c` — **minor / functional_regression** — markdown, page(s) 1: User-visible Markdown emphasis or code syntax differs. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-CATASTROPHE-RECAP-a9c0df1f3cc2` — **major / functional_regression** — markdown, page(s) 1: Table count or document order differs from LlamaParse. Owner: `GAP-TABLE-001` / `P04-US04`; test: `test_p04_us04_table_candidate_gate.py`.
- `FID-CATASTROPHE-RECAP-1a2ce6b8ec9a` — **minor / acceptable_difference** — json, page(s) 1: Cross-envelope component decomposition or taxonomy differs on the page. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-CATASTROPHE-RECAP-bd00bb4712f8` — **minor / acceptable_difference** — json, page(s) 1: Service JSON adds nested component relationships beyond LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-CATASTROPHE-RECAP-92eefd1ddf37` — **minor / harmless_formatting** — json, page(s) 1: Table 1 serialized field bytes differ while logical cells and spans match. Owner: `GAP-TABLE-003` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-CATASTROPHE-RECAP-7127527086b7` — **critical / functional_regression** — json, page(s) 1: Page-associated JSON component content differs from LlamaParse. Owner: `GAP-TEXT-001` / `P02-US04`; test: `test_p02_us04_text_reconciliation.py`.
- `FID-CATASTROPHE-RECAP-3d0d90699668` — **minor / review_required** — json, page(s) 1: Visual-origin text proxy differs and requires region-level review. Owner: `GAP-OCR-001` / `P02-US06`; test: `test_p02_us06_spatial_tokens.py`.
- `FID-CATASTROPHE-RECAP-0a564a0efa3a` — **critical / functional_regression** — json, page(s) 1: Image 1 labels, values, description, or caption differ. Owner: `GAP-VISUAL-001` / `P06-US05`; test: `test_p06_us05_grounding.py`.
- `FID-CATASTROPHE-RECAP-2f395dd7cc5f` — **critical / functional_regression** — json, page(s) 1: Chart 1 labels, values, description, or caption differ. Owner: `GAP-CHART-002` / `P05-US04`; test: `test_p05_us04_vector_values.py`.
- `FID-CATASTROPHE-RECAP-ea8a1ea050ca` — **critical / functional_regression** — rendered_dom, page(s) 1: Rendered Markdown visible semantic text differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-CATASTROPHE-RECAP-1bcea83539d1` — **major / functional_regression** — rendered_dom, page(s) 1: Rendered semantic tag hierarchy or order differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-CATASTROPHE-RECAP-5e8e8cd6c858` — **major / functional_regression** — rendered_dom, page(s) 1: Rendered item grouping/type sequence differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-CATASTROPHE-RECAP-f1bf581ba0d2` — **critical / functional_regression** — rendered_dom, page(s) 1: Table count or document order differs from LlamaParse. Owner: `GAP-TABLE-001` / `P04-US04`; test: `test_p04_us04_table_candidate_gate.py`.

### clean-energy

Status: **discrepancy_found**

| Physical page | Page status | JSON text recall | JSON text precision | Sequence ratio | Reference DOM | Service DOM | Findings |
|---:|---|---:|---:|---:|---|---|---:|
| 1 | discrepancy_found | 85.37% | 58.33% | 37.62% | yes | yes | 12 |

- `FID-CLEAN-ENERGY-b53fae781052` — **critical / functional_regression** — markdown, page(s) 1: Raw Markdown has missing, added, replaced, duplicated, or reordered visible text. Owner: `GAP-TEXT-001` / `P02-US04`; test: `test_p02_us04_text_reconciliation.py`.
- `FID-CLEAN-ENERGY-6d5736c77002` — **critical / functional_regression** — markdown, page(s) document: Table count or document order differs from LlamaParse. Owner: `GAP-TABLE-001` / `P04-US04`; test: `test_p04_us04_table_candidate_gate.py`.
- `FID-CLEAN-ENERGY-ffd46fa58a10` — **minor / acceptable_difference** — json, page(s) 1: Cross-envelope component decomposition or taxonomy differs on the page. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-CLEAN-ENERGY-81d7221728d3` — **minor / acceptable_difference** — json, page(s) 1: Cross-envelope nested component decomposition differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-CLEAN-ENERGY-7d7d24cb2f8a` — **critical / functional_regression** — json, page(s) 1: Page-associated JSON component content differs from LlamaParse. Owner: `GAP-TEXT-001` / `P02-US04`; test: `test_p02_us04_text_reconciliation.py`.
- `FID-CLEAN-ENERGY-bb971422eb7a` — **minor / review_required** — json, page(s) 1: Visual-origin text proxy differs and requires region-level review. Owner: `GAP-OCR-001` / `P02-US06`; test: `test_p02_us06_spatial_tokens.py`.
- `FID-CLEAN-ENERGY-5ffdf7968983` — **minor / acceptable_difference** — json, page(s) 1: Service emits additional image regions while retaining all LlamaParse image pages. Owner: `GAP-COVERAGE-001` / `P07-US02`; test: `test_p07_us02_image_parity.py plus M5 twins`.
- `FID-CLEAN-ENERGY-0525f89e6046` — **critical / functional_regression** — json, page(s) 1: Chart 1 labels, values, description, or caption differ. Owner: `GAP-CHART-002` / `P05-US04`; test: `test_p05_us04_vector_values.py`.
- `FID-CLEAN-ENERGY-04877de9eb00` — **major / functional_regression** — json, page(s) 1: Chart 1 page-relative placement differs materially. Owner: `GAP-VISUAL-001` / `P06-US05`; test: `test_p06_us05_grounding.py`.
- `FID-CLEAN-ENERGY-09fb178f85e2` — **critical / functional_regression** — rendered_dom, page(s) 1: Rendered Markdown visible semantic text differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-CLEAN-ENERGY-f6271f986d1b` — **major / functional_regression** — rendered_dom, page(s) 1: Rendered semantic tag hierarchy or order differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-CLEAN-ENERGY-8c6a7c7acec3` — **major / functional_regression** — rendered_dom, page(s) 1: Rendered item grouping/type sequence differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-CLEAN-ENERGY-8a43ea4d1240` — **critical / functional_regression** — rendered_dom, page(s) 1: Table count or document order differs from LlamaParse. Owner: `GAP-TABLE-001` / `P04-US04`; test: `test_p04_us04_table_candidate_gate.py`.

### clinical-study

Status: **discrepancy_found**

| Physical page | Page status | JSON text recall | JSON text precision | Sequence ratio | Reference DOM | Service DOM | Findings |
|---:|---|---:|---:|---:|---|---|---:|
| 1 | discrepancy_found | 94.94% | 92.30% | 93.43% | yes | yes | 15 |
| 2 | discrepancy_found | 95.03% | 95.03% | 93.17% | yes | yes | 14 |
| 3 | discrepancy_found | 0.00% | 0.00% | 0.00% | yes | yes | 13 |
| 4 | discrepancy_found | 89.25% | 95.75% | 91.51% | yes | yes | 14 |

- `FID-CLINICAL-STUDY-7ff711b5ea91` — **major / functional_regression** — markdown, page(s) 1, 2, 3, 4: Raw Markdown has missing, added, replaced, duplicated, or reordered visible text. Owner: `GAP-TEXT-001` / `P02-US04`; test: `test_p02_us04_text_reconciliation.py`.
- `FID-CLINICAL-STUDY-a23b7affb315` — **major / functional_regression** — markdown, page(s) 1: Heading text, level, or order differs from LlamaParse. Owner: `GAP-LIST-001` / `P03-US07`; test: `test_p03_us07_outline_structure.py`.
- `FID-CLINICAL-STUDY-79f515286213` — **major / functional_regression** — markdown, page(s) 1: List identity, nesting, text, or order differs. Owner: `GAP-LIST-001` / `P03-US07`; test: `test_p03_us07_outline_structure.py`.
- `FID-CLINICAL-STUDY-742092da3cc3` — **major / functional_regression** — markdown, page(s) 1, 2, 3, 4: Markdown links/images differ in text, target, or order. Owner: `GAP-LINK-001` / `P01-US01`; test: `test_p01_us01_ir_contract.py`.
- `FID-CLINICAL-STUDY-e5ec64f34148` — **minor / functional_regression** — markdown, page(s) 1, 2, 3, 4: User-visible Markdown emphasis or code syntax differs. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-CLINICAL-STUDY-13190a09c84e` — **major / functional_regression** — markdown, page(s) 2: Table 1 differs in shape, spans, row order, or cell content. Owner: `GAP-TABLE-003` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-CLINICAL-STUDY-31e481be46c0` — **critical / functional_regression** — markdown, page(s) 4: Table 2 differs in shape, spans, row order, or cell content. Owner: `GAP-TABLE-003` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-CLINICAL-STUDY-ef172dbafa99` — **minor / acceptable_difference** — json, page(s) 1: Cross-envelope component decomposition or taxonomy differs on the page. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-CLINICAL-STUDY-113a08bdd03a` — **minor / acceptable_difference** — json, page(s) 1: Cross-envelope nested component decomposition differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-CLINICAL-STUDY-91672c4e2c2a` — **minor / acceptable_difference** — json, page(s) 2: Cross-envelope component decomposition or taxonomy differs on the page. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-CLINICAL-STUDY-73565db5ec5e` — **minor / acceptable_difference** — json, page(s) 2: Cross-envelope nested component decomposition differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-CLINICAL-STUDY-40f3fd1f6ba7` — **minor / acceptable_difference** — json, page(s) 3: Cross-envelope component decomposition or taxonomy differs on the page. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-CLINICAL-STUDY-de7ccf73d4c6` — **minor / acceptable_difference** — json, page(s) 3: Cross-envelope nested component decomposition differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-CLINICAL-STUDY-7f8c81566609` — **minor / acceptable_difference** — json, page(s) 4: Cross-envelope component decomposition or taxonomy differs on the page. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-CLINICAL-STUDY-090e612f1adb` — **minor / acceptable_difference** — json, page(s) 4: Cross-envelope nested component decomposition differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-CLINICAL-STUDY-c5eaeee30f05` — **major / functional_regression** — json, page(s) 2: Table 1 differs in shape, spans, row order, or cell content. Owner: `GAP-TABLE-002` / `P04-US01`; test: `test_p04_us01_span_fidelity.py`.
- `FID-CLINICAL-STUDY-b96d2d42b26d` — **critical / functional_regression** — json, page(s) 4: Table 2 differs in shape, spans, row order, or cell content. Owner: `GAP-TABLE-002` / `P04-US01`; test: `test_p04_us01_span_fidelity.py`.
- `FID-CLINICAL-STUDY-605279ab6015` — **major / functional_regression** — json, page(s) 1: Page-associated JSON component content differs from LlamaParse. Owner: `GAP-TEXT-001` / `P02-US04`; test: `test_p02_us04_text_reconciliation.py`.
- `FID-CLINICAL-STUDY-790d26732eda` — **major / functional_regression** — json, page(s) 2: Page-associated JSON component content differs from LlamaParse. Owner: `GAP-TEXT-001` / `P02-US04`; test: `test_p02_us04_text_reconciliation.py`.
- `FID-CLINICAL-STUDY-c72ac3ab2004` — **critical / functional_regression** — json, page(s) 3: Page-associated JSON component content differs from LlamaParse. Owner: `GAP-TEXT-001` / `P02-US04`; test: `test_p02_us04_text_reconciliation.py`.
- `FID-CLINICAL-STUDY-abe1355a00d9` — **critical / functional_regression** — json, page(s) 4: Page-associated JSON component content differs from LlamaParse. Owner: `GAP-TEXT-001` / `P02-US04`; test: `test_p02_us04_text_reconciliation.py`.
- `FID-CLINICAL-STUDY-52d3be61bf85` — **minor / review_required** — json, page(s) 1, 2, 3, 4: Visual-origin text proxy differs and requires region-level review. Owner: `GAP-OCR-001` / `P02-US06`; test: `test_p02_us06_spatial_tokens.py`.
- `FID-CLINICAL-STUDY-8b78bb805ece` — **major / functional_regression** — json, page(s) 1, 3: Image detection count or page placement differs from LlamaParse. Owner: `GAP-COVERAGE-001` / `P07-US02`; test: `test_p07_us02_image_parity.py plus M5 twins`.
- `FID-CLINICAL-STUDY-98383eb40fc3` — **critical / functional_regression** — json, page(s) 1: Image 1 labels, values, description, or caption differ. Owner: `GAP-VISUAL-001` / `P06-US05`; test: `test_p06_us05_grounding.py`.
- `FID-CLINICAL-STUDY-1b2e7a33b2c3` — **major / functional_regression** — json, page(s) 3: Diagram detection count or page placement differs from LlamaParse. Owner: `GAP-DIAGRAM-001` / `P05-US10`; test: `test_p05_us10_diagram_topology.py`.
- `FID-CLINICAL-STUDY-1fd4acc2b488` — **major / functional_regression** — rendered_dom, page(s) 1: Rendered Markdown visible semantic text differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-CLINICAL-STUDY-59f5050beee6` — **major / functional_regression** — rendered_dom, page(s) 1: Rendered semantic tag hierarchy or order differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-CLINICAL-STUDY-ee7820743df7` — **major / functional_regression** — rendered_dom, page(s) 1: Rendered item grouping/type sequence differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-CLINICAL-STUDY-84b7ba216fb4` — **major / functional_regression** — rendered_dom, page(s) 1: Rendered links differ in text, target, or order. Owner: `GAP-LINK-001` / `P01-US01`; test: `test_p01_us01_ir_contract.py`.
- `FID-CLINICAL-STUDY-3777d40e54b1` — **major / functional_regression** — rendered_dom, page(s) 2: Rendered Markdown visible semantic text differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-CLINICAL-STUDY-9b0aef3e83ea` — **major / functional_regression** — rendered_dom, page(s) 2: Rendered semantic tag hierarchy or order differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-CLINICAL-STUDY-34d673c9cd92` — **major / functional_regression** — rendered_dom, page(s) 2: Rendered item grouping/type sequence differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-CLINICAL-STUDY-cf4b3b4ad5da` — **major / functional_regression** — rendered_dom, page(s) 2: Table 1 differs in shape, spans, row order, or cell content. Owner: `GAP-TABLE-003` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-CLINICAL-STUDY-ba71855ba7cc` — **major / functional_regression** — rendered_dom, page(s) 2: Rendered links differ in text, target, or order. Owner: `GAP-LINK-001` / `P01-US01`; test: `test_p01_us01_ir_contract.py`.
- `FID-CLINICAL-STUDY-f137b2957551` — **critical / functional_regression** — rendered_dom, page(s) 3: Rendered Markdown visible semantic text differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-CLINICAL-STUDY-f3f9cc680411` — **major / functional_regression** — rendered_dom, page(s) 3: Rendered semantic tag hierarchy or order differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-CLINICAL-STUDY-91b550ccea1d` — **major / functional_regression** — rendered_dom, page(s) 3: Rendered item grouping/type sequence differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-CLINICAL-STUDY-6d6dd1bf2bc4` — **major / functional_regression** — rendered_dom, page(s) 3: Rendered links differ in text, target, or order. Owner: `GAP-LINK-001` / `P01-US01`; test: `test_p01_us01_ir_contract.py`.
- `FID-CLINICAL-STUDY-163286ff7c93` — **critical / functional_regression** — rendered_dom, page(s) 4: Rendered Markdown visible semantic text differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-CLINICAL-STUDY-51a57711aeb6` — **major / functional_regression** — rendered_dom, page(s) 4: Rendered semantic tag hierarchy or order differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-CLINICAL-STUDY-75d8d72cb5cc` — **major / functional_regression** — rendered_dom, page(s) 4: Rendered item grouping/type sequence differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-CLINICAL-STUDY-42ea87fc96e7` — **critical / functional_regression** — rendered_dom, page(s) 4: Table 1 differs in shape, spans, row order, or cell content. Owner: `GAP-TABLE-003` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-CLINICAL-STUDY-a0f5a0d4bad3` — **major / functional_regression** — rendered_dom, page(s) 4: Rendered links differ in text, target, or order. Owner: `GAP-LINK-001` / `P01-US01`; test: `test_p01_us01_ir_contract.py`.

### component-datasheet

Status: **discrepancy_found**

| Physical page | Page status | JSON text recall | JSON text precision | Sequence ratio | Reference DOM | Service DOM | Findings |
|---:|---|---:|---:|---:|---|---|---:|
| 1 | discrepancy_found | 95.20% | 70.55% | 79.93% | yes | yes | 11 |
| 2 | discrepancy_found | 94.98% | 65.04% | 76.19% | yes | yes | 11 |
| 3 | discrepancy_found | 100.00% | 88.37% | 93.83% | yes | yes | 11 |

- `FID-COMPONENT-DATASHEET-78708d8eb72a` — **critical / functional_regression** — markdown, page(s) 1, 2, 3: Raw Markdown has missing, added, replaced, duplicated, or reordered visible text. Owner: `GAP-TEXT-001` / `P02-US04`; test: `test_p02_us04_text_reconciliation.py`.
- `FID-COMPONENT-DATASHEET-6c53c51e0141` — **major / functional_regression** — markdown, page(s) 1, 2, 3: Heading text, level, or order differs from LlamaParse. Owner: `GAP-LIST-001` / `P03-US07`; test: `test_p03_us07_outline_structure.py`.
- `FID-COMPONENT-DATASHEET-84ceb18e51e9` — **major / functional_regression** — markdown, page(s) 1, 2: List identity, nesting, text, or order differs. Owner: `GAP-LIST-001` / `P03-US07`; test: `test_p03_us07_outline_structure.py`.
- `FID-COMPONENT-DATASHEET-5392dc81f136` — **minor / functional_regression** — markdown, page(s) 1, 2, 3: User-visible Markdown emphasis or code syntax differs. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-COMPONENT-DATASHEET-baf37d4b29d9` — **critical / functional_regression** — markdown, page(s) 3: Table count or document order differs from LlamaParse. Owner: `GAP-TABLE-001` / `P04-US04`; test: `test_p04_us04_table_candidate_gate.py`.
- `FID-COMPONENT-DATASHEET-d9fb73d77e56` — **minor / acceptable_difference** — json, page(s) 1: Cross-envelope component decomposition or taxonomy differs on the page. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-COMPONENT-DATASHEET-ea00535af12f` — **minor / acceptable_difference** — json, page(s) 1: Cross-envelope nested component decomposition differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-COMPONENT-DATASHEET-0ec3e57feb42` — **minor / acceptable_difference** — json, page(s) 2: Cross-envelope component decomposition or taxonomy differs on the page. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-COMPONENT-DATASHEET-267852c11299` — **minor / acceptable_difference** — json, page(s) 2: Cross-envelope nested component decomposition differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-COMPONENT-DATASHEET-524221a7ce16` — **minor / acceptable_difference** — json, page(s) 3: Cross-envelope component decomposition or taxonomy differs on the page. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-COMPONENT-DATASHEET-827cee8d7436` — **critical / functional_regression** — json, page(s) 3: Table 1 differs in shape, spans, row order, or cell content. Owner: `GAP-TABLE-002` / `P04-US01`; test: `test_p04_us01_span_fidelity.py`.
- `FID-COMPONENT-DATASHEET-4ea057066a65` — **critical / functional_regression** — json, page(s) 1: Page-associated JSON component content differs from LlamaParse. Owner: `GAP-TEXT-001` / `P02-US04`; test: `test_p02_us04_text_reconciliation.py`.
- `FID-COMPONENT-DATASHEET-94aa27605fa9` — **critical / functional_regression** — json, page(s) 2: Page-associated JSON component content differs from LlamaParse. Owner: `GAP-TEXT-001` / `P02-US04`; test: `test_p02_us04_text_reconciliation.py`.
- `FID-COMPONENT-DATASHEET-ce528e20e330` — **critical / functional_regression** — json, page(s) 3: Page-associated JSON component content differs from LlamaParse. Owner: `GAP-TEXT-001` / `P02-US04`; test: `test_p02_us04_text_reconciliation.py`.
- `FID-COMPONENT-DATASHEET-b6f03e5fe68c` — **major / functional_regression** — json, page(s) 1, 2: Chart detection count or page placement differs from LlamaParse. Owner: `GAP-CHART-001` / `P05-US03`; test: `test_p05_us03_axes_legends.py`.
- `FID-COMPONENT-DATASHEET-93cd576de9b8` — **critical / functional_regression** — rendered_dom, page(s) 1: Rendered Markdown visible semantic text differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-COMPONENT-DATASHEET-864d341291f8` — **major / functional_regression** — rendered_dom, page(s) 1: Rendered semantic tag hierarchy or order differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-COMPONENT-DATASHEET-61406060a065` — **major / functional_regression** — rendered_dom, page(s) 1: Rendered item grouping/type sequence differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-COMPONENT-DATASHEET-47efbb0373a4` — **critical / functional_regression** — rendered_dom, page(s) 2: Rendered Markdown visible semantic text differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-COMPONENT-DATASHEET-6f72e2a049ec` — **major / functional_regression** — rendered_dom, page(s) 2: Rendered semantic tag hierarchy or order differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-COMPONENT-DATASHEET-c2b40db8f530` — **major / functional_regression** — rendered_dom, page(s) 2: Rendered item grouping/type sequence differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-COMPONENT-DATASHEET-a81d678f5d40` — **critical / functional_regression** — rendered_dom, page(s) 3: Rendered Markdown visible semantic text differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-COMPONENT-DATASHEET-6129e0953fc0` — **major / functional_regression** — rendered_dom, page(s) 3: Rendered semantic tag hierarchy or order differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-COMPONENT-DATASHEET-01425d83c1c9` — **major / functional_regression** — rendered_dom, page(s) 3: Rendered item grouping/type sequence differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-COMPONENT-DATASHEET-d3402849df11` — **critical / functional_regression** — rendered_dom, page(s) 3: Table count or document order differs from LlamaParse. Owner: `GAP-TABLE-001` / `P04-US04`; test: `test_p04_us04_table_candidate_gate.py`.

### egov-survey

Status: **discrepancy_found**

| Physical page | Page status | JSON text recall | JSON text precision | Sequence ratio | Reference DOM | Service DOM | Findings |
|---:|---|---:|---:|---:|---|---|---:|
| 1 | discrepancy_found | 93.02% | 93.02% | 85.83% | yes | yes | 12 |

- `FID-EGOV-SURVEY-e32df2f651e5` — **critical / functional_regression** — markdown, page(s) 1: Raw Markdown has missing, added, replaced, duplicated, or reordered visible text. Owner: `GAP-TEXT-001` / `P02-US04`; test: `test_p02_us04_text_reconciliation.py`.
- `FID-EGOV-SURVEY-c1208dd1ef86` — **minor / functional_regression** — markdown, page(s) 1: User-visible Markdown emphasis or code syntax differs. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-EGOV-SURVEY-e2a281c14b5b` — **critical / functional_regression** — markdown, page(s) document: Table count or document order differs from LlamaParse. Owner: `GAP-TABLE-001` / `P04-US04`; test: `test_p04_us04_table_candidate_gate.py`.
- `FID-EGOV-SURVEY-de22cde4f49b` — **minor / acceptable_difference** — json, page(s) 1: Cross-envelope component decomposition or taxonomy differs on the page. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-EGOV-SURVEY-2adf18b48e4e` — **minor / acceptable_difference** — json, page(s) 1: Service JSON adds nested component relationships beyond LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-EGOV-SURVEY-b51ebd6e50f5` — **critical / functional_regression** — json, page(s) 1: Page-associated JSON component content differs from LlamaParse. Owner: `GAP-TEXT-001` / `P02-US04`; test: `test_p02_us04_text_reconciliation.py`.
- `FID-EGOV-SURVEY-d947042a408e` — **minor / review_required** — json, page(s) 1: Visual-origin text proxy differs and requires region-level review. Owner: `GAP-OCR-001` / `P02-US06`; test: `test_p02_us06_spatial_tokens.py`.
- `FID-EGOV-SURVEY-ad1f91b889ce` — **critical / functional_regression** — json, page(s) 1: Chart 1 labels, values, description, or caption differ. Owner: `GAP-CHART-002` / `P05-US04`; test: `test_p05_us04_vector_values.py`.
- `FID-EGOV-SURVEY-5c64eeecbbd0` — **major / functional_regression** — json, page(s) 1: Chart 1 page-relative placement differs materially. Owner: `GAP-VISUAL-001` / `P06-US05`; test: `test_p06_us05_grounding.py`.
- `FID-EGOV-SURVEY-29310ad3e9c8` — **critical / functional_regression** — rendered_dom, page(s) 1: Rendered Markdown visible semantic text differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-EGOV-SURVEY-c52fcd7dc5ad` — **major / functional_regression** — rendered_dom, page(s) 1: Rendered semantic tag hierarchy or order differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-EGOV-SURVEY-e1e1c3962d37` — **major / functional_regression** — rendered_dom, page(s) 1: Rendered item grouping/type sequence differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-EGOV-SURVEY-4b63c69be7e7` — **critical / functional_regression** — rendered_dom, page(s) 1: Table count or document order differs from LlamaParse. Owner: `GAP-TABLE-001` / `P04-US04`; test: `test_p04_us04_table_candidate_gate.py`.

### esg-metrics

Status: **discrepancy_found**

| Physical page | Page status | JSON text recall | JSON text precision | Sequence ratio | Reference DOM | Service DOM | Findings |
|---:|---|---:|---:|---:|---|---|---:|
| 1 | discrepancy_found | 86.46% | 95.90% | 84.79% | yes | yes | 21 |

- `FID-ESG-METRICS-0ce54fb8433b` — **critical / functional_regression** — markdown, page(s) 1: Raw Markdown has missing, added, replaced, duplicated, or reordered visible text. Owner: `GAP-TEXT-001` / `P02-US04`; test: `test_p02_us04_text_reconciliation.py`.
- `FID-ESG-METRICS-3b200448c400` — **major / functional_regression** — markdown, page(s) 1: Heading text, level, or order differs from LlamaParse. Owner: `GAP-LIST-001` / `P03-US07`; test: `test_p03_us07_outline_structure.py`.
- `FID-ESG-METRICS-6d4f6004bafc` — **major / functional_regression** — markdown, page(s) 1: Markdown links/images differ in text, target, or order. Owner: `GAP-LINK-001` / `P01-US01`; test: `test_p01_us01_ir_contract.py`.
- `FID-ESG-METRICS-73b6b0dfdc92` — **minor / functional_regression** — markdown, page(s) 1: User-visible Markdown emphasis or code syntax differs. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-ESG-METRICS-50724b72bad7` — **major / functional_regression** — markdown, page(s) 1: Table count or document order differs from LlamaParse. Owner: `GAP-TABLE-001` / `P04-US04`; test: `test_p04_us04_table_candidate_gate.py`.
- `FID-ESG-METRICS-8ef7ab9b009d` — **major / functional_regression** — markdown, page(s) 1: Table 1 differs in shape, spans, row order, or cell content. Owner: `GAP-TABLE-003` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-ESG-METRICS-f777c3e13dc1` — **minor / acceptable_difference** — json, page(s) 1: Cross-envelope component decomposition or taxonomy differs on the page. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-ESG-METRICS-abd56e4d558c` — **minor / acceptable_difference** — json, page(s) 1: Cross-envelope nested component decomposition differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-ESG-METRICS-565e34be412b` — **major / functional_regression** — json, page(s) 1: Table 1 differs in shape, spans, row order, or cell content. Owner: `GAP-TABLE-002` / `P04-US01`; test: `test_p04_us01_span_fidelity.py`.
- `FID-ESG-METRICS-3c29ade3a594` — **critical / functional_regression** — json, page(s) 1: Page-associated JSON component content differs from LlamaParse. Owner: `GAP-TEXT-001` / `P02-US04`; test: `test_p02_us04_text_reconciliation.py`.
- `FID-ESG-METRICS-849a723b603a` — **minor / review_required** — json, page(s) 1: Visual-origin text proxy differs and requires region-level review. Owner: `GAP-OCR-001` / `P02-US06`; test: `test_p02_us06_spatial_tokens.py`.
- `FID-ESG-METRICS-a12a1cdd7fb9` — **minor / acceptable_difference** — json, page(s) 1: Service emits additional image regions while retaining all LlamaParse image pages. Owner: `GAP-COVERAGE-001` / `P07-US02`; test: `test_p07_us02_image_parity.py plus M5 twins`.
- `FID-ESG-METRICS-83ed2ad018bb` — **major / functional_regression** — json, page(s) 1: Chart detection count or page placement differs from LlamaParse. Owner: `GAP-CHART-001` / `P05-US03`; test: `test_p05_us03_axes_legends.py`.
- `FID-ESG-METRICS-4e1614e44d08` — **critical / functional_regression** — json, page(s) 1: Chart 1 labels, values, description, or caption differ. Owner: `GAP-CHART-002` / `P05-US04`; test: `test_p05_us04_vector_values.py`.
- `FID-ESG-METRICS-3f75ac67cd66` — **major / functional_regression** — json, page(s) 1: Chart 1 page-relative placement differs materially. Owner: `GAP-VISUAL-001` / `P06-US05`; test: `test_p06_us05_grounding.py`.
- `FID-ESG-METRICS-0bfe5ec1c2a7` — **critical / functional_regression** — rendered_dom, page(s) 1: Rendered Markdown visible semantic text differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-ESG-METRICS-fc42b2021db1` — **major / functional_regression** — rendered_dom, page(s) 1: Rendered semantic tag hierarchy or order differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-ESG-METRICS-dab1913f99c4` — **major / functional_regression** — rendered_dom, page(s) 1: Rendered item grouping/type sequence differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-ESG-METRICS-ab7298406cc8` — **major / functional_regression** — rendered_dom, page(s) 1: Table count or document order differs from LlamaParse. Owner: `GAP-TABLE-001` / `P04-US04`; test: `test_p04_us04_table_candidate_gate.py`.
- `FID-ESG-METRICS-706f47b51d62` — **major / functional_regression** — rendered_dom, page(s) 1: Table 1 differs in shape, spans, row order, or cell content. Owner: `GAP-TABLE-003` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-ESG-METRICS-054fd7edf0c7` — **major / functional_regression** — rendered_dom, page(s) 1: Rendered links differ in text, target, or order. Owner: `GAP-LINK-001` / `P01-US01`; test: `test_p01_us01_ir_contract.py`.

### finance-10k

Status: **discrepancy_found**

| Physical page | Page status | JSON text recall | JSON text precision | Sequence ratio | Reference DOM | Service DOM | Findings |
|---:|---|---:|---:|---:|---|---|---:|
| 1 | discrepancy_found | 100.00% | 96.89% | 97.52% | yes | yes | 12 |
| 2 | discrepancy_found | 100.00% | 97.42% | 98.32% | yes | yes | 10 |
| 3 | discrepancy_found | 100.00% | 98.19% | 98.56% | yes | yes | 10 |

- `FID-FINANCE-10K-bc1daa94090c` — **minor / functional_regression** — markdown, page(s) 1, 2, 3: Raw Markdown has missing, added, replaced, duplicated, or reordered visible text. Owner: `GAP-TEXT-001` / `P02-US04`; test: `test_p02_us04_text_reconciliation.py`.
- `FID-FINANCE-10K-81d2e5054001` — **major / functional_regression** — markdown, page(s) 1, 2, 3: Heading text, level, or order differs from LlamaParse. Owner: `GAP-LIST-001` / `P03-US07`; test: `test_p03_us07_outline_structure.py`.
- `FID-FINANCE-10K-e67803d159eb` — **minor / functional_regression** — markdown, page(s) 1: User-visible Markdown emphasis or code syntax differs. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-FINANCE-10K-8d787dd65309` — **critical / functional_regression** — markdown, page(s) 1: Table 1 differs in shape, spans, row order, or cell content. Owner: `GAP-TABLE-003` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-FINANCE-10K-0db5ca2c153e` — **critical / functional_regression** — markdown, page(s) 2: Table 2 differs in shape, spans, row order, or cell content. Owner: `GAP-TABLE-003` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-FINANCE-10K-01196cc8d6b7` — **critical / functional_regression** — markdown, page(s) 3: Table 3 differs in shape, spans, row order, or cell content. Owner: `GAP-TABLE-003` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-FINANCE-10K-546d3d721e36` — **minor / acceptable_difference** — json, page(s) 1: Cross-envelope component decomposition or taxonomy differs on the page. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-FINANCE-10K-7910a110f738` — **minor / acceptable_difference** — json, page(s) 1: Service JSON adds nested component relationships beyond LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-FINANCE-10K-942ab32ac556` — **minor / acceptable_difference** — json, page(s) 2: Cross-envelope component decomposition or taxonomy differs on the page. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-FINANCE-10K-a4a59a3a5b6e` — **minor / acceptable_difference** — json, page(s) 3: Cross-envelope component decomposition or taxonomy differs on the page. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-FINANCE-10K-fa867cb538fe` — **critical / functional_regression** — json, page(s) 1: Table 1 differs in shape, spans, row order, or cell content. Owner: `GAP-TABLE-002` / `P04-US01`; test: `test_p04_us01_span_fidelity.py`.
- `FID-FINANCE-10K-c99d4fb830d1` — **critical / functional_regression** — json, page(s) 2: Table 2 differs in shape, spans, row order, or cell content. Owner: `GAP-TABLE-002` / `P04-US01`; test: `test_p04_us01_span_fidelity.py`.
- `FID-FINANCE-10K-f6465eaed071` — **critical / functional_regression** — json, page(s) 3: Table 3 differs in shape, spans, row order, or cell content. Owner: `GAP-TABLE-002` / `P04-US01`; test: `test_p04_us01_span_fidelity.py`.
- `FID-FINANCE-10K-e73853ea8e8b` — **major / functional_regression** — json, page(s) 1: Page-associated JSON component content differs from LlamaParse. Owner: `GAP-TEXT-001` / `P02-US04`; test: `test_p02_us04_text_reconciliation.py`.
- `FID-FINANCE-10K-4ac2a08a152e` — **major / functional_regression** — json, page(s) 2: Page-associated JSON component content differs from LlamaParse. Owner: `GAP-TEXT-001` / `P02-US04`; test: `test_p02_us04_text_reconciliation.py`.
- `FID-FINANCE-10K-f0e1277584b5` — **minor / functional_regression** — json, page(s) 3: Page-associated JSON component content differs from LlamaParse. Owner: `GAP-TEXT-001` / `P02-US04`; test: `test_p02_us04_text_reconciliation.py`.
- `FID-FINANCE-10K-549bdd5a4d52` — **major / functional_regression** — rendered_dom, page(s) 1: Rendered Markdown visible semantic text differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-FINANCE-10K-1120a609976e` — **major / functional_regression** — rendered_dom, page(s) 1: Rendered semantic tag hierarchy or order differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-FINANCE-10K-c2873fba0488` — **major / functional_regression** — rendered_dom, page(s) 1: Rendered item grouping/type sequence differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-FINANCE-10K-1d4a701f867c` — **critical / functional_regression** — rendered_dom, page(s) 1: Table 1 differs in shape, spans, row order, or cell content. Owner: `GAP-TABLE-003` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-FINANCE-10K-2690a34a582b` — **major / functional_regression** — rendered_dom, page(s) 2: Rendered Markdown visible semantic text differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-FINANCE-10K-bca02cd84bb6` — **major / functional_regression** — rendered_dom, page(s) 2: Rendered semantic tag hierarchy or order differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-FINANCE-10K-5b05b57dffa5` — **major / functional_regression** — rendered_dom, page(s) 2: Rendered item grouping/type sequence differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-FINANCE-10K-c6763eb5a189` — **critical / functional_regression** — rendered_dom, page(s) 2: Table 1 differs in shape, spans, row order, or cell content. Owner: `GAP-TABLE-003` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-FINANCE-10K-7b3a5d45f54c` — **major / functional_regression** — rendered_dom, page(s) 3: Rendered Markdown visible semantic text differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-FINANCE-10K-f05a3b5ea054` — **major / functional_regression** — rendered_dom, page(s) 3: Rendered semantic tag hierarchy or order differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-FINANCE-10K-4a5f1bdb0e8b` — **major / functional_regression** — rendered_dom, page(s) 3: Rendered item grouping/type sequence differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-FINANCE-10K-cd7192e72be9` — **critical / functional_regression** — rendered_dom, page(s) 3: Table 1 differs in shape, spans, row order, or cell content. Owner: `GAP-TABLE-003` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.

### health-report

Status: **discrepancy_found**

| Physical page | Page status | JSON text recall | JSON text precision | Sequence ratio | Reference DOM | Service DOM | Findings |
|---:|---|---:|---:|---:|---|---|---:|
| 1 | discrepancy_found | 49.56% | 72.41% | 51.14% | yes | yes | 15 |

- `FID-HEALTH-REPORT-993d6a632b14` — **critical / functional_regression** — markdown, page(s) 1: Raw Markdown has missing, added, replaced, duplicated, or reordered visible text. Owner: `GAP-TEXT-001` / `P02-US04`; test: `test_p02_us04_text_reconciliation.py`.
- `FID-HEALTH-REPORT-213d484517ef` — **major / functional_regression** — markdown, page(s) 1: Table count or document order differs from LlamaParse. Owner: `GAP-TABLE-001` / `P04-US04`; test: `test_p04_us04_table_candidate_gate.py`.
- `FID-HEALTH-REPORT-d54b8b67cac6` — **critical / functional_regression** — markdown, page(s) 1: Table 1 differs in shape, spans, row order, or cell content. Owner: `GAP-TABLE-003` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-HEALTH-REPORT-d8fbfe7e553d` — **minor / acceptable_difference** — json, page(s) 1: Cross-envelope component decomposition or taxonomy differs on the page. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-HEALTH-REPORT-655d1fb9fdc5` — **minor / acceptable_difference** — json, page(s) 1: Service JSON adds nested component relationships beyond LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-HEALTH-REPORT-1c4d85bc12e6` — **major / functional_regression** — json, page(s) 1: Table count or document order differs from LlamaParse. Owner: `GAP-TABLE-001` / `P04-US04`; test: `test_p04_us04_table_candidate_gate.py`.
- `FID-HEALTH-REPORT-e0115e31a832` — **critical / functional_regression** — json, page(s) 1: Page-associated JSON component content differs from LlamaParse. Owner: `GAP-TEXT-001` / `P02-US04`; test: `test_p02_us04_text_reconciliation.py`.
- `FID-HEALTH-REPORT-7d701b497ec5` — **minor / review_required** — json, page(s) 1: Visual-origin text proxy differs and requires region-level review. Owner: `GAP-OCR-001` / `P02-US06`; test: `test_p02_us06_spatial_tokens.py`.
- `FID-HEALTH-REPORT-93c9edbbbc19` — **critical / functional_regression** — json, page(s) 1: Chart 1 labels, values, description, or caption differ. Owner: `GAP-CHART-002` / `P05-US04`; test: `test_p05_us04_vector_values.py`.
- `FID-HEALTH-REPORT-593ba60401dc` — **critical / functional_regression** — json, page(s) 1: Chart 2 labels, values, description, or caption differ. Owner: `GAP-CHART-002` / `P05-US04`; test: `test_p05_us04_vector_values.py`.
- `FID-HEALTH-REPORT-5cd27ba79c60` — **critical / functional_regression** — rendered_dom, page(s) 1: Rendered Markdown visible semantic text differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-HEALTH-REPORT-8643b7992307` — **major / functional_regression** — rendered_dom, page(s) 1: Rendered semantic tag hierarchy or order differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-HEALTH-REPORT-2ccd4c7fcfa1` — **major / functional_regression** — rendered_dom, page(s) 1: Rendered item grouping/type sequence differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-HEALTH-REPORT-00a2246c35bd` — **critical / functional_regression** — rendered_dom, page(s) 1: Table count or document order differs from LlamaParse. Owner: `GAP-TABLE-001` / `P04-US04`; test: `test_p04_us04_table_candidate_gate.py`.
- `FID-HEALTH-REPORT-027ffc0290d5` — **major / functional_regression** — rendered_dom, page(s) 1: Rendered links differ in text, target, or order. Owner: `GAP-LINK-001` / `P01-US01`; test: `test_p01_us01_ir_contract.py`.

### insurance-acord

Status: **discrepancy_found**

| Physical page | Page status | JSON text recall | JSON text precision | Sequence ratio | Reference DOM | Service DOM | Findings |
|---:|---|---:|---:|---:|---|---|---:|
| 1 | discrepancy_found | 99.54% | 71.90% | 75.43% | yes | yes | 18 |

- `FID-INSURANCE-ACORD-681d2bb99aff` — **critical / functional_regression** — markdown, page(s) 1: Raw Markdown has missing, added, replaced, duplicated, or reordered visible text. Owner: `GAP-TEXT-001` / `P02-US04`; test: `test_p02_us04_text_reconciliation.py`.
- `FID-INSURANCE-ACORD-aa6422e37eef` — **major / functional_regression** — markdown, page(s) 1: Heading text, level, or order differs from LlamaParse. Owner: `GAP-LIST-001` / `P03-US07`; test: `test_p03_us07_outline_structure.py`.
- `FID-INSURANCE-ACORD-e804b92fa217` — **minor / functional_regression** — markdown, page(s) 1: User-visible Markdown emphasis or code syntax differs. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-INSURANCE-ACORD-3c0e132cd69f` — **critical / functional_regression** — markdown, page(s) 1: Table 1 differs in shape, spans, row order, or cell content. Owner: `GAP-TABLE-003` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-INSURANCE-ACORD-6ae2c85b2f75` — **critical / functional_regression** — markdown, page(s) 1: Table 2 differs in shape, spans, row order, or cell content. Owner: `GAP-TABLE-003` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-INSURANCE-ACORD-c2f6d459a7cc` — **critical / functional_regression** — markdown, page(s) 1: Table 3 differs in shape, spans, row order, or cell content. Owner: `GAP-TABLE-003` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-INSURANCE-ACORD-91f274b6b428` — **minor / acceptable_difference** — json, page(s) 1: Cross-envelope component decomposition or taxonomy differs on the page. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-INSURANCE-ACORD-1389a3dd73e6` — **minor / acceptable_difference** — json, page(s) 1: Service JSON adds nested component relationships beyond LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-INSURANCE-ACORD-d88f24385488` — **critical / functional_regression** — json, page(s) 1: Table 1 differs in shape, spans, row order, or cell content. Owner: `GAP-TABLE-002` / `P04-US01`; test: `test_p04_us01_span_fidelity.py`.
- `FID-INSURANCE-ACORD-bd389889329c` — **critical / functional_regression** — json, page(s) 1: Table 2 differs in shape, spans, row order, or cell content. Owner: `GAP-TABLE-002` / `P04-US01`; test: `test_p04_us01_span_fidelity.py`.
- `FID-INSURANCE-ACORD-1176c6f38b01` — **critical / functional_regression** — json, page(s) 1: Table 3 differs in shape, spans, row order, or cell content. Owner: `GAP-TABLE-002` / `P04-US01`; test: `test_p04_us01_span_fidelity.py`.
- `FID-INSURANCE-ACORD-88ecb3ac1794` — **critical / functional_regression** — json, page(s) 1: Page-associated JSON component content differs from LlamaParse. Owner: `GAP-TEXT-001` / `P02-US04`; test: `test_p02_us04_text_reconciliation.py`.
- `FID-INSURANCE-ACORD-a8d9f7730332` — **minor / review_required** — json, page(s) 1: Visual-origin text proxy differs and requires region-level review. Owner: `GAP-OCR-001` / `P02-US06`; test: `test_p02_us06_spatial_tokens.py`.
- `FID-INSURANCE-ACORD-6f9f3c509d2a` — **critical / functional_regression** — json, page(s) 1: Image 1 labels, values, description, or caption differ. Owner: `GAP-VISUAL-001` / `P06-US05`; test: `test_p06_us05_grounding.py`.
- `FID-INSURANCE-ACORD-056649e21eb7` — **critical / functional_regression** — rendered_dom, page(s) 1: Rendered Markdown visible semantic text differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-INSURANCE-ACORD-d2d336d388c6` — **major / functional_regression** — rendered_dom, page(s) 1: Rendered semantic tag hierarchy or order differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-INSURANCE-ACORD-8e0d8350a801` — **major / functional_regression** — rendered_dom, page(s) 1: Rendered item grouping/type sequence differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-INSURANCE-ACORD-2911357e84e9` — **critical / functional_regression** — rendered_dom, page(s) 1: Table count or document order differs from LlamaParse. Owner: `GAP-TABLE-001` / `P04-US04`; test: `test_p04_us04_table_candidate_gate.py`.

### manufacturing-report

Status: **discrepancy_found**

| Physical page | Page status | JSON text recall | JSON text precision | Sequence ratio | Reference DOM | Service DOM | Findings |
|---:|---|---:|---:|---:|---|---|---:|
| 1 | discrepancy_found | 95.77% | 70.10% | 57.14% | yes | yes | 18 |
| 2 | discrepancy_found | 41.39% | 57.63% | 23.70% | yes | yes | 17 |
| 3 | discrepancy_found | 62.99% | 92.97% | 70.19% | yes | yes | 17 |

- `FID-MANUFACTURING-REPORT-571c05381ca8` — **critical / functional_regression** — markdown, page(s) 1, 2, 3: Raw Markdown has missing, added, replaced, duplicated, or reordered visible text. Owner: `GAP-TEXT-001` / `P02-US04`; test: `test_p02_us04_text_reconciliation.py`.
- `FID-MANUFACTURING-REPORT-7047514464d2` — **major / functional_regression** — markdown, page(s) 3: Heading text, level, or order differs from LlamaParse. Owner: `GAP-LIST-001` / `P03-US07`; test: `test_p03_us07_outline_structure.py`.
- `FID-MANUFACTURING-REPORT-49318df3a14b` — **minor / functional_regression** — markdown, page(s) 1, 2, 3: User-visible Markdown emphasis or code syntax differs. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-MANUFACTURING-REPORT-6e32e3ff42fa` — **critical / functional_regression** — markdown, page(s) document: Table count or document order differs from LlamaParse. Owner: `GAP-TABLE-001` / `P04-US04`; test: `test_p04_us04_table_candidate_gate.py`.
- `FID-MANUFACTURING-REPORT-934041db3b24` — **minor / acceptable_difference** — json, page(s) 1: Cross-envelope component decomposition or taxonomy differs on the page. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-MANUFACTURING-REPORT-b5bc64251fe1` — **minor / acceptable_difference** — json, page(s) 1: Service JSON adds nested component relationships beyond LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-MANUFACTURING-REPORT-0dd8033d14fe` — **minor / acceptable_difference** — json, page(s) 2: Cross-envelope component decomposition or taxonomy differs on the page. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-MANUFACTURING-REPORT-488a9de364a0` — **minor / acceptable_difference** — json, page(s) 2: Cross-envelope nested component decomposition differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-MANUFACTURING-REPORT-3dd4b2ccb6b9` — **minor / acceptable_difference** — json, page(s) 3: Cross-envelope component decomposition or taxonomy differs on the page. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-MANUFACTURING-REPORT-9db9f7ee642c` — **minor / acceptable_difference** — json, page(s) 3: Service JSON adds nested component relationships beyond LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-MANUFACTURING-REPORT-4ac30774e63e` — **critical / functional_regression** — json, page(s) 1: Page-associated JSON component content differs from LlamaParse. Owner: `GAP-TEXT-001` / `P02-US04`; test: `test_p02_us04_text_reconciliation.py`.
- `FID-MANUFACTURING-REPORT-6ddabe8b6efd` — **critical / functional_regression** — json, page(s) 2: Page-associated JSON component content differs from LlamaParse. Owner: `GAP-TEXT-001` / `P02-US04`; test: `test_p02_us04_text_reconciliation.py`.
- `FID-MANUFACTURING-REPORT-7a334d146aee` — **critical / functional_regression** — json, page(s) 3: Page-associated JSON component content differs from LlamaParse. Owner: `GAP-TEXT-001` / `P02-US04`; test: `test_p02_us04_text_reconciliation.py`.
- `FID-MANUFACTURING-REPORT-15c4546d7718` — **minor / review_required** — json, page(s) 1, 2, 3: Visual-origin text proxy differs and requires region-level review. Owner: `GAP-OCR-001` / `P02-US06`; test: `test_p02_us06_spatial_tokens.py`.
- `FID-MANUFACTURING-REPORT-7f967af04d03` — **minor / acceptable_difference** — json, page(s) 3: Service emits additional image regions while retaining all LlamaParse image pages. Owner: `GAP-COVERAGE-001` / `P07-US02`; test: `test_p07_us02_image_parity.py plus M5 twins`.
- `FID-MANUFACTURING-REPORT-5aa0d7056284` — **major / functional_regression** — json, page(s) 1, 2, 3: Chart detection count or page placement differs from LlamaParse. Owner: `GAP-CHART-001` / `P05-US03`; test: `test_p05_us03_axes_legends.py`.
- `FID-MANUFACTURING-REPORT-1ca465a6906b` — **critical / functional_regression** — json, page(s) 1: Chart 1 labels, values, description, or caption differ. Owner: `GAP-CHART-002` / `P05-US04`; test: `test_p05_us04_vector_values.py`.
- `FID-MANUFACTURING-REPORT-3f543c51c865` — **major / functional_regression** — json, page(s) 1: Chart 1 associated caption text or ordering differs. Owner: `GAP-VISUAL-001` / `P06-US05`; test: `test_p06_us05_grounding.py`.
- `FID-MANUFACTURING-REPORT-2a8782805000` — **major / functional_regression** — json, page(s) 1: Chart 1 page-relative placement differs materially. Owner: `GAP-VISUAL-001` / `P06-US05`; test: `test_p06_us05_grounding.py`.
- `FID-MANUFACTURING-REPORT-71eb251f4fec` — **critical / functional_regression** — json, page(s) 1: Chart 2 labels, values, description, or caption differ. Owner: `GAP-CHART-002` / `P05-US04`; test: `test_p05_us04_vector_values.py`.
- `FID-MANUFACTURING-REPORT-4c6b880d88ee` — **major / functional_regression** — json, page(s) 1: Chart 2 associated caption text or ordering differs. Owner: `GAP-VISUAL-001` / `P06-US05`; test: `test_p06_us05_grounding.py`.
- `FID-MANUFACTURING-REPORT-84fb28d145a6` — **major / functional_regression** — json, page(s) 1: Chart 2 page-relative placement differs materially. Owner: `GAP-VISUAL-001` / `P06-US05`; test: `test_p06_us05_grounding.py`.
- `FID-MANUFACTURING-REPORT-0c1da69598b8` — **critical / functional_regression** — json, page(s) 2: Chart 3 labels, values, description, or caption differ. Owner: `GAP-CHART-002` / `P05-US04`; test: `test_p05_us04_vector_values.py`.
- `FID-MANUFACTURING-REPORT-4c2d359dd006` — **major / functional_regression** — json, page(s) 2: Chart 3 associated caption text or ordering differs. Owner: `GAP-VISUAL-001` / `P06-US05`; test: `test_p06_us05_grounding.py`.
- `FID-MANUFACTURING-REPORT-d3eb57d9916e` — **critical / functional_regression** — json, page(s) 2: Chart 4 labels, values, description, or caption differ. Owner: `GAP-CHART-002` / `P05-US04`; test: `test_p05_us04_vector_values.py`.
- `FID-MANUFACTURING-REPORT-e081b61b07b6` — **major / functional_regression** — json, page(s) 2: Chart 4 associated caption text or ordering differs. Owner: `GAP-VISUAL-001` / `P06-US05`; test: `test_p06_us05_grounding.py`.
- `FID-MANUFACTURING-REPORT-ffc9b397adc5` — **major / functional_regression** — json, page(s) 2: Chart 4 page-relative placement differs materially. Owner: `GAP-VISUAL-001` / `P06-US05`; test: `test_p06_us05_grounding.py`.
- `FID-MANUFACTURING-REPORT-66b5fefd0871` — **critical / functional_regression** — json, page(s) 3: Chart 5 labels, values, description, or caption differ. Owner: `GAP-CHART-002` / `P05-US04`; test: `test_p05_us04_vector_values.py`.
- `FID-MANUFACTURING-REPORT-b854cde4250a` — **major / functional_regression** — json, page(s) 3: Chart 5 associated caption text or ordering differs. Owner: `GAP-VISUAL-001` / `P06-US05`; test: `test_p06_us05_grounding.py`.
- `FID-MANUFACTURING-REPORT-5af954fae854` — **major / functional_regression** — json, page(s) 3: Chart 5 page-relative placement differs materially. Owner: `GAP-VISUAL-001` / `P06-US05`; test: `test_p06_us05_grounding.py`.
- `FID-MANUFACTURING-REPORT-f425a0c1830f` — **critical / functional_regression** — rendered_dom, page(s) 1: Rendered Markdown visible semantic text differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-MANUFACTURING-REPORT-b98ac22785a2` — **major / functional_regression** — rendered_dom, page(s) 1: Rendered semantic tag hierarchy or order differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-MANUFACTURING-REPORT-ff21aec376c0` — **major / functional_regression** — rendered_dom, page(s) 1: Rendered item grouping/type sequence differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-MANUFACTURING-REPORT-e605ae4622e4` — **critical / functional_regression** — rendered_dom, page(s) 1: Table count or document order differs from LlamaParse. Owner: `GAP-TABLE-001` / `P04-US04`; test: `test_p04_us04_table_candidate_gate.py`.
- `FID-MANUFACTURING-REPORT-994215ffdc38` — **major / functional_regression** — rendered_dom, page(s) 1: Rendered links differ in text, target, or order. Owner: `GAP-LINK-001` / `P01-US01`; test: `test_p01_us01_ir_contract.py`.
- `FID-MANUFACTURING-REPORT-93a4761c6ed9` — **critical / functional_regression** — rendered_dom, page(s) 2: Rendered Markdown visible semantic text differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-MANUFACTURING-REPORT-39a83f041dca` — **major / functional_regression** — rendered_dom, page(s) 2: Rendered semantic tag hierarchy or order differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-MANUFACTURING-REPORT-1c33bc48cb28` — **major / functional_regression** — rendered_dom, page(s) 2: Rendered item grouping/type sequence differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-MANUFACTURING-REPORT-a568fba898d7` — **critical / functional_regression** — rendered_dom, page(s) 2: Table count or document order differs from LlamaParse. Owner: `GAP-TABLE-001` / `P04-US04`; test: `test_p04_us04_table_candidate_gate.py`.
- `FID-MANUFACTURING-REPORT-cf539820227b` — **major / functional_regression** — rendered_dom, page(s) 2: Rendered links differ in text, target, or order. Owner: `GAP-LINK-001` / `P01-US01`; test: `test_p01_us01_ir_contract.py`.
- `FID-MANUFACTURING-REPORT-0495f81b3b79` — **critical / functional_regression** — rendered_dom, page(s) 3: Rendered Markdown visible semantic text differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-MANUFACTURING-REPORT-203a03772e35` — **major / functional_regression** — rendered_dom, page(s) 3: Rendered semantic tag hierarchy or order differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-MANUFACTURING-REPORT-ca45263b4d13` — **major / functional_regression** — rendered_dom, page(s) 3: Rendered item grouping/type sequence differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-MANUFACTURING-REPORT-7d99bc2f726d` — **critical / functional_regression** — rendered_dom, page(s) 3: Table count or document order differs from LlamaParse. Owner: `GAP-TABLE-001` / `P04-US04`; test: `test_p04_us04_table_candidate_gate.py`.
- `FID-MANUFACTURING-REPORT-24c3db60c9bf` — **major / functional_regression** — rendered_dom, page(s) 3: Rendered links differ in text, target, or order. Owner: `GAP-LINK-001` / `P01-US01`; test: `test_p01_us01_ir_contract.py`.

### ny-timetable

Status: **discrepancy_found**

| Physical page | Page status | JSON text recall | JSON text precision | Sequence ratio | Reference DOM | Service DOM | Findings |
|---:|---|---:|---:|---:|---|---|---:|
| 1 | discrepancy_found | 100.00% | 99.51% | 99.75% | yes | yes | 11 |
| 2 | discrepancy_found | 99.92% | 99.19% | 99.55% | yes | yes | 10 |
| 3 | discrepancy_found | 99.92% | 99.28% | 56.05% | yes | yes | 10 |

- `FID-NY-TIMETABLE-358dae8b30d5` — **critical / functional_regression** — markdown, page(s) 1, 2, 3: Raw Markdown has missing, added, replaced, duplicated, or reordered visible text. Owner: `GAP-TEXT-001` / `P02-US04`; test: `test_p02_us04_text_reconciliation.py`.
- `FID-NY-TIMETABLE-5864f57b266a` — **major / functional_regression** — markdown, page(s) 1: Heading text, level, or order differs from LlamaParse. Owner: `GAP-LIST-001` / `P03-US07`; test: `test_p03_us07_outline_structure.py`.
- `FID-NY-TIMETABLE-57118eda4864` — **minor / functional_regression** — markdown, page(s) 1: User-visible Markdown emphasis or code syntax differs. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-NY-TIMETABLE-3c09ae1c1fed` — **critical / functional_regression** — markdown, page(s) 1: Table 1 differs in shape, spans, row order, or cell content. Owner: `GAP-TABLE-003` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-NY-TIMETABLE-939790d49dcb` — **critical / functional_regression** — markdown, page(s) 2: Table 2 differs in shape, spans, row order, or cell content. Owner: `GAP-TABLE-003` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-NY-TIMETABLE-f68fa7226c40` — **critical / functional_regression** — markdown, page(s) 3: Table 3 differs in shape, spans, row order, or cell content. Owner: `GAP-TABLE-003` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-NY-TIMETABLE-a9a8053fa774` — **minor / acceptable_difference** — json, page(s) 1: Cross-envelope component decomposition or taxonomy differs on the page. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-NY-TIMETABLE-34991435f173` — **minor / acceptable_difference** — json, page(s) 2: Cross-envelope component decomposition or taxonomy differs on the page. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-NY-TIMETABLE-3f2bed50ee27` — **minor / acceptable_difference** — json, page(s) 2: Cross-envelope nested component decomposition differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-NY-TIMETABLE-bb92f53c6ee9` — **minor / acceptable_difference** — json, page(s) 3: Cross-envelope component decomposition or taxonomy differs on the page. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-NY-TIMETABLE-42e8a9347b49` — **minor / acceptable_difference** — json, page(s) 3: Cross-envelope nested component decomposition differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-NY-TIMETABLE-55d88e759692` — **critical / functional_regression** — json, page(s) 1: Table 1 differs in shape, spans, row order, or cell content. Owner: `GAP-TABLE-002` / `P04-US01`; test: `test_p04_us01_span_fidelity.py`.
- `FID-NY-TIMETABLE-1e69e533b324` — **critical / functional_regression** — json, page(s) 2: Table 2 differs in shape, spans, row order, or cell content. Owner: `GAP-TABLE-002` / `P04-US01`; test: `test_p04_us01_span_fidelity.py`.
- `FID-NY-TIMETABLE-cb3f118c17f7` — **critical / functional_regression** — json, page(s) 3: Table 3 differs in shape, spans, row order, or cell content. Owner: `GAP-TABLE-002` / `P04-US01`; test: `test_p04_us01_span_fidelity.py`.
- `FID-NY-TIMETABLE-729bf6cba878` — **minor / functional_regression** — json, page(s) 1: Page-associated JSON component content differs from LlamaParse. Owner: `GAP-TEXT-001` / `P02-US04`; test: `test_p02_us04_text_reconciliation.py`.
- `FID-NY-TIMETABLE-1bdfb990f0de` — **minor / functional_regression** — json, page(s) 2: Page-associated JSON component content differs from LlamaParse. Owner: `GAP-TEXT-001` / `P02-US04`; test: `test_p02_us04_text_reconciliation.py`.
- `FID-NY-TIMETABLE-a29d15dd38c2` — **critical / functional_regression** — json, page(s) 3: Page-associated JSON component content differs from LlamaParse. Owner: `GAP-TEXT-001` / `P02-US04`; test: `test_p02_us04_text_reconciliation.py`.
- `FID-NY-TIMETABLE-2473d2c6e802` — **minor / functional_regression** — rendered_dom, page(s) 1: Rendered Markdown visible semantic text differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-NY-TIMETABLE-b9e805b3b091` — **major / functional_regression** — rendered_dom, page(s) 1: Rendered semantic tag hierarchy or order differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-NY-TIMETABLE-1f9bb2261833` — **major / functional_regression** — rendered_dom, page(s) 1: Rendered item grouping/type sequence differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-NY-TIMETABLE-c275bd14b32f` — **critical / functional_regression** — rendered_dom, page(s) 1: Table 1 differs in shape, spans, row order, or cell content. Owner: `GAP-TABLE-003` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-NY-TIMETABLE-441f9d74c0ad` — **minor / functional_regression** — rendered_dom, page(s) 2: Rendered Markdown visible semantic text differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-NY-TIMETABLE-804d13cbd54e` — **major / functional_regression** — rendered_dom, page(s) 2: Rendered semantic tag hierarchy or order differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-NY-TIMETABLE-f6275c7de11f` — **major / functional_regression** — rendered_dom, page(s) 2: Rendered item grouping/type sequence differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-NY-TIMETABLE-8c5df9cd0cec` — **critical / functional_regression** — rendered_dom, page(s) 2: Table 1 differs in shape, spans, row order, or cell content. Owner: `GAP-TABLE-003` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-NY-TIMETABLE-0333270312ad` — **critical / functional_regression** — rendered_dom, page(s) 3: Rendered Markdown visible semantic text differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-NY-TIMETABLE-c472fed49126` — **major / functional_regression** — rendered_dom, page(s) 3: Rendered semantic tag hierarchy or order differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-NY-TIMETABLE-fa59b6f7dac0` — **major / functional_regression** — rendered_dom, page(s) 3: Rendered item grouping/type sequence differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-NY-TIMETABLE-08d2888497f4` — **critical / functional_regression** — rendered_dom, page(s) 3: Table 1 differs in shape, spans, row order, or cell content. Owner: `GAP-TABLE-003` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.

### postal-10k

Status: **discrepancy_found**

| Physical page | Page status | JSON text recall | JSON text precision | Sequence ratio | Reference DOM | Service DOM | Findings |
|---:|---|---:|---:|---:|---|---|---:|
| 1 | discrepancy_found | 100.00% | 95.55% | 97.72% | yes | yes | 9 |
| 2 | discrepancy_found | 96.90% | 91.91% | 94.34% | yes | yes | 10 |
| 3 | discrepancy_found | 100.00% | 96.81% | 98.38% | yes | yes | 11 |

Resolved discrepancy evidence:

- Prior IDs: `FID-POSTAL-10K-805dd524ea4c`
- Code changes: `["app/services/pipeline.py: rebind non-target running-region canonical blocks to singleton public custody", "app/models.py: require complete context-free public overlay validation"]`
- Validation: `["local: .venv/bin/pytest -q tests/regression/phase_04/test_p04_us01_public_projection_regression.py -> 2 passed", "agent-verified: P03/P04 custody suites -> 187 passed", "agent-verified: API/model/visual suites -> 139 passed", "agent-verified: opt-in exact two-case corpus drift -> 2 passed", "agent-verified: compileall passed", "fresh LlamaParse Agentic job pjb-a97cbzz7kcwjfk5n2n51r6jkyljc", "fresh post-fix HTTP JSON and Markdown 200 responses", "fresh reference and service rendered-DOM capture"]`
- Validation scope: `Public API parse-blocking defect only; unrelated fidelity differences remain open.`
- Remaining evidence: `["See comparison/postal-10k/evidence.json for current Markdown, JSON, table, and rendered differences."]`
- Current raw artifacts are bound by SHA-256 in the case evidence.

- `FID-POSTAL-10K-bef746f86b84` — **minor / functional_regression** — markdown, page(s) 1, 2, 3: Raw Markdown has missing, added, replaced, duplicated, or reordered visible text. Owner: `GAP-TEXT-001` / `P02-US04`; test: `test_p02_us04_text_reconciliation.py`.
- `FID-POSTAL-10K-46976029171d` — **major / functional_regression** — markdown, page(s) 2, 3: Heading text, level, or order differs from LlamaParse. Owner: `GAP-LIST-001` / `P03-US07`; test: `test_p03_us07_outline_structure.py`.
- `FID-POSTAL-10K-39152c79bdbc` — **minor / functional_regression** — markdown, page(s) 3: User-visible Markdown emphasis or code syntax differs. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-POSTAL-10K-5d7ad72c5a64` — **major / functional_regression** — markdown, page(s) 1: Table 1 differs in shape, spans, row order, or cell content. Owner: `GAP-TABLE-003` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-POSTAL-10K-f3794519e215` — **major / functional_regression** — markdown, page(s) 2: Table 2 differs in shape, spans, row order, or cell content. Owner: `GAP-TABLE-003` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-POSTAL-10K-20c56ad733fd` — **critical / functional_regression** — markdown, page(s) 3: Table 3 differs in shape, spans, row order, or cell content. Owner: `GAP-TABLE-003` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-POSTAL-10K-1e83115c05ee` — **minor / acceptable_difference** — json, page(s) 1: Cross-envelope component decomposition or taxonomy differs on the page. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-POSTAL-10K-5242a9c9e257` — **minor / acceptable_difference** — json, page(s) 2: Cross-envelope component decomposition or taxonomy differs on the page. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-POSTAL-10K-03829e843250` — **minor / acceptable_difference** — json, page(s) 3: Cross-envelope component decomposition or taxonomy differs on the page. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-POSTAL-10K-f216f5bfea98` — **major / functional_regression** — json, page(s) 1: Table 1 differs in shape, spans, row order, or cell content. Owner: `GAP-TABLE-002` / `P04-US01`; test: `test_p04_us01_span_fidelity.py`.
- `FID-POSTAL-10K-86120a6ddb27` — **major / functional_regression** — json, page(s) 2: Table 2 differs in shape, spans, row order, or cell content. Owner: `GAP-TABLE-002` / `P04-US01`; test: `test_p04_us01_span_fidelity.py`.
- `FID-POSTAL-10K-a1b1d6df1503` — **critical / functional_regression** — json, page(s) 3: Table 3 differs in shape, spans, row order, or cell content. Owner: `GAP-TABLE-002` / `P04-US01`; test: `test_p04_us01_span_fidelity.py`.
- `FID-POSTAL-10K-06891ce06a38` — **major / functional_regression** — json, page(s) 1: Page-associated JSON component content differs from LlamaParse. Owner: `GAP-TEXT-001` / `P02-US04`; test: `test_p02_us04_text_reconciliation.py`.
- `FID-POSTAL-10K-58019aa19019` — **major / functional_regression** — json, page(s) 2: Page-associated JSON component content differs from LlamaParse. Owner: `GAP-TEXT-001` / `P02-US04`; test: `test_p02_us04_text_reconciliation.py`.
- `FID-POSTAL-10K-2022440939c9` — **major / functional_regression** — json, page(s) 3: Page-associated JSON component content differs from LlamaParse. Owner: `GAP-TEXT-001` / `P02-US04`; test: `test_p02_us04_text_reconciliation.py`.
- `FID-POSTAL-10K-3292be1abe04` — **critical / functional_regression** — rendered_dom, page(s) 1: Rendered Markdown visible semantic text differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-POSTAL-10K-ef9b1dadaff2` — **major / functional_regression** — rendered_dom, page(s) 1: Rendered semantic tag hierarchy or order differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-POSTAL-10K-9c641bb00af0` — **major / functional_regression** — rendered_dom, page(s) 1: Rendered item grouping/type sequence differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-POSTAL-10K-f6d8d0d1be16` — **major / functional_regression** — rendered_dom, page(s) 1: Table count or document order differs from LlamaParse. Owner: `GAP-TABLE-001` / `P04-US04`; test: `test_p04_us04_table_candidate_gate.py`.
- `FID-POSTAL-10K-a4f0c1c8abc9` — **critical / functional_regression** — rendered_dom, page(s) 2: Rendered Markdown visible semantic text differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-POSTAL-10K-a85ecb2b6c79` — **major / functional_regression** — rendered_dom, page(s) 2: Rendered semantic tag hierarchy or order differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-POSTAL-10K-4af81021c350` — **major / functional_regression** — rendered_dom, page(s) 2: Rendered item grouping/type sequence differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-POSTAL-10K-3187c960416f` — **major / functional_regression** — rendered_dom, page(s) 2: Table count or document order differs from LlamaParse. Owner: `GAP-TABLE-001` / `P04-US04`; test: `test_p04_us04_table_candidate_gate.py`.
- `FID-POSTAL-10K-b1bcd9dc74ca` — **critical / functional_regression** — rendered_dom, page(s) 3: Rendered Markdown visible semantic text differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-POSTAL-10K-1be56bdec0ef` — **major / functional_regression** — rendered_dom, page(s) 3: Rendered semantic tag hierarchy or order differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-POSTAL-10K-bba2f06cdd98` — **major / functional_regression** — rendered_dom, page(s) 3: Rendered item grouping/type sequence differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-POSTAL-10K-038795e08224` — **major / functional_regression** — rendered_dom, page(s) 3: Table count or document order differs from LlamaParse. Owner: `GAP-TABLE-001` / `P04-US04`; test: `test_p04_us04_table_candidate_gate.py`.

### purchase-agreement

Status: **discrepancy_found**

| Physical page | Page status | JSON text recall | JSON text precision | Sequence ratio | Reference DOM | Service DOM | Findings |
|---:|---|---:|---:|---:|---|---|---:|
| 1 | discrepancy_found | 100.00% | 99.80% | 99.90% | yes | yes | 8 |

- `FID-PURCHASE-AGREEMENT-a1f09047bf65` — **minor / functional_regression** — markdown, page(s) 1: Raw Markdown has missing, added, replaced, duplicated, or reordered visible text. Owner: `GAP-TEXT-001` / `P02-US04`; test: `test_p02_us04_text_reconciliation.py`.
- `FID-PURCHASE-AGREEMENT-e15feb985a62` — **major / functional_regression** — markdown, page(s) 1: Heading text, level, or order differs from LlamaParse. Owner: `GAP-LIST-001` / `P03-US07`; test: `test_p03_us07_outline_structure.py`.
- `FID-PURCHASE-AGREEMENT-293a5b1de8f7` — **minor / functional_regression** — markdown, page(s) 1: User-visible Markdown emphasis or code syntax differs. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-PURCHASE-AGREEMENT-8f9ef5431725` — **minor / acceptable_difference** — json, page(s) 1: Cross-envelope component decomposition or taxonomy differs on the page. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-PURCHASE-AGREEMENT-9d1e53a4ccf9` — **minor / functional_regression** — json, page(s) 1: Page-associated JSON component content differs from LlamaParse. Owner: `GAP-TEXT-001` / `P02-US04`; test: `test_p02_us04_text_reconciliation.py`.
- `FID-PURCHASE-AGREEMENT-e906938c16e7` — **minor / functional_regression** — rendered_dom, page(s) 1: Rendered Markdown visible semantic text differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-PURCHASE-AGREEMENT-02b0a542e555` — **major / functional_regression** — rendered_dom, page(s) 1: Rendered semantic tag hierarchy or order differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-PURCHASE-AGREEMENT-f22e8780db07` — **major / functional_regression** — rendered_dom, page(s) 1: Rendered item grouping/type sequence differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.

### settlement-agreement

Status: **discrepancy_found**

| Physical page | Page status | JSON text recall | JSON text precision | Sequence ratio | Reference DOM | Service DOM | Findings |
|---:|---|---:|---:|---:|---|---|---:|
| 1 | discrepancy_found | 99.33% | 99.11% | 99.22% | yes | yes | 10 |

- `FID-SETTLEMENT-AGREEMENT-dcebd22141bf` — **minor / functional_regression** — markdown, page(s) 1: Raw Markdown has missing, added, replaced, duplicated, or reordered visible text. Owner: `GAP-TEXT-001` / `P02-US04`; test: `test_p02_us04_text_reconciliation.py`.
- `FID-SETTLEMENT-AGREEMENT-068a56e11ad1` — **minor / functional_regression** — markdown, page(s) 1: User-visible Markdown emphasis or code syntax differs. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-SETTLEMENT-AGREEMENT-015c49e44743` — **major / functional_regression** — markdown, page(s) 1: Table 1 differs in shape, spans, row order, or cell content. Owner: `GAP-TABLE-003` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-SETTLEMENT-AGREEMENT-98c50c05c437` — **minor / acceptable_difference** — json, page(s) 1: Component type names differ but map to the same semantic families and order. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-SETTLEMENT-AGREEMENT-715d1044c081` — **major / functional_regression** — json, page(s) 1: Table 1 differs in shape, spans, row order, or cell content. Owner: `GAP-TABLE-002` / `P04-US01`; test: `test_p04_us01_span_fidelity.py`.
- `FID-SETTLEMENT-AGREEMENT-01f6e229967c` — **minor / functional_regression** — json, page(s) 1: Page-associated JSON component content differs from LlamaParse. Owner: `GAP-TEXT-001` / `P02-US04`; test: `test_p02_us04_text_reconciliation.py`.
- `FID-SETTLEMENT-AGREEMENT-e84eb88221cb` — **minor / functional_regression** — rendered_dom, page(s) 1: Rendered Markdown visible semantic text differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-SETTLEMENT-AGREEMENT-c3c86d501635` — **major / functional_regression** — rendered_dom, page(s) 1: Rendered semantic tag hierarchy or order differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-SETTLEMENT-AGREEMENT-4742c6e21c60` — **major / functional_regression** — rendered_dom, page(s) 1: Rendered item grouping/type sequence differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-SETTLEMENT-AGREEMENT-7370a7e3d335` — **major / functional_regression** — rendered_dom, page(s) 1: Table 1 differs in shape, spans, row order, or cell content. Owner: `GAP-TABLE-003` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.

### uber-earnings

Status: **discrepancy_found**

| Physical page | Page status | JSON text recall | JSON text precision | Sequence ratio | Reference DOM | Service DOM | Findings |
|---:|---|---:|---:|---:|---|---|---:|
| 1 | discrepancy_found | 54.55% | 66.67% | 45.00% | yes | yes | 12 |
| 2 | discrepancy_found | 64.10% | 60.98% | 40.83% | yes | yes | 18 |
| 3 | discrepancy_found | 48.86% | 87.76% | 54.01% | yes | yes | 12 |

- `FID-UBER-EARNINGS-0260ee013175` — **critical / functional_regression** — markdown, page(s) 1, 2, 3: Raw Markdown has missing, added, replaced, duplicated, or reordered visible text. Owner: `GAP-TEXT-001` / `P02-US04`; test: `test_p02_us04_text_reconciliation.py`.
- `FID-UBER-EARNINGS-858da308162c` — **major / functional_regression** — markdown, page(s) 1, 2, 3: Heading text, level, or order differs from LlamaParse. Owner: `GAP-LIST-001` / `P03-US07`; test: `test_p03_us07_outline_structure.py`.
- `FID-UBER-EARNINGS-9c4cd53cfb88` — **minor / functional_regression** — markdown, page(s) 1, 2, 3: User-visible Markdown emphasis or code syntax differs. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-UBER-EARNINGS-3ed2d799f995` — **critical / functional_regression** — markdown, page(s) document: Table count or document order differs from LlamaParse. Owner: `GAP-TABLE-001` / `P04-US04`; test: `test_p04_us04_table_candidate_gate.py`.
- `FID-UBER-EARNINGS-fe9f0a58649e` — **minor / acceptable_difference** — json, page(s) 1: Cross-envelope component decomposition or taxonomy differs on the page. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-UBER-EARNINGS-7d25fd2388e9` — **minor / acceptable_difference** — json, page(s) 1: Service JSON adds nested component relationships beyond LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-UBER-EARNINGS-b96e14d674d2` — **minor / acceptable_difference** — json, page(s) 2: Cross-envelope component decomposition or taxonomy differs on the page. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-UBER-EARNINGS-2ead6b2a765d` — **minor / acceptable_difference** — json, page(s) 2: Service JSON adds nested component relationships beyond LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-UBER-EARNINGS-606c50e4045d` — **minor / acceptable_difference** — json, page(s) 3: Cross-envelope component decomposition or taxonomy differs on the page. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-UBER-EARNINGS-b97e58332eb5` — **minor / acceptable_difference** — json, page(s) 3: Service JSON adds nested component relationships beyond LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-UBER-EARNINGS-42c4107aa7b8` — **critical / functional_regression** — json, page(s) 1: Page-associated JSON component content differs from LlamaParse. Owner: `GAP-TEXT-001` / `P02-US04`; test: `test_p02_us04_text_reconciliation.py`.
- `FID-UBER-EARNINGS-64b244c4756e` — **critical / functional_regression** — json, page(s) 2: Page-associated JSON component content differs from LlamaParse. Owner: `GAP-TEXT-001` / `P02-US04`; test: `test_p02_us04_text_reconciliation.py`.
- `FID-UBER-EARNINGS-a9f1a25340a2` — **critical / functional_regression** — json, page(s) 3: Page-associated JSON component content differs from LlamaParse. Owner: `GAP-TEXT-001` / `P02-US04`; test: `test_p02_us04_text_reconciliation.py`.
- `FID-UBER-EARNINGS-692ed2c08bf6` — **minor / review_required** — json, page(s) 1, 2, 3: Visual-origin text proxy differs and requires region-level review. Owner: `GAP-OCR-001` / `P02-US06`; test: `test_p02_us06_spatial_tokens.py`.
- `FID-UBER-EARNINGS-59bfd52367e1` — **major / functional_regression** — json, page(s) 1, 2, 3: Image detection count or page placement differs from LlamaParse. Owner: `GAP-COVERAGE-001` / `P07-US02`; test: `test_p07_us02_image_parity.py plus M5 twins`.
- `FID-UBER-EARNINGS-9ca384140fc1` — **critical / functional_regression** — json, page(s) 1: Image 1 labels, values, description, or caption differ. Owner: `GAP-VISUAL-001` / `P06-US05`; test: `test_p06_us05_grounding.py`.
- `FID-UBER-EARNINGS-bc1d3c49768c` — **critical / functional_regression** — json, page(s) 2: Image 2 labels, values, description, or caption differ. Owner: `GAP-VISUAL-001` / `P06-US05`; test: `test_p06_us05_grounding.py`.
- `FID-UBER-EARNINGS-c7d70a2591c2` — **major / functional_regression** — json, page(s) 2: Image 3 page-relative placement differs materially. Owner: `GAP-VISUAL-001` / `P06-US05`; test: `test_p06_us05_grounding.py`.
- `FID-UBER-EARNINGS-b1072eb8825e` — **major / functional_regression** — json, page(s) 2: Image 4 page-relative placement differs materially. Owner: `GAP-VISUAL-001` / `P06-US05`; test: `test_p06_us05_grounding.py`.
- `FID-UBER-EARNINGS-7dccb5715211` — **major / functional_regression** — json, page(s) 2, 3: Chart detection count or page placement differs from LlamaParse. Owner: `GAP-CHART-001` / `P05-US03`; test: `test_p05_us03_axes_legends.py`.
- `FID-UBER-EARNINGS-9033bcb7d0e1` — **critical / functional_regression** — json, page(s) 2: Chart 1 labels, values, description, or caption differ. Owner: `GAP-CHART-002` / `P05-US04`; test: `test_p05_us04_vector_values.py`.
- `FID-UBER-EARNINGS-05f5fa356a9a` — **critical / functional_regression** — json, page(s) 2: Chart 2 labels, values, description, or caption differ. Owner: `GAP-CHART-002` / `P05-US04`; test: `test_p05_us04_vector_values.py`.
- `FID-UBER-EARNINGS-8b1fdd3dd7d7` — **critical / functional_regression** — rendered_dom, page(s) 1: Rendered Markdown visible semantic text differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-UBER-EARNINGS-4c2e0beeb2cd` — **major / functional_regression** — rendered_dom, page(s) 1: Rendered semantic tag hierarchy or order differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-UBER-EARNINGS-abd38be1753f` — **major / functional_regression** — rendered_dom, page(s) 1: Rendered item grouping/type sequence differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-UBER-EARNINGS-17b9f12ca38b` — **critical / functional_regression** — rendered_dom, page(s) 2: Rendered Markdown visible semantic text differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-UBER-EARNINGS-3e519aad7c0c` — **major / functional_regression** — rendered_dom, page(s) 2: Rendered semantic tag hierarchy or order differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-UBER-EARNINGS-892028c05264` — **major / functional_regression** — rendered_dom, page(s) 2: Rendered item grouping/type sequence differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-UBER-EARNINGS-292bed5856cc` — **critical / functional_regression** — rendered_dom, page(s) 2: Table count or document order differs from LlamaParse. Owner: `GAP-TABLE-001` / `P04-US04`; test: `test_p04_us04_table_candidate_gate.py`.
- `FID-UBER-EARNINGS-6e8c020d2dff` — **critical / functional_regression** — rendered_dom, page(s) 3: Rendered Markdown visible semantic text differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-UBER-EARNINGS-e8d012f7549f` — **major / functional_regression** — rendered_dom, page(s) 3: Rendered semantic tag hierarchy or order differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-UBER-EARNINGS-0a7f2e6a679f` — **major / functional_regression** — rendered_dom, page(s) 3: Rendered item grouping/type sequence differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.

## Comparison policy and limitations

- **Signal counting:** Counts are intentionally conservative and may correlate across output surfaces or cascade after an unmatched table/visual. They are not a count of independently confirmed defects.
- **JSON text scope:** LlamaParse page Markdown and the service all-item page projection are not perfectly symmetric; text metrics are diagnostic and require source-page review.
- **Visual matching:** Baseline visual bboxes/fragments can represent generated descriptions or multiple regions for one source visual, while the service can group or refine them differently. Geometry/type-count signals therefore require source adjudication.
- **Table matching:** Tables are paired in page order. One missing or baseline chart-as-table item can cascade later pairwise differences; chart-labelled table-shaped baseline items are compared as visuals instead of physical tables.
- **Authority:** The hash-bound source PDF is authoritative. Baseline prose, inferred chart values, unsupported links, and source-contradicted structure are recorded as accepted differences rather than parity targets.

- **Baseline Role:** LlamaParse is the requested reference baseline, not independent source truth; a difference can expose a baseline defect rather than a service defect.
- **Json Envelopes:** Exact wire-schema parity is not required. Raw keys, paths, types, and nesting are inventoried, while functional classification uses normalized page, content, table, visual, and ordering projections.
- **Component Decomposition:** Type-family and nesting-only differences are reported as acceptable schema differences; missing/reordered user-visible content is classified independently.
- **Chart Table Polymorphism:** A LlamaParse table item labelled only as chart is compared as a chart visual and excluded from business-table counts.
- **Page Identity:** Physical page association prefers service page_index; printed page labels are compared separately against LlamaParse page-number tokens.
- **Ocr And Visuals:** Non-scanned visual-origin OCR aggregation is a token proxy, not spatial source truth; proxy-only differences require page-region review.
- **Rendering:** DOM checks compare semantic tags, text, grouping, tables, links, and meaningful layout tokens. PNG metrics are diagnostic unless viewport, fonts, theme, and renderer match.
- **Surface Independence:** Standalone reference Markdown and page Markdown embedded in LlamaParse JSON can differ; each surface is compared independently.
- **Out Of Scope:** Latency, CPU, memory, and exhaustive hardening are not measured.

## Validation and resolution rule

Each machine-readable discrepancy contains the expected LlamaParse projection, actual service projection, page/output type, complete table cell evidence where applicable, severity, story owner, acceptance criterion, and a stable reproduction command. Unit-test success alone is insufficient: resolved cases must retain fresh raw Markdown, JSON, rendered DOM, and snapshot evidence. The optional resolution ledger can label a clean case `fixed` only when it binds the current four raw artifact hashes and identifies prior discrepancy IDs.
