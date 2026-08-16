# LlamaParse-15 functional-fidelity comparison

Run: `functional-fidelity-20260813`  
Candidate artifacts: `service-post-fix`  
Analyzer schema: `functional-fidelity-comparison-v1`  
Story mapping: `tracker/benchmarks/llamaparse-15/gap-to-story-matrix.md`

This is a functionality/output-quality comparison. It does not make latency, CPU, memory, or exhaustive hardening claims.

The finding count is a conservative count of reproducible discrepancy signals,
not a count of unique confirmed root-cause defects. One root cause can emit
Markdown, JSON, table, and rendered-DOM signals on several pages. LlamaParse is
the requested reference, while the retained source-page reviews remain the
truth authority when the baseline itself inferred or misrepresented content.

Known interpretation limits: reference JSON page text is often body-only while
service page text may include all public items; visual matching can choose the
first reference box where a chart-labelled or largest box is more appropriate;
exact visual fragment/type counts can penalize legitimate service grouping;
and positional table pairing can cascade after one missing table. Accordingly,
individual JSON/visual signal IDs require source-page review before being
treated as distinct production defects. These limits do not change the release
decision because every PDF also has independently user-visible Markdown,
table, ordering, or rendered-content differences.

## Release readiness

**NOT READY** — 272 functional regression(s), 9 manual-review signal(s), 0 evidence gap(s), 55 accepted/harmless difference(s), and 2 hash-validated resolved discrepancy/discrepancies.

A `pending` case lacks one or more service artifacts or rendered-page captures; it is not a fidelity pass. A `fixed` case requires a hash-bound resolution ledger and a clean rerun. A hash-bound prior issue may be resolved while unrelated current findings keep the PDF at `discrepancy_found`.

## Per-PDF status

| PDF | Status | Critical | Major | Minor | Functional | Review | Evidence gaps | Evidence |
|---|---|---:|---:|---:|---:|---:|---:|---|
| `catastrophe-recap.pdf` | **discrepancy_found** | 5 | 2 | 5 | 8 | 1 | 0 | [`evidence.json`](catastrophe-recap/evidence.json) |
| `clean-energy.pdf` | **discrepancy_found** | 6 | 3 | 5 | 10 | 1 | 0 | [`evidence.json`](clean-energy/evidence.json) |
| `clinical-study.pdf` | **discrepancy_found** | 10 | 23 | 10 | 34 | 1 | 0 | [`evidence.json`](clinical-study/evidence.json) |
| `component-datasheet.pdf` | **discrepancy_found** | 10 | 9 | 6 | 20 | 0 | 0 | [`evidence.json`](component-datasheet/evidence.json) |
| `egov-survey.pdf` | **discrepancy_found** | 6 | 3 | 4 | 10 | 1 | 0 | [`evidence.json`](egov-survey/evidence.json) |
| `esg-metrics.pdf` | **discrepancy_found** | 5 | 10 | 5 | 16 | 1 | 0 | [`evidence.json`](esg-metrics/evidence.json) |
| `finance-10k.pdf` | **discrepancy_found** | 9 | 12 | 7 | 24 | 0 | 0 | [`evidence.json`](finance-10k/evidence.json) |
| `health-report.pdf` | **discrepancy_found** | 7 | 5 | 3 | 12 | 1 | 0 | [`evidence.json`](health-report/evidence.json) |
| `insurance-acord.pdf` | **discrepancy_found** | 9 | 5 | 4 | 15 | 1 | 0 | [`evidence.json`](insurance-acord/evidence.json) |
| `manufacturing-report.pdf` | **discrepancy_found** | 17 | 20 | 9 | 38 | 1 | 0 | [`evidence.json`](manufacturing-report/evidence.json) |
| `ny-timetable.pdf` | **discrepancy_found** | 16 | 7 | 6 | 24 | 0 | 0 | [`evidence.json`](ny-timetable/evidence.json) |
| `postal-10k.pdf` | **discrepancy_found** | 5 | 11 | 5 | 18 | 0 | 0 | [`evidence.json`](postal-10k/evidence.json) |
| `purchase-agreement.pdf` | **discrepancy_found** | 0 | 3 | 5 | 7 | 0 | 0 | [`evidence.json`](purchase-agreement/evidence.json) |
| `settlement-agreement.pdf` | **discrepancy_found** | 1 | 4 | 5 | 9 | 0 | 0 | [`evidence.json`](settlement-agreement/evidence.json) |
| `uber-earnings.pdf` | **discrepancy_found** | 13 | 13 | 8 | 27 | 1 | 0 | [`evidence.json`](uber-earnings/evidence.json) |

## Findings

### catastrophe-recap

Status: **discrepancy_found**

| Physical page | Page status | JSON text recall | JSON text precision | Sequence ratio | Reference DOM | Service DOM | Findings |
|---:|---|---:|---:|---:|---|---|---:|
| 1 | discrepancy_found | 60.79% | 95.33% | 67.88% | yes | yes | 12 |

Resolved discrepancy evidence:

- Prior IDs: `FID-CATASTROPHE-RECAP-80d905db1393`
- Code changes: `["app/services/pipeline.py: rebind non-target visual canonical blocks to exact public layout relationships and exclusions", "app/models.py: require complete context-free public overlay validation"]`
- Validation: `["local: .venv/bin/pytest -q tests/regression/phase_04/test_p04_us01_public_projection_regression.py -> 2 passed", "agent-verified: P03/P04 custody suites -> 187 passed", "agent-verified: API/model/visual suites -> 139 passed", "agent-verified: opt-in exact two-case corpus drift -> 2 passed", "agent-verified: compileall passed", "fresh LlamaParse Agentic job pjb-7zcmu6esqvbzn6dxsc5lefxs2qa3", "fresh post-fix HTTP JSON and Markdown 200 responses", "fresh reference and service rendered-DOM capture"]`
- Validation scope: `Public API parse-blocking defect only; unrelated fidelity differences remain open.`
- Remaining evidence: `["See comparison/catastrophe-recap/evidence.json for current Markdown, JSON, visual, table, and rendered differences."]`
- Current raw artifacts are bound by SHA-256 in the case evidence.

- `FID-CATASTROPHE-RECAP-913b533a66b0` — **critical / functional_regression** — markdown, page(s) 1: Raw Markdown has missing, added, replaced, duplicated, or reordered visible text. Owner: `GAP-TEXT-001` / `P02-US04`; test: `test_p02_us04_text_reconciliation.py`.
- `FID-CATASTROPHE-RECAP-327194d1001c` — **minor / functional_regression** — markdown, page(s) 1: User-visible Markdown emphasis or code syntax differs. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-CATASTROPHE-RECAP-3a08c6497cba` — **major / functional_regression** — markdown, page(s) 1: Table count or document order differs from LlamaParse. Owner: `GAP-TABLE-001` / `P04-US04`; test: `test_p04_us04_table_candidate_gate.py`.
- `FID-CATASTROPHE-RECAP-90328239f5ca` — **minor / acceptable_difference** — json, page(s) 1: Cross-envelope component decomposition or taxonomy differs on the page. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-CATASTROPHE-RECAP-5e608fa452b3` — **minor / acceptable_difference** — json, page(s) 1: Service JSON adds nested component relationships beyond LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-CATASTROPHE-RECAP-92eefd1ddf37` — **minor / harmless_formatting** — json, page(s) 1: Table 1 serialized field bytes differ while logical cells and spans match. Owner: `GAP-TABLE-003` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-CATASTROPHE-RECAP-5f99a4e4aa6c` — **critical / functional_regression** — json, page(s) 1: Page-associated JSON component content differs from LlamaParse. Owner: `GAP-TEXT-001` / `P02-US04`; test: `test_p02_us04_text_reconciliation.py`.
- `FID-CATASTROPHE-RECAP-3011a7123d6f` — **minor / review_required** — json, page(s) 1: Visual-origin text proxy differs and requires region-level review. Owner: `GAP-OCR-001` / `P02-US06`; test: `test_p02_us06_spatial_tokens.py`.
- `FID-CATASTROPHE-RECAP-0a564a0efa3a` — **critical / functional_regression** — json, page(s) 1: Image 1 labels, values, description, or caption differ. Owner: `GAP-VISUAL-001` / `P06-US05`; test: `test_p06_us05_grounding.py`.
- `FID-CATASTROPHE-RECAP-646d607b13e9` — **critical / functional_regression** — json, page(s) 1: Chart 1 labels, values, description, or caption differ. Owner: `GAP-CHART-002` / `P05-US04`; test: `test_p05_us04_vector_values.py`.
- `FID-CATASTROPHE-RECAP-33db90ad399b` — **critical / functional_regression** — rendered_dom, page(s) 1: Rendered Markdown visible semantic text differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-CATASTROPHE-RECAP-b63baf34d396` — **major / functional_regression** — rendered_dom, page(s) 1: Rendered semantic tag hierarchy or order differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.

### clean-energy

Status: **discrepancy_found**

| Physical page | Page status | JSON text recall | JSON text precision | Sequence ratio | Reference DOM | Service DOM | Findings |
|---:|---|---:|---:|---:|---|---|---:|
| 1 | discrepancy_found | 78.22% | 65.83% | 45.25% | yes | yes | 13 |

- `FID-CLEAN-ENERGY-a25fc869cc6c` — **critical / functional_regression** — markdown, page(s) 1: Raw Markdown has missing, added, replaced, duplicated, or reordered visible text. Owner: `GAP-TEXT-001` / `P02-US04`; test: `test_p02_us04_text_reconciliation.py`.
- `FID-CLEAN-ENERGY-badb29b17bae` — **minor / functional_regression** — markdown, page(s) 1: User-visible Markdown emphasis or code syntax differs. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-CLEAN-ENERGY-b496ac81f1d9` — **critical / functional_regression** — markdown, page(s) document: Table count or document order differs from LlamaParse. Owner: `GAP-TABLE-001` / `P04-US04`; test: `test_p04_us04_table_candidate_gate.py`.
- `FID-CLEAN-ENERGY-f02051dcd7ca` — **minor / acceptable_difference** — json, page(s) 1: Cross-envelope component decomposition or taxonomy differs on the page. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-CLEAN-ENERGY-adf5722c0cb5` — **minor / acceptable_difference** — json, page(s) 1: Cross-envelope nested component decomposition differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-CLEAN-ENERGY-5691fe365d59` — **critical / functional_regression** — json, page(s) 1: Page-associated JSON component content differs from LlamaParse. Owner: `GAP-TEXT-001` / `P02-US04`; test: `test_p02_us04_text_reconciliation.py`.
- `FID-CLEAN-ENERGY-22462cda391e` — **minor / review_required** — json, page(s) 1: Visual-origin text proxy differs and requires region-level review. Owner: `GAP-OCR-001` / `P02-US06`; test: `test_p02_us06_spatial_tokens.py`.
- `FID-CLEAN-ENERGY-5ffdf7968983` — **minor / acceptable_difference** — json, page(s) 1: Service emits additional image regions while retaining all LlamaParse image pages. Owner: `GAP-COVERAGE-001` / `P07-US02`; test: `test_p07_us02_image_parity.py plus M5 twins`.
- `FID-CLEAN-ENERGY-1dd707687608` — **critical / functional_regression** — json, page(s) 1: Chart 1 labels, values, description, or caption differ. Owner: `GAP-CHART-002` / `P05-US04`; test: `test_p05_us04_vector_values.py`.
- `FID-CLEAN-ENERGY-04877de9eb00` — **major / functional_regression** — json, page(s) 1: Chart 1 page-relative placement differs materially. Owner: `GAP-VISUAL-001` / `P06-US05`; test: `test_p06_us05_grounding.py`.
- `FID-CLEAN-ENERGY-a4bf5b2d7e80` — **critical / functional_regression** — rendered_dom, page(s) 1: Rendered Markdown visible semantic text differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-CLEAN-ENERGY-8bd7766a3082` — **major / functional_regression** — rendered_dom, page(s) 1: Rendered semantic tag hierarchy or order differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-CLEAN-ENERGY-d815b9200af3` — **major / functional_regression** — rendered_dom, page(s) 1: Rendered item grouping/type sequence differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-CLEAN-ENERGY-a96b3a93c183` — **critical / functional_regression** — rendered_dom, page(s) 1: Table count or document order differs from LlamaParse. Owner: `GAP-TABLE-001` / `P04-US04`; test: `test_p04_us04_table_candidate_gate.py`.

### clinical-study

Status: **discrepancy_found**

| Physical page | Page status | JSON text recall | JSON text precision | Sequence ratio | Reference DOM | Service DOM | Findings |
|---:|---|---:|---:|---:|---|---|---:|
| 1 | discrepancy_found | 94.62% | 92.30% | 93.28% | yes | yes | 15 |
| 2 | discrepancy_found | 95.03% | 95.03% | 93.17% | yes | yes | 14 |
| 3 | discrepancy_found | 0.00% | 0.00% | 0.00% | yes | yes | 13 |
| 4 | discrepancy_found | 89.25% | 95.75% | 91.51% | yes | yes | 14 |

- `FID-CLINICAL-STUDY-d8996c298736` — **critical / functional_regression** — markdown, page(s) 1, 2, 3, 4: Raw Markdown has missing, added, replaced, duplicated, or reordered visible text. Owner: `GAP-TEXT-001` / `P02-US04`; test: `test_p02_us04_text_reconciliation.py`.
- `FID-CLINICAL-STUDY-a23b7affb315` — **major / functional_regression** — markdown, page(s) 1: Heading text, level, or order differs from LlamaParse. Owner: `GAP-LIST-001` / `P03-US07`; test: `test_p03_us07_outline_structure.py`.
- `FID-CLINICAL-STUDY-79f515286213` — **major / functional_regression** — markdown, page(s) 1: List identity, nesting, text, or order differs. Owner: `GAP-LIST-001` / `P03-US07`; test: `test_p03_us07_outline_structure.py`.
- `FID-CLINICAL-STUDY-742092da3cc3` — **major / functional_regression** — markdown, page(s) 1, 2, 3, 4: Markdown links/images differ in text, target, or order. Owner: `GAP-LINK-001` / `P01-US01`; test: `test_p01_us01_ir_contract.py`.
- `FID-CLINICAL-STUDY-5747475fd94a` — **minor / functional_regression** — markdown, page(s) 1, 2, 3, 4: User-visible Markdown emphasis or code syntax differs. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-CLINICAL-STUDY-13190a09c84e` — **major / functional_regression** — markdown, page(s) 2: Table 1 differs in shape, spans, row order, or cell content. Owner: `GAP-TABLE-003` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-CLINICAL-STUDY-31e481be46c0` — **critical / functional_regression** — markdown, page(s) 4: Table 2 differs in shape, spans, row order, or cell content. Owner: `GAP-TABLE-003` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-CLINICAL-STUDY-9ddd2862fb70` — **minor / acceptable_difference** — json, page(s) 1: Cross-envelope component decomposition or taxonomy differs on the page. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-CLINICAL-STUDY-c1069e1251c5` — **minor / acceptable_difference** — json, page(s) 1: Cross-envelope nested component decomposition differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-CLINICAL-STUDY-60b6a2c3de36` — **minor / acceptable_difference** — json, page(s) 2: Cross-envelope component decomposition or taxonomy differs on the page. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-CLINICAL-STUDY-73565db5ec5e` — **minor / acceptable_difference** — json, page(s) 2: Cross-envelope nested component decomposition differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-CLINICAL-STUDY-17188a5f33d9` — **minor / acceptable_difference** — json, page(s) 3: Cross-envelope component decomposition or taxonomy differs on the page. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-CLINICAL-STUDY-d7112af9e2fd` — **minor / acceptable_difference** — json, page(s) 3: Cross-envelope nested component decomposition differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-CLINICAL-STUDY-7f8c81566609` — **minor / acceptable_difference** — json, page(s) 4: Cross-envelope component decomposition or taxonomy differs on the page. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-CLINICAL-STUDY-090e612f1adb` — **minor / acceptable_difference** — json, page(s) 4: Cross-envelope nested component decomposition differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-CLINICAL-STUDY-c5eaeee30f05` — **major / functional_regression** — json, page(s) 2: Table 1 differs in shape, spans, row order, or cell content. Owner: `GAP-TABLE-002` / `P04-US01`; test: `test_p04_us01_span_fidelity.py`.
- `FID-CLINICAL-STUDY-b96d2d42b26d` — **critical / functional_regression** — json, page(s) 4: Table 2 differs in shape, spans, row order, or cell content. Owner: `GAP-TABLE-002` / `P04-US01`; test: `test_p04_us01_span_fidelity.py`.
- `FID-CLINICAL-STUDY-d4be1e799219` — **major / functional_regression** — json, page(s) 1: Page-associated JSON component content differs from LlamaParse. Owner: `GAP-TEXT-001` / `P02-US04`; test: `test_p02_us04_text_reconciliation.py`.
- `FID-CLINICAL-STUDY-790d26732eda` — **major / functional_regression** — json, page(s) 2: Page-associated JSON component content differs from LlamaParse. Owner: `GAP-TEXT-001` / `P02-US04`; test: `test_p02_us04_text_reconciliation.py`.
- `FID-CLINICAL-STUDY-ee4024e9769e` — **critical / functional_regression** — json, page(s) 3: Page-associated JSON component content differs from LlamaParse. Owner: `GAP-TEXT-001` / `P02-US04`; test: `test_p02_us04_text_reconciliation.py`.
- `FID-CLINICAL-STUDY-6aa8820df6bf` — **critical / functional_regression** — json, page(s) 4: Page-associated JSON component content differs from LlamaParse. Owner: `GAP-TEXT-001` / `P02-US04`; test: `test_p02_us04_text_reconciliation.py`.
- `FID-CLINICAL-STUDY-bacaca948fc2` — **minor / review_required** — json, page(s) 1, 2, 3, 4: Visual-origin text proxy differs and requires region-level review. Owner: `GAP-OCR-001` / `P02-US06`; test: `test_p02_us06_spatial_tokens.py`.
- `FID-CLINICAL-STUDY-0cde0be990a6` — **major / functional_regression** — json, page(s) 1, 3: Image detection count or page placement differs from LlamaParse. Owner: `GAP-COVERAGE-001` / `P07-US02`; test: `test_p07_us02_image_parity.py plus M5 twins`.
- `FID-CLINICAL-STUDY-b0de0d1f7a7e` — **critical / functional_regression** — json, page(s) 1: Image 1 labels, values, description, or caption differ. Owner: `GAP-VISUAL-001` / `P06-US05`; test: `test_p06_us05_grounding.py`.
- `FID-CLINICAL-STUDY-e2b46f08c4ea` — **major / functional_regression** — json, page(s) 3: Diagram detection count or page placement differs from LlamaParse. Owner: `GAP-DIAGRAM-001` / `P05-US10`; test: `test_p05_us10_diagram_topology.py`.
- `FID-CLINICAL-STUDY-8a4b29672788` — **major / functional_regression** — rendered_dom, page(s) 1: Rendered Markdown visible semantic text differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-CLINICAL-STUDY-51485cfc3faf` — **major / functional_regression** — rendered_dom, page(s) 1: Rendered semantic tag hierarchy or order differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-CLINICAL-STUDY-79c6028fe819` — **major / functional_regression** — rendered_dom, page(s) 1: Rendered item grouping/type sequence differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-CLINICAL-STUDY-84b7ba216fb4` — **major / functional_regression** — rendered_dom, page(s) 1: Rendered links differ in text, target, or order. Owner: `GAP-LINK-001` / `P01-US01`; test: `test_p01_us01_ir_contract.py`.
- `FID-CLINICAL-STUDY-672aad52a1b3` — **major / functional_regression** — rendered_dom, page(s) 2: Rendered Markdown visible semantic text differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-CLINICAL-STUDY-d514d63ee486` — **major / functional_regression** — rendered_dom, page(s) 2: Rendered semantic tag hierarchy or order differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-CLINICAL-STUDY-0cec098a8ece` — **major / functional_regression** — rendered_dom, page(s) 2: Rendered item grouping/type sequence differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-CLINICAL-STUDY-93064d0a0c56` — **critical / functional_regression** — rendered_dom, page(s) 2: Table count or document order differs from LlamaParse. Owner: `GAP-TABLE-001` / `P04-US04`; test: `test_p04_us04_table_candidate_gate.py`.
- `FID-CLINICAL-STUDY-ba71855ba7cc` — **major / functional_regression** — rendered_dom, page(s) 2: Rendered links differ in text, target, or order. Owner: `GAP-LINK-001` / `P01-US01`; test: `test_p01_us01_ir_contract.py`.
- `FID-CLINICAL-STUDY-9c8f59577c20` — **critical / functional_regression** — rendered_dom, page(s) 3: Rendered Markdown visible semantic text differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-CLINICAL-STUDY-f3f9cc680411` — **major / functional_regression** — rendered_dom, page(s) 3: Rendered semantic tag hierarchy or order differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-CLINICAL-STUDY-4dcf6617afa6` — **major / functional_regression** — rendered_dom, page(s) 3: Rendered item grouping/type sequence differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-CLINICAL-STUDY-6d6dd1bf2bc4` — **major / functional_regression** — rendered_dom, page(s) 3: Rendered links differ in text, target, or order. Owner: `GAP-LINK-001` / `P01-US01`; test: `test_p01_us01_ir_contract.py`.
- `FID-CLINICAL-STUDY-681609fc153b` — **critical / functional_regression** — rendered_dom, page(s) 4: Rendered Markdown visible semantic text differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-CLINICAL-STUDY-7c674d5374d6` — **major / functional_regression** — rendered_dom, page(s) 4: Rendered semantic tag hierarchy or order differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-CLINICAL-STUDY-d5415b66577f` — **major / functional_regression** — rendered_dom, page(s) 4: Rendered item grouping/type sequence differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-CLINICAL-STUDY-6bfd8f0f8c82` — **critical / functional_regression** — rendered_dom, page(s) 4: Table count or document order differs from LlamaParse. Owner: `GAP-TABLE-001` / `P04-US04`; test: `test_p04_us04_table_candidate_gate.py`.
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
- `FID-COMPONENT-DATASHEET-ace33ec6550e` — **minor / acceptable_difference** — json, page(s) 2: Cross-envelope component decomposition or taxonomy differs on the page. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-COMPONENT-DATASHEET-267852c11299` — **minor / acceptable_difference** — json, page(s) 2: Cross-envelope nested component decomposition differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-COMPONENT-DATASHEET-524221a7ce16` — **minor / acceptable_difference** — json, page(s) 3: Cross-envelope component decomposition or taxonomy differs on the page. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-COMPONENT-DATASHEET-1c7b9c341bd3` — **critical / functional_regression** — json, page(s) 3: Table count or document order differs from LlamaParse. Owner: `GAP-TABLE-001` / `P04-US04`; test: `test_p04_us04_table_candidate_gate.py`.
- `FID-COMPONENT-DATASHEET-4ea057066a65` — **critical / functional_regression** — json, page(s) 1: Page-associated JSON component content differs from LlamaParse. Owner: `GAP-TEXT-001` / `P02-US04`; test: `test_p02_us04_text_reconciliation.py`.
- `FID-COMPONENT-DATASHEET-94aa27605fa9` — **critical / functional_regression** — json, page(s) 2: Page-associated JSON component content differs from LlamaParse. Owner: `GAP-TEXT-001` / `P02-US04`; test: `test_p02_us04_text_reconciliation.py`.
- `FID-COMPONENT-DATASHEET-ce528e20e330` — **critical / functional_regression** — json, page(s) 3: Page-associated JSON component content differs from LlamaParse. Owner: `GAP-TEXT-001` / `P02-US04`; test: `test_p02_us04_text_reconciliation.py`.
- `FID-COMPONENT-DATASHEET-b6f03e5fe68c` — **major / functional_regression** — json, page(s) 1, 2: Chart detection count or page placement differs from LlamaParse. Owner: `GAP-CHART-001` / `P05-US03`; test: `test_p05_us03_axes_legends.py`.
- `FID-COMPONENT-DATASHEET-93cd576de9b8` — **critical / functional_regression** — rendered_dom, page(s) 1: Rendered Markdown visible semantic text differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-COMPONENT-DATASHEET-e7d18163db42` — **major / functional_regression** — rendered_dom, page(s) 1: Rendered semantic tag hierarchy or order differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-COMPONENT-DATASHEET-102a3358541b` — **major / functional_regression** — rendered_dom, page(s) 1: Rendered item grouping/type sequence differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-COMPONENT-DATASHEET-47efbb0373a4` — **critical / functional_regression** — rendered_dom, page(s) 2: Rendered Markdown visible semantic text differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-COMPONENT-DATASHEET-052ae898f74a` — **major / functional_regression** — rendered_dom, page(s) 2: Rendered semantic tag hierarchy or order differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-COMPONENT-DATASHEET-821fecf0399a` — **major / functional_regression** — rendered_dom, page(s) 2: Rendered item grouping/type sequence differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-COMPONENT-DATASHEET-a81d678f5d40` — **critical / functional_regression** — rendered_dom, page(s) 3: Rendered Markdown visible semantic text differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-COMPONENT-DATASHEET-0c0ba6be64e3` — **major / functional_regression** — rendered_dom, page(s) 3: Rendered semantic tag hierarchy or order differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-COMPONENT-DATASHEET-f1400be710ed` — **major / functional_regression** — rendered_dom, page(s) 3: Rendered item grouping/type sequence differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-COMPONENT-DATASHEET-d3402849df11` — **critical / functional_regression** — rendered_dom, page(s) 3: Table count or document order differs from LlamaParse. Owner: `GAP-TABLE-001` / `P04-US04`; test: `test_p04_us04_table_candidate_gate.py`.

### egov-survey

Status: **discrepancy_found**

| Physical page | Page status | JSON text recall | JSON text precision | Sequence ratio | Reference DOM | Service DOM | Findings |
|---:|---|---:|---:|---:|---|---|---:|
| 1 | discrepancy_found | 93.02% | 93.02% | 85.83% | yes | yes | 12 |

- `FID-EGOV-SURVEY-e32df2f651e5` — **critical / functional_regression** — markdown, page(s) 1: Raw Markdown has missing, added, replaced, duplicated, or reordered visible text. Owner: `GAP-TEXT-001` / `P02-US04`; test: `test_p02_us04_text_reconciliation.py`.
- `FID-EGOV-SURVEY-c1208dd1ef86` — **minor / functional_regression** — markdown, page(s) 1: User-visible Markdown emphasis or code syntax differs. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-EGOV-SURVEY-e2a281c14b5b` — **critical / functional_regression** — markdown, page(s) document: Table count or document order differs from LlamaParse. Owner: `GAP-TABLE-001` / `P04-US04`; test: `test_p04_us04_table_candidate_gate.py`.
- `FID-EGOV-SURVEY-1d28bb6756d8` — **minor / acceptable_difference** — json, page(s) 1: Cross-envelope component decomposition or taxonomy differs on the page. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-EGOV-SURVEY-8e7c3d2389f0` — **minor / acceptable_difference** — json, page(s) 1: Service JSON adds nested component relationships beyond LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-EGOV-SURVEY-b51ebd6e50f5` — **critical / functional_regression** — json, page(s) 1: Page-associated JSON component content differs from LlamaParse. Owner: `GAP-TEXT-001` / `P02-US04`; test: `test_p02_us04_text_reconciliation.py`.
- `FID-EGOV-SURVEY-d947042a408e` — **minor / review_required** — json, page(s) 1: Visual-origin text proxy differs and requires region-level review. Owner: `GAP-OCR-001` / `P02-US06`; test: `test_p02_us06_spatial_tokens.py`.
- `FID-EGOV-SURVEY-644aa7483f2c` — **critical / functional_regression** — json, page(s) 1: Chart 1 labels, values, description, or caption differ. Owner: `GAP-CHART-002` / `P05-US04`; test: `test_p05_us04_vector_values.py`.
- `FID-EGOV-SURVEY-5c64eeecbbd0` — **major / functional_regression** — json, page(s) 1: Chart 1 page-relative placement differs materially. Owner: `GAP-VISUAL-001` / `P06-US05`; test: `test_p06_us05_grounding.py`.
- `FID-EGOV-SURVEY-29310ad3e9c8` — **critical / functional_regression** — rendered_dom, page(s) 1: Rendered Markdown visible semantic text differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-EGOV-SURVEY-c52fcd7dc5ad` — **major / functional_regression** — rendered_dom, page(s) 1: Rendered semantic tag hierarchy or order differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-EGOV-SURVEY-4dfa45f83225` — **major / functional_regression** — rendered_dom, page(s) 1: Rendered item grouping/type sequence differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-EGOV-SURVEY-4b63c69be7e7` — **critical / functional_regression** — rendered_dom, page(s) 1: Table count or document order differs from LlamaParse. Owner: `GAP-TABLE-001` / `P04-US04`; test: `test_p04_us04_table_candidate_gate.py`.

### esg-metrics

Status: **discrepancy_found**

| Physical page | Page status | JSON text recall | JSON text precision | Sequence ratio | Reference DOM | Service DOM | Findings |
|---:|---|---:|---:|---:|---|---|---:|
| 1 | discrepancy_found | 86.46% | 95.90% | 84.79% | yes | yes | 20 |

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
- `FID-ESG-METRICS-88f71a1597a6` — **major / functional_regression** — rendered_dom, page(s) 1: Rendered semantic tag hierarchy or order differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-ESG-METRICS-f277dedda186` — **major / functional_regression** — rendered_dom, page(s) 1: Rendered item grouping/type sequence differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-ESG-METRICS-385144139dce` — **critical / functional_regression** — rendered_dom, page(s) 1: Table count or document order differs from LlamaParse. Owner: `GAP-TABLE-001` / `P04-US04`; test: `test_p04_us04_table_candidate_gate.py`.
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
- `FID-FINANCE-10K-9d25f249dbec` — **major / functional_regression** — rendered_dom, page(s) 1: Rendered semantic tag hierarchy or order differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-FINANCE-10K-ad8231631425` — **major / functional_regression** — rendered_dom, page(s) 1: Rendered item grouping/type sequence differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-FINANCE-10K-d24c58427966` — **critical / functional_regression** — rendered_dom, page(s) 1: Table count or document order differs from LlamaParse. Owner: `GAP-TABLE-001` / `P04-US04`; test: `test_p04_us04_table_candidate_gate.py`.
- `FID-FINANCE-10K-2690a34a582b` — **major / functional_regression** — rendered_dom, page(s) 2: Rendered Markdown visible semantic text differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-FINANCE-10K-ba27dad6d158` — **major / functional_regression** — rendered_dom, page(s) 2: Rendered semantic tag hierarchy or order differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-FINANCE-10K-e827670afc62` — **major / functional_regression** — rendered_dom, page(s) 2: Rendered item grouping/type sequence differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-FINANCE-10K-19ecd8457d3e` — **critical / functional_regression** — rendered_dom, page(s) 2: Table count or document order differs from LlamaParse. Owner: `GAP-TABLE-001` / `P04-US04`; test: `test_p04_us04_table_candidate_gate.py`.
- `FID-FINANCE-10K-7b3a5d45f54c` — **major / functional_regression** — rendered_dom, page(s) 3: Rendered Markdown visible semantic text differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-FINANCE-10K-70c5a235c45f` — **major / functional_regression** — rendered_dom, page(s) 3: Rendered semantic tag hierarchy or order differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-FINANCE-10K-51bbfc76ec42` — **major / functional_regression** — rendered_dom, page(s) 3: Rendered item grouping/type sequence differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-FINANCE-10K-b53ae7f89cb3` — **critical / functional_regression** — rendered_dom, page(s) 3: Table count or document order differs from LlamaParse. Owner: `GAP-TABLE-001` / `P04-US04`; test: `test_p04_us04_table_candidate_gate.py`.

### health-report

Status: **discrepancy_found**

| Physical page | Page status | JSON text recall | JSON text precision | Sequence ratio | Reference DOM | Service DOM | Findings |
|---:|---|---:|---:|---:|---|---|---:|
| 1 | discrepancy_found | 49.10% | 70.26% | 49.65% | yes | yes | 15 |

- `FID-HEALTH-REPORT-3e3dc5d648ab` — **critical / functional_regression** — markdown, page(s) 1: Raw Markdown has missing, added, replaced, duplicated, or reordered visible text. Owner: `GAP-TEXT-001` / `P02-US04`; test: `test_p02_us04_text_reconciliation.py`.
- `FID-HEALTH-REPORT-c8a9e0f1d7af` — **major / functional_regression** — markdown, page(s) 1: Table count or document order differs from LlamaParse. Owner: `GAP-TABLE-001` / `P04-US04`; test: `test_p04_us04_table_candidate_gate.py`.
- `FID-HEALTH-REPORT-50738d3c2071` — **critical / functional_regression** — markdown, page(s) 1: Table 1 differs in shape, spans, row order, or cell content. Owner: `GAP-TABLE-003` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-HEALTH-REPORT-e3c98c23002d` — **minor / acceptable_difference** — json, page(s) 1: Cross-envelope component decomposition or taxonomy differs on the page. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-HEALTH-REPORT-ac4aaed7cc6a` — **minor / acceptable_difference** — json, page(s) 1: Service JSON adds nested component relationships beyond LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-HEALTH-REPORT-f9d09dc008b9` — **major / functional_regression** — json, page(s) 1: Table count or document order differs from LlamaParse. Owner: `GAP-TABLE-001` / `P04-US04`; test: `test_p04_us04_table_candidate_gate.py`.
- `FID-HEALTH-REPORT-c2712a220c6a` — **critical / functional_regression** — json, page(s) 1: Page-associated JSON component content differs from LlamaParse. Owner: `GAP-TEXT-001` / `P02-US04`; test: `test_p02_us04_text_reconciliation.py`.
- `FID-HEALTH-REPORT-9e7b81af7932` — **minor / review_required** — json, page(s) 1: Visual-origin text proxy differs and requires region-level review. Owner: `GAP-OCR-001` / `P02-US06`; test: `test_p02_us06_spatial_tokens.py`.
- `FID-HEALTH-REPORT-5e11534dd0a9` — **critical / functional_regression** — json, page(s) 1: Chart 1 labels, values, description, or caption differ. Owner: `GAP-CHART-002` / `P05-US04`; test: `test_p05_us04_vector_values.py`.
- `FID-HEALTH-REPORT-92872bc960ca` — **critical / functional_regression** — json, page(s) 1: Chart 2 labels, values, description, or caption differ. Owner: `GAP-CHART-002` / `P05-US04`; test: `test_p05_us04_vector_values.py`.
- `FID-HEALTH-REPORT-d6486ec2710f` — **critical / functional_regression** — rendered_dom, page(s) 1: Rendered Markdown visible semantic text differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-HEALTH-REPORT-c28a73598d52` — **major / functional_regression** — rendered_dom, page(s) 1: Rendered semantic tag hierarchy or order differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-HEALTH-REPORT-b3658968536e` — **major / functional_regression** — rendered_dom, page(s) 1: Rendered item grouping/type sequence differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-HEALTH-REPORT-670b47320be5` — **critical / functional_regression** — rendered_dom, page(s) 1: Table count or document order differs from LlamaParse. Owner: `GAP-TABLE-001` / `P04-US04`; test: `test_p04_us04_table_candidate_gate.py`.
- `FID-HEALTH-REPORT-027ffc0290d5` — **major / functional_regression** — rendered_dom, page(s) 1: Rendered links differ in text, target, or order. Owner: `GAP-LINK-001` / `P01-US01`; test: `test_p01_us01_ir_contract.py`.

### insurance-acord

Status: **discrepancy_found**

| Physical page | Page status | JSON text recall | JSON text precision | Sequence ratio | Reference DOM | Service DOM | Findings |
|---:|---|---:|---:|---:|---|---|---:|
| 1 | discrepancy_found | 99.54% | 75.13% | 77.36% | yes | yes | 18 |

- `FID-INSURANCE-ACORD-90bcff6e2f21` — **critical / functional_regression** — markdown, page(s) 1: Raw Markdown has missing, added, replaced, duplicated, or reordered visible text. Owner: `GAP-TEXT-001` / `P02-US04`; test: `test_p02_us04_text_reconciliation.py`.
- `FID-INSURANCE-ACORD-aa6422e37eef` — **major / functional_regression** — markdown, page(s) 1: Heading text, level, or order differs from LlamaParse. Owner: `GAP-LIST-001` / `P03-US07`; test: `test_p03_us07_outline_structure.py`.
- `FID-INSURANCE-ACORD-e804b92fa217` — **minor / functional_regression** — markdown, page(s) 1: User-visible Markdown emphasis or code syntax differs. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-INSURANCE-ACORD-fb77905ba8ce` — **major / functional_regression** — markdown, page(s) 1: Table count or document order differs from LlamaParse. Owner: `GAP-TABLE-001` / `P04-US04`; test: `test_p04_us04_table_candidate_gate.py`.
- `FID-INSURANCE-ACORD-3c0e132cd69f` — **critical / functional_regression** — markdown, page(s) 1: Table 1 differs in shape, spans, row order, or cell content. Owner: `GAP-TABLE-003` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-INSURANCE-ACORD-6ae2c85b2f75` — **critical / functional_regression** — markdown, page(s) 1: Table 2 differs in shape, spans, row order, or cell content. Owner: `GAP-TABLE-003` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-INSURANCE-ACORD-12eb40f5a125` — **minor / acceptable_difference** — json, page(s) 1: Cross-envelope component decomposition or taxonomy differs on the page. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-INSURANCE-ACORD-1389a3dd73e6` — **minor / acceptable_difference** — json, page(s) 1: Service JSON adds nested component relationships beyond LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-INSURANCE-ACORD-e08b0e6cb914` — **major / functional_regression** — json, page(s) 1: Table count or document order differs from LlamaParse. Owner: `GAP-TABLE-001` / `P04-US04`; test: `test_p04_us04_table_candidate_gate.py`.
- `FID-INSURANCE-ACORD-d88f24385488` — **critical / functional_regression** — json, page(s) 1: Table 1 differs in shape, spans, row order, or cell content. Owner: `GAP-TABLE-002` / `P04-US01`; test: `test_p04_us01_span_fidelity.py`.
- `FID-INSURANCE-ACORD-bd389889329c` — **critical / functional_regression** — json, page(s) 1: Table 2 differs in shape, spans, row order, or cell content. Owner: `GAP-TABLE-002` / `P04-US01`; test: `test_p04_us01_span_fidelity.py`.
- `FID-INSURANCE-ACORD-8655bb12ae1a` — **critical / functional_regression** — json, page(s) 1: Page-associated JSON component content differs from LlamaParse. Owner: `GAP-TEXT-001` / `P02-US04`; test: `test_p02_us04_text_reconciliation.py`.
- `FID-INSURANCE-ACORD-a8d9f7730332` — **minor / review_required** — json, page(s) 1: Visual-origin text proxy differs and requires region-level review. Owner: `GAP-OCR-001` / `P02-US06`; test: `test_p02_us06_spatial_tokens.py`.
- `FID-INSURANCE-ACORD-6f9f3c509d2a` — **critical / functional_regression** — json, page(s) 1: Image 1 labels, values, description, or caption differ. Owner: `GAP-VISUAL-001` / `P06-US05`; test: `test_p06_us05_grounding.py`.
- `FID-INSURANCE-ACORD-b4ce8ec30820` — **critical / functional_regression** — rendered_dom, page(s) 1: Rendered Markdown visible semantic text differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-INSURANCE-ACORD-2946c9fb1a37` — **major / functional_regression** — rendered_dom, page(s) 1: Rendered semantic tag hierarchy or order differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-INSURANCE-ACORD-32f2f40bc53d` — **major / functional_regression** — rendered_dom, page(s) 1: Rendered item grouping/type sequence differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-INSURANCE-ACORD-2911357e84e9` — **critical / functional_regression** — rendered_dom, page(s) 1: Table count or document order differs from LlamaParse. Owner: `GAP-TABLE-001` / `P04-US04`; test: `test_p04_us04_table_candidate_gate.py`.

### manufacturing-report

Status: **discrepancy_found**

| Physical page | Page status | JSON text recall | JSON text precision | Sequence ratio | Reference DOM | Service DOM | Findings |
|---:|---|---:|---:|---:|---|---|---:|
| 1 | discrepancy_found | 76.06% | 73.97% | 58.33% | yes | yes | 18 |
| 2 | discrepancy_found | 41.39% | 56.57% | 23.51% | yes | yes | 17 |
| 3 | discrepancy_found | 63.20% | 93.29% | 70.19% | yes | yes | 19 |

- `FID-MANUFACTURING-REPORT-66a65bd84f5f` — **critical / functional_regression** — markdown, page(s) 1, 2, 3: Raw Markdown has missing, added, replaced, duplicated, or reordered visible text. Owner: `GAP-TEXT-001` / `P02-US04`; test: `test_p02_us04_text_reconciliation.py`.
- `FID-MANUFACTURING-REPORT-fd7127656271` — **major / functional_regression** — markdown, page(s) 3: Heading text, level, or order differs from LlamaParse. Owner: `GAP-LIST-001` / `P03-US07`; test: `test_p03_us07_outline_structure.py`.
- `FID-MANUFACTURING-REPORT-49318df3a14b` — **minor / functional_regression** — markdown, page(s) 1, 2, 3: User-visible Markdown emphasis or code syntax differs. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-MANUFACTURING-REPORT-55bf0e0b88f6` — **critical / functional_regression** — markdown, page(s) 3: Table count or document order differs from LlamaParse. Owner: `GAP-TABLE-001` / `P04-US04`; test: `test_p04_us04_table_candidate_gate.py`.
- `FID-MANUFACTURING-REPORT-da7ea3df1497` — **minor / acceptable_difference** — json, page(s) 1: Cross-envelope component decomposition or taxonomy differs on the page. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-MANUFACTURING-REPORT-307d545fb03e` — **minor / acceptable_difference** — json, page(s) 1: Service JSON adds nested component relationships beyond LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-MANUFACTURING-REPORT-aab6f7e9006e` — **minor / acceptable_difference** — json, page(s) 2: Cross-envelope component decomposition or taxonomy differs on the page. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-MANUFACTURING-REPORT-e57cf73e7c68` — **minor / acceptable_difference** — json, page(s) 2: Cross-envelope nested component decomposition differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-MANUFACTURING-REPORT-881b4a19908b` — **minor / acceptable_difference** — json, page(s) 3: Cross-envelope component decomposition or taxonomy differs on the page. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-MANUFACTURING-REPORT-b2b296335808` — **minor / acceptable_difference** — json, page(s) 3: Cross-envelope nested component decomposition differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-MANUFACTURING-REPORT-9f550f1d6a00` — **critical / functional_regression** — json, page(s) 3: Table count or document order differs from LlamaParse. Owner: `GAP-TABLE-001` / `P04-US04`; test: `test_p04_us04_table_candidate_gate.py`.
- `FID-MANUFACTURING-REPORT-b9e7fe4e5c1d` — **critical / functional_regression** — json, page(s) 1: Page-associated JSON component content differs from LlamaParse. Owner: `GAP-TEXT-001` / `P02-US04`; test: `test_p02_us04_text_reconciliation.py`.
- `FID-MANUFACTURING-REPORT-fc69fd8d13b8` — **critical / functional_regression** — json, page(s) 2: Page-associated JSON component content differs from LlamaParse. Owner: `GAP-TEXT-001` / `P02-US04`; test: `test_p02_us04_text_reconciliation.py`.
- `FID-MANUFACTURING-REPORT-713d86884454` — **critical / functional_regression** — json, page(s) 3: Page-associated JSON component content differs from LlamaParse. Owner: `GAP-TEXT-001` / `P02-US04`; test: `test_p02_us04_text_reconciliation.py`.
- `FID-MANUFACTURING-REPORT-21816bd23dd1` — **minor / review_required** — json, page(s) 1, 2, 3: Visual-origin text proxy differs and requires region-level review. Owner: `GAP-OCR-001` / `P02-US06`; test: `test_p02_us06_spatial_tokens.py`.
- `FID-MANUFACTURING-REPORT-7f967af04d03` — **minor / acceptable_difference** — json, page(s) 3: Service emits additional image regions while retaining all LlamaParse image pages. Owner: `GAP-COVERAGE-001` / `P07-US02`; test: `test_p07_us02_image_parity.py plus M5 twins`.
- `FID-MANUFACTURING-REPORT-e82bef46ac63` — **major / functional_regression** — json, page(s) 1, 2, 3: Chart detection count or page placement differs from LlamaParse. Owner: `GAP-CHART-001` / `P05-US03`; test: `test_p05_us03_axes_legends.py`.
- `FID-MANUFACTURING-REPORT-3a3c96aa810f` — **critical / functional_regression** — json, page(s) 1: Chart 1 labels, values, description, or caption differ. Owner: `GAP-CHART-002` / `P05-US04`; test: `test_p05_us04_vector_values.py`.
- `FID-MANUFACTURING-REPORT-3f543c51c865` — **major / functional_regression** — json, page(s) 1: Chart 1 associated caption text or ordering differs. Owner: `GAP-VISUAL-001` / `P06-US05`; test: `test_p06_us05_grounding.py`.
- `FID-MANUFACTURING-REPORT-2a8782805000` — **major / functional_regression** — json, page(s) 1: Chart 1 page-relative placement differs materially. Owner: `GAP-VISUAL-001` / `P06-US05`; test: `test_p06_us05_grounding.py`.
- `FID-MANUFACTURING-REPORT-09e82db04d52` — **critical / functional_regression** — json, page(s) 1: Chart 2 labels, values, description, or caption differ. Owner: `GAP-CHART-002` / `P05-US04`; test: `test_p05_us04_vector_values.py`.
- `FID-MANUFACTURING-REPORT-4c6b880d88ee` — **major / functional_regression** — json, page(s) 1: Chart 2 associated caption text or ordering differs. Owner: `GAP-VISUAL-001` / `P06-US05`; test: `test_p06_us05_grounding.py`.
- `FID-MANUFACTURING-REPORT-84fb28d145a6` — **major / functional_regression** — json, page(s) 1: Chart 2 page-relative placement differs materially. Owner: `GAP-VISUAL-001` / `P06-US05`; test: `test_p06_us05_grounding.py`.
- `FID-MANUFACTURING-REPORT-08cd70a2ecab` — **critical / functional_regression** — json, page(s) 2: Chart 3 labels, values, description, or caption differ. Owner: `GAP-CHART-002` / `P05-US04`; test: `test_p05_us04_vector_values.py`.
- `FID-MANUFACTURING-REPORT-4c2d359dd006` — **major / functional_regression** — json, page(s) 2: Chart 3 associated caption text or ordering differs. Owner: `GAP-VISUAL-001` / `P06-US05`; test: `test_p06_us05_grounding.py`.
- `FID-MANUFACTURING-REPORT-da8fcb5bbc79` — **critical / functional_regression** — json, page(s) 2: Chart 4 labels, values, description, or caption differ. Owner: `GAP-CHART-002` / `P05-US04`; test: `test_p05_us04_vector_values.py`.
- `FID-MANUFACTURING-REPORT-e081b61b07b6` — **major / functional_regression** — json, page(s) 2: Chart 4 associated caption text or ordering differs. Owner: `GAP-VISUAL-001` / `P06-US05`; test: `test_p06_us05_grounding.py`.
- `FID-MANUFACTURING-REPORT-ffc9b397adc5` — **major / functional_regression** — json, page(s) 2: Chart 4 page-relative placement differs materially. Owner: `GAP-VISUAL-001` / `P06-US05`; test: `test_p06_us05_grounding.py`.
- `FID-MANUFACTURING-REPORT-4df2a9aa0d4a` — **critical / functional_regression** — json, page(s) 3: Chart 5 labels, values, description, or caption differ. Owner: `GAP-CHART-002` / `P05-US04`; test: `test_p05_us04_vector_values.py`.
- `FID-MANUFACTURING-REPORT-b854cde4250a` — **major / functional_regression** — json, page(s) 3: Chart 5 associated caption text or ordering differs. Owner: `GAP-VISUAL-001` / `P06-US05`; test: `test_p06_us05_grounding.py`.
- `FID-MANUFACTURING-REPORT-5af954fae854` — **major / functional_regression** — json, page(s) 3: Chart 5 page-relative placement differs materially. Owner: `GAP-VISUAL-001` / `P06-US05`; test: `test_p06_us05_grounding.py`.
- `FID-MANUFACTURING-REPORT-718493a864b6` — **critical / functional_regression** — rendered_dom, page(s) 1: Rendered Markdown visible semantic text differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-MANUFACTURING-REPORT-b98ac22785a2` — **major / functional_regression** — rendered_dom, page(s) 1: Rendered semantic tag hierarchy or order differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-MANUFACTURING-REPORT-6d429e973b5c` — **major / functional_regression** — rendered_dom, page(s) 1: Rendered item grouping/type sequence differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-MANUFACTURING-REPORT-e605ae4622e4` — **critical / functional_regression** — rendered_dom, page(s) 1: Table count or document order differs from LlamaParse. Owner: `GAP-TABLE-001` / `P04-US04`; test: `test_p04_us04_table_candidate_gate.py`.
- `FID-MANUFACTURING-REPORT-994215ffdc38` — **major / functional_regression** — rendered_dom, page(s) 1: Rendered links differ in text, target, or order. Owner: `GAP-LINK-001` / `P01-US01`; test: `test_p01_us01_ir_contract.py`.
- `FID-MANUFACTURING-REPORT-0bc74aefd254` — **critical / functional_regression** — rendered_dom, page(s) 2: Rendered Markdown visible semantic text differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-MANUFACTURING-REPORT-39a83f041dca` — **major / functional_regression** — rendered_dom, page(s) 2: Rendered semantic tag hierarchy or order differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-MANUFACTURING-REPORT-0754101cbfc2` — **major / functional_regression** — rendered_dom, page(s) 2: Rendered item grouping/type sequence differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-MANUFACTURING-REPORT-a568fba898d7` — **critical / functional_regression** — rendered_dom, page(s) 2: Table count or document order differs from LlamaParse. Owner: `GAP-TABLE-001` / `P04-US04`; test: `test_p04_us04_table_candidate_gate.py`.
- `FID-MANUFACTURING-REPORT-cf539820227b` — **major / functional_regression** — rendered_dom, page(s) 2: Rendered links differ in text, target, or order. Owner: `GAP-LINK-001` / `P01-US01`; test: `test_p01_us01_ir_contract.py`.
- `FID-MANUFACTURING-REPORT-c5a41babf631` — **critical / functional_regression** — rendered_dom, page(s) 3: Rendered Markdown visible semantic text differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-MANUFACTURING-REPORT-9a6a194ba32b` — **major / functional_regression** — rendered_dom, page(s) 3: Rendered semantic tag hierarchy or order differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-MANUFACTURING-REPORT-1a8d4b2a7cdf` — **major / functional_regression** — rendered_dom, page(s) 3: Rendered item grouping/type sequence differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-MANUFACTURING-REPORT-7fa56b19b209` — **critical / functional_regression** — rendered_dom, page(s) 3: Table count or document order differs from LlamaParse. Owner: `GAP-TABLE-001` / `P04-US04`; test: `test_p04_us04_table_candidate_gate.py`.
- `FID-MANUFACTURING-REPORT-24c3db60c9bf` — **major / functional_regression** — rendered_dom, page(s) 3: Rendered links differ in text, target, or order. Owner: `GAP-LINK-001` / `P01-US01`; test: `test_p01_us01_ir_contract.py`.

### ny-timetable

Status: **discrepancy_found**

| Physical page | Page status | JSON text recall | JSON text precision | Sequence ratio | Reference DOM | Service DOM | Findings |
|---:|---|---:|---:|---:|---|---|---:|
| 1 | discrepancy_found | 100.00% | 99.51% | 64.88% | yes | yes | 11 |
| 2 | discrepancy_found | 99.92% | 99.27% | 11.60% | yes | yes | 10 |
| 3 | discrepancy_found | 100.00% | 99.36% | 25.73% | yes | yes | 10 |

- `FID-NY-TIMETABLE-0af5062b42dc` — **critical / functional_regression** — markdown, page(s) 1, 2, 3: Raw Markdown has missing, added, replaced, duplicated, or reordered visible text. Owner: `GAP-TEXT-001` / `P02-US04`; test: `test_p02_us04_text_reconciliation.py`.
- `FID-NY-TIMETABLE-5864f57b266a` — **major / functional_regression** — markdown, page(s) 1: Heading text, level, or order differs from LlamaParse. Owner: `GAP-LIST-001` / `P03-US07`; test: `test_p03_us07_outline_structure.py`.
- `FID-NY-TIMETABLE-57118eda4864` — **minor / functional_regression** — markdown, page(s) 1: User-visible Markdown emphasis or code syntax differs. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-NY-TIMETABLE-c5435a6e7add` — **critical / functional_regression** — markdown, page(s) 1: Table 1 differs in shape, spans, row order, or cell content. Owner: `GAP-TABLE-003` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-NY-TIMETABLE-67c13cb437f5` — **critical / functional_regression** — markdown, page(s) 2: Table 2 differs in shape, spans, row order, or cell content. Owner: `GAP-TABLE-003` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-NY-TIMETABLE-761046d9d0f6` — **critical / functional_regression** — markdown, page(s) 3: Table 3 differs in shape, spans, row order, or cell content. Owner: `GAP-TABLE-003` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-NY-TIMETABLE-dde08ef30da1` — **minor / acceptable_difference** — json, page(s) 1: Cross-envelope component decomposition or taxonomy differs on the page. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-NY-TIMETABLE-5a6044a5ef52` — **minor / acceptable_difference** — json, page(s) 2: Cross-envelope component decomposition or taxonomy differs on the page. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-NY-TIMETABLE-3f2bed50ee27` — **minor / acceptable_difference** — json, page(s) 2: Cross-envelope nested component decomposition differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-NY-TIMETABLE-603687bed8bf` — **minor / acceptable_difference** — json, page(s) 3: Cross-envelope component decomposition or taxonomy differs on the page. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-NY-TIMETABLE-42e8a9347b49` — **minor / acceptable_difference** — json, page(s) 3: Cross-envelope nested component decomposition differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-NY-TIMETABLE-71095b4254d1` — **critical / functional_regression** — json, page(s) 1: Table 1 differs in shape, spans, row order, or cell content. Owner: `GAP-TABLE-002` / `P04-US01`; test: `test_p04_us01_span_fidelity.py`.
- `FID-NY-TIMETABLE-62cfdfcb4994` — **critical / functional_regression** — json, page(s) 2: Table 2 differs in shape, spans, row order, or cell content. Owner: `GAP-TABLE-002` / `P04-US01`; test: `test_p04_us01_span_fidelity.py`.
- `FID-NY-TIMETABLE-74c2f9db13c9` — **critical / functional_regression** — json, page(s) 3: Table 3 differs in shape, spans, row order, or cell content. Owner: `GAP-TABLE-002` / `P04-US01`; test: `test_p04_us01_span_fidelity.py`.
- `FID-NY-TIMETABLE-acc0fc9bb3f1` — **critical / functional_regression** — json, page(s) 1: Page-associated JSON component content differs from LlamaParse. Owner: `GAP-TEXT-001` / `P02-US04`; test: `test_p02_us04_text_reconciliation.py`.
- `FID-NY-TIMETABLE-c79e4c29c184` — **critical / functional_regression** — json, page(s) 2: Page-associated JSON component content differs from LlamaParse. Owner: `GAP-TEXT-001` / `P02-US04`; test: `test_p02_us04_text_reconciliation.py`.
- `FID-NY-TIMETABLE-c0de2c7e9038` — **critical / functional_regression** — json, page(s) 3: Page-associated JSON component content differs from LlamaParse. Owner: `GAP-TEXT-001` / `P02-US04`; test: `test_p02_us04_text_reconciliation.py`.
- `FID-NY-TIMETABLE-0de1ae8b8996` — **critical / functional_regression** — rendered_dom, page(s) 1: Rendered Markdown visible semantic text differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-NY-TIMETABLE-43ff44487ac7` — **major / functional_regression** — rendered_dom, page(s) 1: Rendered semantic tag hierarchy or order differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-NY-TIMETABLE-4018f5bd7566` — **major / functional_regression** — rendered_dom, page(s) 1: Rendered item grouping/type sequence differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-NY-TIMETABLE-01ee2944e0b4` — **critical / functional_regression** — rendered_dom, page(s) 1: Table count or document order differs from LlamaParse. Owner: `GAP-TABLE-001` / `P04-US04`; test: `test_p04_us04_table_candidate_gate.py`.
- `FID-NY-TIMETABLE-acee8ecb5a94` — **critical / functional_regression** — rendered_dom, page(s) 2: Rendered Markdown visible semantic text differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-NY-TIMETABLE-9a6f2e8ffa68` — **major / functional_regression** — rendered_dom, page(s) 2: Rendered semantic tag hierarchy or order differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-NY-TIMETABLE-8db2262ad7f1` — **major / functional_regression** — rendered_dom, page(s) 2: Rendered item grouping/type sequence differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-NY-TIMETABLE-6b5f23e3300e` — **critical / functional_regression** — rendered_dom, page(s) 2: Table count or document order differs from LlamaParse. Owner: `GAP-TABLE-001` / `P04-US04`; test: `test_p04_us04_table_candidate_gate.py`.
- `FID-NY-TIMETABLE-0d00803c928f` — **critical / functional_regression** — rendered_dom, page(s) 3: Rendered Markdown visible semantic text differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-NY-TIMETABLE-83c73416b297` — **major / functional_regression** — rendered_dom, page(s) 3: Rendered semantic tag hierarchy or order differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-NY-TIMETABLE-84f853a1adea` — **major / functional_regression** — rendered_dom, page(s) 3: Rendered item grouping/type sequence differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-NY-TIMETABLE-098668095048` — **critical / functional_regression** — rendered_dom, page(s) 3: Table count or document order differs from LlamaParse. Owner: `GAP-TABLE-001` / `P04-US04`; test: `test_p04_us04_table_candidate_gate.py`.

### postal-10k

Status: **discrepancy_found**

| Physical page | Page status | JSON text recall | JSON text precision | Sequence ratio | Reference DOM | Service DOM | Findings |
|---:|---|---:|---:|---:|---|---|---:|
| 1 | discrepancy_found | 100.00% | 95.55% | 97.72% | yes | yes | 7 |
| 2 | discrepancy_found | 96.90% | 91.91% | 94.34% | yes | yes | 8 |
| 3 | discrepancy_found | 100.00% | 96.81% | 98.38% | yes | yes | 9 |

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
- `FID-POSTAL-10K-26fa0e7f7754` — **major / functional_regression** — rendered_dom, page(s) 1: Rendered semantic tag hierarchy or order differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-POSTAL-10K-a4f0c1c8abc9` — **critical / functional_regression** — rendered_dom, page(s) 2: Rendered Markdown visible semantic text differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-POSTAL-10K-a0de04ff8938` — **major / functional_regression** — rendered_dom, page(s) 2: Rendered semantic tag hierarchy or order differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-POSTAL-10K-b1bcd9dc74ca` — **critical / functional_regression** — rendered_dom, page(s) 3: Rendered Markdown visible semantic text differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-POSTAL-10K-78b7c8606b84` — **major / functional_regression** — rendered_dom, page(s) 3: Rendered semantic tag hierarchy or order differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.

### purchase-agreement

Status: **discrepancy_found**

| Physical page | Page status | JSON text recall | JSON text precision | Sequence ratio | Reference DOM | Service DOM | Findings |
|---:|---|---:|---:|---:|---|---|---:|
| 1 | discrepancy_found | 100.00% | 99.80% | 99.90% | yes | yes | 8 |

- `FID-PURCHASE-AGREEMENT-a1f09047bf65` — **minor / functional_regression** — markdown, page(s) 1: Raw Markdown has missing, added, replaced, duplicated, or reordered visible text. Owner: `GAP-TEXT-001` / `P02-US04`; test: `test_p02_us04_text_reconciliation.py`.
- `FID-PURCHASE-AGREEMENT-e15feb985a62` — **major / functional_regression** — markdown, page(s) 1: Heading text, level, or order differs from LlamaParse. Owner: `GAP-LIST-001` / `P03-US07`; test: `test_p03_us07_outline_structure.py`.
- `FID-PURCHASE-AGREEMENT-98cde2c4c8c7` — **minor / functional_regression** — markdown, page(s) 1: User-visible Markdown emphasis or code syntax differs. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-PURCHASE-AGREEMENT-8f9ef5431725` — **minor / acceptable_difference** — json, page(s) 1: Cross-envelope component decomposition or taxonomy differs on the page. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-PURCHASE-AGREEMENT-9d1e53a4ccf9` — **minor / functional_regression** — json, page(s) 1: Page-associated JSON component content differs from LlamaParse. Owner: `GAP-TEXT-001` / `P02-US04`; test: `test_p02_us04_text_reconciliation.py`.
- `FID-PURCHASE-AGREEMENT-e906938c16e7` — **minor / functional_regression** — rendered_dom, page(s) 1: Rendered Markdown visible semantic text differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-PURCHASE-AGREEMENT-9b27b026cdd6` — **major / functional_regression** — rendered_dom, page(s) 1: Rendered semantic tag hierarchy or order differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-PURCHASE-AGREEMENT-bad28358b003` — **major / functional_regression** — rendered_dom, page(s) 1: Rendered item grouping/type sequence differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.

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
- `FID-SETTLEMENT-AGREEMENT-1bce01f7564d` — **major / functional_regression** — rendered_dom, page(s) 1: Rendered semantic tag hierarchy or order differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-SETTLEMENT-AGREEMENT-c98326ce0047` — **major / functional_regression** — rendered_dom, page(s) 1: Rendered item grouping/type sequence differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-SETTLEMENT-AGREEMENT-c9746d2debfd` — **critical / functional_regression** — rendered_dom, page(s) 1: Table count or document order differs from LlamaParse. Owner: `GAP-TABLE-001` / `P04-US04`; test: `test_p04_us04_table_candidate_gate.py`.

### uber-earnings

Status: **discrepancy_found**

| Physical page | Page status | JSON text recall | JSON text precision | Sequence ratio | Reference DOM | Service DOM | Findings |
|---:|---|---:|---:|---:|---|---|---:|
| 1 | discrepancy_found | 54.55% | 40.00% | 38.46% | yes | yes | 12 |
| 2 | discrepancy_found | 69.50% | 79.67% | 55.30% | yes | yes | 20 |
| 3 | discrepancy_found | 48.86% | 87.76% | 54.01% | yes | yes | 12 |

- `FID-UBER-EARNINGS-b4b2e87b7116` — **critical / functional_regression** — markdown, page(s) 1, 2, 3: Raw Markdown has missing, added, replaced, duplicated, or reordered visible text. Owner: `GAP-TEXT-001` / `P02-US04`; test: `test_p02_us04_text_reconciliation.py`.
- `FID-UBER-EARNINGS-5069f8dc411f` — **major / functional_regression** — markdown, page(s) 1, 2, 3: Heading text, level, or order differs from LlamaParse. Owner: `GAP-LIST-001` / `P03-US07`; test: `test_p03_us07_outline_structure.py`.
- `FID-UBER-EARNINGS-9c4cd53cfb88` — **minor / functional_regression** — markdown, page(s) 1, 2, 3: User-visible Markdown emphasis or code syntax differs. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-UBER-EARNINGS-2910210ba8c9` — **critical / functional_regression** — markdown, page(s) document: Table count or document order differs from LlamaParse. Owner: `GAP-TABLE-001` / `P04-US04`; test: `test_p04_us04_table_candidate_gate.py`.
- `FID-UBER-EARNINGS-fe9f0a58649e` — **minor / acceptable_difference** — json, page(s) 1: Cross-envelope component decomposition or taxonomy differs on the page. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-UBER-EARNINGS-7d25fd2388e9` — **minor / acceptable_difference** — json, page(s) 1: Service JSON adds nested component relationships beyond LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-UBER-EARNINGS-7bd5d8956583` — **minor / acceptable_difference** — json, page(s) 2: Cross-envelope component decomposition or taxonomy differs on the page. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-UBER-EARNINGS-fcb7ac70f875` — **minor / acceptable_difference** — json, page(s) 2: Service JSON adds nested component relationships beyond LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-UBER-EARNINGS-606c50e4045d` — **minor / acceptable_difference** — json, page(s) 3: Cross-envelope component decomposition or taxonomy differs on the page. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-UBER-EARNINGS-b97e58332eb5` — **minor / acceptable_difference** — json, page(s) 3: Service JSON adds nested component relationships beyond LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-UBER-EARNINGS-4d51ed9b82ae` — **critical / functional_regression** — json, page(s) 1: Page-associated JSON component content differs from LlamaParse. Owner: `GAP-TEXT-001` / `P02-US04`; test: `test_p02_us04_text_reconciliation.py`.
- `FID-UBER-EARNINGS-8fa01c9a1fba` — **critical / functional_regression** — json, page(s) 2: Page-associated JSON component content differs from LlamaParse. Owner: `GAP-TEXT-001` / `P02-US04`; test: `test_p02_us04_text_reconciliation.py`.
- `FID-UBER-EARNINGS-a9f1a25340a2` — **critical / functional_regression** — json, page(s) 3: Page-associated JSON component content differs from LlamaParse. Owner: `GAP-TEXT-001` / `P02-US04`; test: `test_p02_us04_text_reconciliation.py`.
- `FID-UBER-EARNINGS-66a8a6be02e9` — **minor / review_required** — json, page(s) 1, 2, 3: Visual-origin text proxy differs and requires region-level review. Owner: `GAP-OCR-001` / `P02-US06`; test: `test_p02_us06_spatial_tokens.py`.
- `FID-UBER-EARNINGS-59bfd52367e1` — **major / functional_regression** — json, page(s) 1, 2, 3: Image detection count or page placement differs from LlamaParse. Owner: `GAP-COVERAGE-001` / `P07-US02`; test: `test_p07_us02_image_parity.py plus M5 twins`.
- `FID-UBER-EARNINGS-43d1b150e675` — **critical / functional_regression** — json, page(s) 1: Image 1 labels, values, description, or caption differ. Owner: `GAP-VISUAL-001` / `P06-US05`; test: `test_p06_us05_grounding.py`.
- `FID-UBER-EARNINGS-bc1d3c49768c` — **critical / functional_regression** — json, page(s) 2: Image 2 labels, values, description, or caption differ. Owner: `GAP-VISUAL-001` / `P06-US05`; test: `test_p06_us05_grounding.py`.
- `FID-UBER-EARNINGS-c7d70a2591c2` — **major / functional_regression** — json, page(s) 2: Image 3 page-relative placement differs materially. Owner: `GAP-VISUAL-001` / `P06-US05`; test: `test_p06_us05_grounding.py`.
- `FID-UBER-EARNINGS-b1072eb8825e` — **major / functional_regression** — json, page(s) 2: Image 4 page-relative placement differs materially. Owner: `GAP-VISUAL-001` / `P06-US05`; test: `test_p06_us05_grounding.py`.
- `FID-UBER-EARNINGS-5455160589dd` — **major / functional_regression** — json, page(s) 2, 3: Chart detection count or page placement differs from LlamaParse. Owner: `GAP-CHART-001` / `P05-US03`; test: `test_p05_us03_axes_legends.py`.
- `FID-UBER-EARNINGS-7dfaaa2c365c` — **critical / functional_regression** — json, page(s) 2: Chart 1 labels, values, description, or caption differ. Owner: `GAP-CHART-002` / `P05-US04`; test: `test_p05_us04_vector_values.py`.
- `FID-UBER-EARNINGS-238f16d0cef0` — **major / functional_regression** — json, page(s) 2: Chart 1 page-relative placement differs materially. Owner: `GAP-VISUAL-001` / `P06-US05`; test: `test_p06_us05_grounding.py`.
- `FID-UBER-EARNINGS-101ca7fe396e` — **critical / functional_regression** — json, page(s) 2: Chart 2 labels, values, description, or caption differ. Owner: `GAP-CHART-002` / `P05-US04`; test: `test_p05_us04_vector_values.py`.
- `FID-UBER-EARNINGS-3fbf95e45ffa` — **major / functional_regression** — json, page(s) 2: Chart 2 page-relative placement differs materially. Owner: `GAP-VISUAL-001` / `P06-US05`; test: `test_p06_us05_grounding.py`.
- `FID-UBER-EARNINGS-19dd17491522` — **critical / functional_regression** — rendered_dom, page(s) 1: Rendered Markdown visible semantic text differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-UBER-EARNINGS-29911a30bfa9` — **major / functional_regression** — rendered_dom, page(s) 1: Rendered semantic tag hierarchy or order differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-UBER-EARNINGS-072927293c64` — **major / functional_regression** — rendered_dom, page(s) 1: Rendered item grouping/type sequence differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-UBER-EARNINGS-7534d96fb2b1` — **critical / functional_regression** — rendered_dom, page(s) 2: Rendered Markdown visible semantic text differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-UBER-EARNINGS-c23ecff11065` — **major / functional_regression** — rendered_dom, page(s) 2: Rendered semantic tag hierarchy or order differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-UBER-EARNINGS-ede85e375c6f` — **major / functional_regression** — rendered_dom, page(s) 2: Rendered item grouping/type sequence differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-UBER-EARNINGS-7095abff6384` — **critical / functional_regression** — rendered_dom, page(s) 2: Table count or document order differs from LlamaParse. Owner: `GAP-TABLE-001` / `P04-US04`; test: `test_p04_us04_table_candidate_gate.py`.
- `FID-UBER-EARNINGS-6e8c020d2dff` — **critical / functional_regression** — rendered_dom, page(s) 3: Rendered Markdown visible semantic text differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-UBER-EARNINGS-ad3aba46cc92` — **major / functional_regression** — rendered_dom, page(s) 3: Rendered semantic tag hierarchy or order differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-UBER-EARNINGS-e6cf9d223a06` — **major / functional_regression** — rendered_dom, page(s) 3: Rendered item grouping/type sequence differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.

## Comparison policy and limitations

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
