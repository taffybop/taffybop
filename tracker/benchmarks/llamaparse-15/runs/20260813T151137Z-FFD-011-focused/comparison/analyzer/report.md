# LlamaParse-15 functional-fidelity comparison

Run: `20260813T151137Z-FFD-011-focused`  
Candidate artifacts: `service`  
Analyzer schema: `functional-fidelity-comparison-v1`  
Story mapping: `tracker/benchmarks/llamaparse-15/gap-to-story-matrix.md`
Reference selection: `default llamaparse batch`

This is a functionality/output-quality comparison. It does not make latency, CPU, memory, or exhaustive hardening claims.

Finding totals are conservative counts of reproducible discrepancy signals, not counts of unique root causes. A missing or regrouped item can create correlated Markdown, JSON, table, visual, and DOM signals. The source-grounded adjudication ledgers must be consulted before treating signals as separate production defects or forcing parity with model-generated, inferred, or source-contradicted baseline content.

## Release readiness

**NOT READY** — 30 functional regression(s), 0 manual-review signal(s), 0 evidence gap(s), 2 accepted/harmless difference(s), and 0 hash-validated resolved discrepancy/discrepancies.

A `pending` case lacks one or more service artifacts or rendered-page captures; it is not a fidelity pass. A `fixed` case requires a hash-bound resolution ledger and a clean rerun. A hash-bound prior issue may be resolved while unrelated current findings keep the PDF at `discrepancy_found`.

## Per-PDF status

| PDF | Status | Critical | Major | Minor | Functional | Review | Evidence gaps | Evidence |
|---|---|---:|---:|---:|---:|---:|---:|---|
| `postal-10k.pdf` | **discrepancy_found** | 6 | 22 | 4 | 30 | 0 | 0 | [`evidence.json`](postal-10k/evidence.json) |

## Findings

### postal-10k

Status: **discrepancy_found**

| Physical page | Page status | JSON text recall | JSON text precision | Sequence ratio | Reference DOM | Service DOM | Findings |
|---:|---|---:|---:|---:|---|---|---:|
| 1 | discrepancy_found | 100.00% | 96.21% | 98.07% | yes | yes | 10 |
| 2 | discrepancy_found | 96.90% | 91.91% | 94.34% | yes | yes | 12 |
| 3 | discrepancy_found | 100.00% | 96.81% | 98.38% | yes | yes | 13 |

- `FID-POSTAL-10K-7edf41919ded` — **minor / functional_regression** — markdown, page(s) 1, 2, 3: Raw Markdown has missing, added, replaced, duplicated, or reordered visible text. Owner: `GAP-TEXT-001` / `P02-US04`; test: `test_p02_us04_text_reconciliation.py`.
- `FID-POSTAL-10K-d8dd5c1d81a1` — **major / functional_regression** — markdown, page(s) 2, 3: Heading text, level, or order differs from LlamaParse. Owner: `GAP-LIST-001` / `P03-US07`; test: `test_p03_us07_outline_structure.py`.
- `FID-POSTAL-10K-39152c79bdbc` — **minor / functional_regression** — markdown, page(s) 3: User-visible Markdown emphasis or code syntax differs. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-POSTAL-10K-5d7ad72c5a64` — **major / functional_regression** — markdown, page(s) 1: Table 1 differs in shape, spans, row order, or cell content. Owner: `GAP-TABLE-003` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-POSTAL-10K-f3794519e215` — **major / functional_regression** — markdown, page(s) 2: Table 2 differs in shape, spans, row order, or cell content. Owner: `GAP-TABLE-003` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-POSTAL-10K-20c56ad733fd` — **critical / functional_regression** — markdown, page(s) 3: Table 3 differs in shape, spans, row order, or cell content. Owner: `GAP-TABLE-003` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-POSTAL-10K-5242a9c9e257` — **minor / acceptable_difference** — json, page(s) 2: Cross-envelope component decomposition or taxonomy differs on the page. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-POSTAL-10K-03829e843250` — **minor / acceptable_difference** — json, page(s) 3: Cross-envelope component decomposition or taxonomy differs on the page. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-POSTAL-10K-f216f5bfea98` — **major / functional_regression** — json, page(s) 1: Table 1 differs in shape, spans, row order, or cell content. Owner: `GAP-TABLE-002` / `P04-US01`; test: `test_p04_us01_span_fidelity.py`.
- `FID-POSTAL-10K-86120a6ddb27` — **major / functional_regression** — json, page(s) 2: Table 2 differs in shape, spans, row order, or cell content. Owner: `GAP-TABLE-002` / `P04-US01`; test: `test_p04_us01_span_fidelity.py`.
- `FID-POSTAL-10K-a1b1d6df1503` — **critical / functional_regression** — json, page(s) 3: Table 3 differs in shape, spans, row order, or cell content. Owner: `GAP-TABLE-002` / `P04-US01`; test: `test_p04_us01_span_fidelity.py`.
- `FID-POSTAL-10K-277e4e3694f7` — **major / functional_regression** — json, page(s) 1: Page-associated JSON component content differs from LlamaParse. Owner: `GAP-TEXT-001` / `P02-US04`; test: `test_p02_us04_text_reconciliation.py`.
- `FID-POSTAL-10K-58019aa19019` — **major / functional_regression** — json, page(s) 2: Page-associated JSON component content differs from LlamaParse. Owner: `GAP-TEXT-001` / `P02-US04`; test: `test_p02_us04_text_reconciliation.py`.
- `FID-POSTAL-10K-2022440939c9` — **major / functional_regression** — json, page(s) 3: Page-associated JSON component content differs from LlamaParse. Owner: `GAP-TEXT-001` / `P02-US04`; test: `test_p02_us04_text_reconciliation.py`.
- `FID-POSTAL-10K-70a419d08aa1` — **critical / functional_regression** — rendered_dom, page(s) 1: Rendered Markdown visible semantic text differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-POSTAL-10K-a9e944c1b75c` — **major / functional_regression** — rendered_dom, page(s) 1: Rendered semantic tag hierarchy or order differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-POSTAL-10K-e136331caec8` — **major / functional_regression** — rendered_dom, page(s) 1: Rendered item grouping/type sequence differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-POSTAL-10K-ebbed5c1b28d` — **major / functional_regression** — rendered_dom, page(s) 1: Table 1 differs in shape, spans, row order, or cell content. Owner: `GAP-TABLE-003` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-POSTAL-10K-6f61ae0a617a` — **major / functional_regression** — rendered_dom, page(s) 1: Rendered links differ in text, target, or order. Owner: `GAP-LINK-001` / `P01-US01`; test: `test_p01_us01_ir_contract.py`.
- `FID-POSTAL-10K-fe7e8c44f1ac` — **major / functional_regression** — rendered_dom, page(s) 1: Rendered images differ in count, order, or alternative text. Owner: `GAP-COVERAGE-001` / `P07-US02`; test: `test_p07_us02_image_parity.py plus M5 twins`.
- `FID-POSTAL-10K-0accfd6e4ad7` — **critical / functional_regression** — rendered_dom, page(s) 2: Rendered Markdown visible semantic text differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-POSTAL-10K-846fd1c1e1c6` — **major / functional_regression** — rendered_dom, page(s) 2: Rendered semantic tag hierarchy or order differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-POSTAL-10K-631efe9ae3f1` — **major / functional_regression** — rendered_dom, page(s) 2: Rendered item grouping/type sequence differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-POSTAL-10K-d16c37371202` — **major / functional_regression** — rendered_dom, page(s) 2: Table 1 differs in shape, spans, row order, or cell content. Owner: `GAP-TABLE-003` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-POSTAL-10K-22d478968d14` — **major / functional_regression** — rendered_dom, page(s) 2: Rendered links differ in text, target, or order. Owner: `GAP-LINK-001` / `P01-US01`; test: `test_p01_us01_ir_contract.py`.
- `FID-POSTAL-10K-f1f2008802d0` — **major / functional_regression** — rendered_dom, page(s) 2: Rendered images differ in count, order, or alternative text. Owner: `GAP-COVERAGE-001` / `P07-US02`; test: `test_p07_us02_image_parity.py plus M5 twins`.
- `FID-POSTAL-10K-5459c1c6ad0d` — **critical / functional_regression** — rendered_dom, page(s) 3: Rendered Markdown visible semantic text differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-POSTAL-10K-5e6c12139733` — **major / functional_regression** — rendered_dom, page(s) 3: Rendered semantic tag hierarchy or order differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-POSTAL-10K-86a5adcbea66` — **major / functional_regression** — rendered_dom, page(s) 3: Rendered item grouping/type sequence differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-POSTAL-10K-8aeb37ed00e9` — **critical / functional_regression** — rendered_dom, page(s) 3: Table 1 differs in shape, spans, row order, or cell content. Owner: `GAP-TABLE-003` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-POSTAL-10K-7533d9dd6a4b` — **major / functional_regression** — rendered_dom, page(s) 3: Rendered links differ in text, target, or order. Owner: `GAP-LINK-001` / `P01-US01`; test: `test_p01_us01_ir_contract.py`.
- `FID-POSTAL-10K-3fa20ba88ac0` — **major / functional_regression** — rendered_dom, page(s) 3: Rendered images differ in count, order, or alternative text. Owner: `GAP-COVERAGE-001` / `P07-US02`; test: `test_p07_us02_image_parity.py plus M5 twins`.

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
