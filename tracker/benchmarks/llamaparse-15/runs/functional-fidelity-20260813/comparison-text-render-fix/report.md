# LlamaParse-15 functional-fidelity comparison

Run: `functional-fidelity-20260813`  
Candidate artifacts: `service-text-render-fix`  
Analyzer schema: `functional-fidelity-comparison-v1`  
Story mapping: `tracker/benchmarks/llamaparse-15/gap-to-story-matrix.md`

This is a functionality/output-quality comparison. It does not make latency, CPU, memory, or exhaustive hardening claims.

## Release readiness

**NOT READY** — 34 functional regression(s), 1 manual-review signal(s), 0 evidence gap(s), 7 accepted/harmless difference(s), and 0 hash-validated resolved discrepancy/discrepancies.

A `pending` case lacks one or more service artifacts or rendered-page captures; it is not a fidelity pass. A `fixed` case requires a hash-bound resolution ledger and a clean rerun. A hash-bound prior issue may be resolved while unrelated current findings keep the PDF at `discrepancy_found`.

## Per-PDF status

| PDF | Status | Critical | Major | Minor | Functional | Review | Evidence gaps | Evidence |
|---|---|---:|---:|---:|---:|---:|---:|---|
| `purchase-agreement.pdf` | **discrepancy_found** | 0 | 3 | 5 | 7 | 0 | 0 | [`evidence.json`](purchase-agreement/evidence.json) |
| `uber-earnings.pdf` | **discrepancy_found** | 13 | 13 | 8 | 27 | 1 | 0 | [`evidence.json`](uber-earnings/evidence.json) |

## Findings

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
- `FID-PURCHASE-AGREEMENT-7a2d1c2fb868` — **minor / functional_regression** — rendered_dom, page(s) 1: Rendered Markdown visible semantic text differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-PURCHASE-AGREEMENT-3db5f2a8cd6d` — **major / functional_regression** — rendered_dom, page(s) 1: Rendered semantic tag hierarchy or order differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-PURCHASE-AGREEMENT-e039123cf927` — **major / functional_regression** — rendered_dom, page(s) 1: Rendered item grouping/type sequence differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.

### uber-earnings

Status: **discrepancy_found**

| Physical page | Page status | JSON text recall | JSON text precision | Sequence ratio | Reference DOM | Service DOM | Findings |
|---:|---|---:|---:|---:|---|---|---:|
| 1 | discrepancy_found | 54.55% | 66.67% | 45.00% | yes | yes | 12 |
| 2 | discrepancy_found | 69.50% | 79.67% | 55.30% | yes | yes | 20 |
| 3 | discrepancy_found | 48.86% | 87.76% | 54.01% | yes | yes | 12 |

- `FID-UBER-EARNINGS-5168da3ba9a9` — **critical / functional_regression** — markdown, page(s) 1, 2, 3: Raw Markdown has missing, added, replaced, duplicated, or reordered visible text. Owner: `GAP-TEXT-001` / `P02-US04`; test: `test_p02_us04_text_reconciliation.py`.
- `FID-UBER-EARNINGS-d4b9dd4167c4` — **major / functional_regression** — markdown, page(s) 1, 2, 3: Heading text, level, or order differs from LlamaParse. Owner: `GAP-LIST-001` / `P03-US07`; test: `test_p03_us07_outline_structure.py`.
- `FID-UBER-EARNINGS-9c4cd53cfb88` — **minor / functional_regression** — markdown, page(s) 1, 2, 3: User-visible Markdown emphasis or code syntax differs. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-UBER-EARNINGS-2910210ba8c9` — **critical / functional_regression** — markdown, page(s) document: Table count or document order differs from LlamaParse. Owner: `GAP-TABLE-001` / `P04-US04`; test: `test_p04_us04_table_candidate_gate.py`.
- `FID-UBER-EARNINGS-fe9f0a58649e` — **minor / acceptable_difference** — json, page(s) 1: Cross-envelope component decomposition or taxonomy differs on the page. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-UBER-EARNINGS-7d25fd2388e9` — **minor / acceptable_difference** — json, page(s) 1: Service JSON adds nested component relationships beyond LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-UBER-EARNINGS-7bd5d8956583` — **minor / acceptable_difference** — json, page(s) 2: Cross-envelope component decomposition or taxonomy differs on the page. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-UBER-EARNINGS-fcb7ac70f875` — **minor / acceptable_difference** — json, page(s) 2: Service JSON adds nested component relationships beyond LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-UBER-EARNINGS-606c50e4045d` — **minor / acceptable_difference** — json, page(s) 3: Cross-envelope component decomposition or taxonomy differs on the page. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-UBER-EARNINGS-b97e58332eb5` — **minor / acceptable_difference** — json, page(s) 3: Service JSON adds nested component relationships beyond LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-UBER-EARNINGS-42c4107aa7b8` — **critical / functional_regression** — json, page(s) 1: Page-associated JSON component content differs from LlamaParse. Owner: `GAP-TEXT-001` / `P02-US04`; test: `test_p02_us04_text_reconciliation.py`.
- `FID-UBER-EARNINGS-8fa01c9a1fba` — **critical / functional_regression** — json, page(s) 2: Page-associated JSON component content differs from LlamaParse. Owner: `GAP-TEXT-001` / `P02-US04`; test: `test_p02_us04_text_reconciliation.py`.
- `FID-UBER-EARNINGS-a9f1a25340a2` — **critical / functional_regression** — json, page(s) 3: Page-associated JSON component content differs from LlamaParse. Owner: `GAP-TEXT-001` / `P02-US04`; test: `test_p02_us04_text_reconciliation.py`.
- `FID-UBER-EARNINGS-66a8a6be02e9` — **minor / review_required** — json, page(s) 1, 2, 3: Visual-origin text proxy differs and requires region-level review. Owner: `GAP-OCR-001` / `P02-US06`; test: `test_p02_us06_spatial_tokens.py`.
- `FID-UBER-EARNINGS-59bfd52367e1` — **major / functional_regression** — json, page(s) 1, 2, 3: Image detection count or page placement differs from LlamaParse. Owner: `GAP-COVERAGE-001` / `P07-US02`; test: `test_p07_us02_image_parity.py plus M5 twins`.
- `FID-UBER-EARNINGS-9ca384140fc1` — **critical / functional_regression** — json, page(s) 1: Image 1 labels, values, description, or caption differ. Owner: `GAP-VISUAL-001` / `P06-US05`; test: `test_p06_us05_grounding.py`.
- `FID-UBER-EARNINGS-bc1d3c49768c` — **critical / functional_regression** — json, page(s) 2: Image 2 labels, values, description, or caption differ. Owner: `GAP-VISUAL-001` / `P06-US05`; test: `test_p06_us05_grounding.py`.
- `FID-UBER-EARNINGS-c7d70a2591c2` — **major / functional_regression** — json, page(s) 2: Image 3 page-relative placement differs materially. Owner: `GAP-VISUAL-001` / `P06-US05`; test: `test_p06_us05_grounding.py`.
- `FID-UBER-EARNINGS-b1072eb8825e` — **major / functional_regression** — json, page(s) 2: Image 4 page-relative placement differs materially. Owner: `GAP-VISUAL-001` / `P06-US05`; test: `test_p06_us05_grounding.py`.
- `FID-UBER-EARNINGS-5455160589dd` — **major / functional_regression** — json, page(s) 2, 3: Chart detection count or page placement differs from LlamaParse. Owner: `GAP-CHART-001` / `P05-US03`; test: `test_p05_us03_axes_legends.py`.
- `FID-UBER-EARNINGS-7dfaaa2c365c` — **critical / functional_regression** — json, page(s) 2: Chart 1 labels, values, description, or caption differ. Owner: `GAP-CHART-002` / `P05-US04`; test: `test_p05_us04_vector_values.py`.
- `FID-UBER-EARNINGS-238f16d0cef0` — **major / functional_regression** — json, page(s) 2: Chart 1 page-relative placement differs materially. Owner: `GAP-VISUAL-001` / `P06-US05`; test: `test_p06_us05_grounding.py`.
- `FID-UBER-EARNINGS-101ca7fe396e` — **critical / functional_regression** — json, page(s) 2: Chart 2 labels, values, description, or caption differ. Owner: `GAP-CHART-002` / `P05-US04`; test: `test_p05_us04_vector_values.py`.
- `FID-UBER-EARNINGS-3fbf95e45ffa` — **major / functional_regression** — json, page(s) 2: Chart 2 page-relative placement differs materially. Owner: `GAP-VISUAL-001` / `P06-US05`; test: `test_p06_us05_grounding.py`.
- `FID-UBER-EARNINGS-8b1fdd3dd7d7` — **critical / functional_regression** — rendered_dom, page(s) 1: Rendered Markdown visible semantic text differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-UBER-EARNINGS-4c2e0beeb2cd` — **major / functional_regression** — rendered_dom, page(s) 1: Rendered semantic tag hierarchy or order differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-UBER-EARNINGS-abd38be1753f` — **major / functional_regression** — rendered_dom, page(s) 1: Rendered item grouping/type sequence differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-UBER-EARNINGS-5e55bf928659` — **critical / functional_regression** — rendered_dom, page(s) 2: Rendered Markdown visible semantic text differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-UBER-EARNINGS-0e496aa75b1c` — **major / functional_regression** — rendered_dom, page(s) 2: Rendered semantic tag hierarchy or order differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-UBER-EARNINGS-01731ea003bb` — **major / functional_regression** — rendered_dom, page(s) 2: Rendered item grouping/type sequence differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-UBER-EARNINGS-7095abff6384` — **critical / functional_regression** — rendered_dom, page(s) 2: Table count or document order differs from LlamaParse. Owner: `GAP-TABLE-001` / `P04-US04`; test: `test_p04_us04_table_candidate_gate.py`.
- `FID-UBER-EARNINGS-478163896fff` — **critical / functional_regression** — rendered_dom, page(s) 3: Rendered Markdown visible semantic text differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-UBER-EARNINGS-84446af07d31` — **major / functional_regression** — rendered_dom, page(s) 3: Rendered semantic tag hierarchy or order differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-UBER-EARNINGS-1c20a19d5de1` — **major / functional_regression** — rendered_dom, page(s) 3: Rendered item grouping/type sequence differs from LlamaParse. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.

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
