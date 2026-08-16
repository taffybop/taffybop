# Source-Gap Coverage

Evidence baseline: `tracker/benchmarks/llamaparse-15/runs/functional-fidelity-20260813/source-grounded-final-disposition-v2.json`  
Baseline SHA-256: `5bb478ca60486969293ec12e2099987130b33f25b5d37af9bcff649138dd7a17`  
Coverage: **25/25 authoritative remaining gaps mapped to 13/13 baseline root-cause defects; plus one post-baseline control defect**

The gap text below is copied verbatim from each case's
`remaining_functional_gaps` array. A composite source gap can map to more than
one defect when it contains independently owned failure modes. That does not
create another source gap or another root-cause defect.

| Gap | Case | Authoritative remaining gap | Mapped defect(s) | Mapping basis |
|---|---|---|---|---|
| SG-001 | `catastrophe-recap` | The chart's explicit legend, axes, selected years, and panel structure are not fully normalized. | FFD-003 | Chart semantic assembly. |
| SG-002 | `catastrophe-recap` | Some chart-origin text remains noisy or fused in OCR presentation. | FFD-002 | Visual OCR normalization. |
| SG-003 | `clean-energy` | Six-panel, axis, and legend organization remains incomplete. | FFD-003 | Chart panel, axis, and legend assembly. |
| SG-004 | `clean-energy` | Rotated OCR has residual noise, duplication, and ordering defects. | FFD-002 | Rotation-aware visual OCR normalization and ordering. |
| SG-005 | `clinical-study` | The sidebar precedes the title and some body text or diacritics remain damaged. | FFD-004, FFD-006 | Reading order and native Unicode/text fidelity are independently owned. |
| SG-006 | `clinical-study` | Heading and outline hierarchy remain flatter than the source. | FFD-005 | Heading and outline hierarchy. |
| SG-007 | `clinical-study` | Visible flowchart connector topology remains safely unresolved because endpoint and direction evidence is insufficient. | FFD-008 | Source-grounded diagram topology. |
| SG-008 | `component-datasheet` | Diagnostic OCR for the page-1 board photograph remains noisy in JSON. | FFD-009 | Diagnostic-only photograph OCR. |
| SG-009 | `component-datasheet` | Page-2 pin labels are incomplete or noisy and the pinout's spatial topology is unmodeled. | FFD-002, FFD-008 | Label OCR and topology are separate failure modes. |
| SG-010 | `component-datasheet` | A source private-use NOTE glyph is not recovered faithfully. | FFD-007 | Private-use glyph recovery. |
| SG-011 | `egov-survey` | Printed bar labels are not yet associated into complete year/category series. | FFD-003 | Printed chart series assembly. |
| SG-012 | `esg-metrics` | The small fiscal-row chart retains noisy user-visible OCR and has no complete series organization. | FFD-002, FFD-003 | Visual OCR and chart-series assembly are independently owned. |
| SG-013 | `esg-metrics` | Some superscript and source column/reading-order presentation remains degraded. | FFD-004, FFD-006 | Column order and inline superscript semantics are independently owned. |
| SG-014 | `health-report` | The second chart retains residual OCR noise because its native text does not satisfy strict owner containment. | FFD-001 | Owner-boundary rejection is the source of the residual primary OCR. |
| SG-015 | `health-report` | Axis, category, and series organization remains incomplete for both charts. | FFD-003 | Chart semantic assembly. |
| SG-016 | `insurance-acord` | The lower coverage grid and its table-versus-form ownership were explicitly outside the scoped ACORD correction and remain unresolved. | FFD-010 | Coverage-grid semantic ownership. |
| SG-017 | `manufacturing-report` | Some page-2 OCR remains primary because source text boxes cross visual-owner boundaries. | FFD-001 | Visual-text owner-boundary handling. |
| SG-018 | `manufacturing-report` | Complete series and curve semantics remain unresolved. | FFD-003 | Chart series and curve assembly. |
| SG-019 | `manufacturing-report` | Residual caption/order and '4.3.' hierarchy presentation differences remain user-visible. | FFD-004, FFD-005 | Caption order and hierarchy typing are independently owned. |
| SG-020 | `postal-10k` | A detached complete 'FERS Federal Employees Retirement System' paragraph still duplicates the glossary row. | FFD-011 | Detached duplicate ownership. |
| SG-021 | `postal-10k` | Four source-italic glossary spans are present in JSON sidecars but are not serialized into table Markdown or rendered emphasis. | FFD-012 | Table-cell inline emphasis projection. |
| SG-022 | `postal-10k` | Four page-3 source em dashes serialize as ASCII hyphens. | FFD-013 | Table-cell Unicode serialization. |
| SG-023 | `uber-earnings` | Page-2 charts lack complete series and printed-value organization. | FFD-003 | Chart series and printed-value assembly. |
| SG-024 | `uber-earnings` | Page-3 unlabeled fan geometry remains unresolved, and the first diagram's primary OCR omits source labels whose boxes cross its owner boundary. | FFD-001, FFD-008 | Owner-boundary text custody and diagram geometry are independently owned. |
| SG-025 | `uber-earnings` | Heading/date/footer ordering and construction-text filtering retain user-visible differences. | FFD-004, FFD-005 | Running-region order and heading/construction callout typing are independently owned. |

## Reverse coverage

| Defect | Covered source gaps |
|---|---|
| FFD-001 | SG-014, SG-017, SG-024 |
| FFD-002 | SG-002, SG-004, SG-009, SG-012 |
| FFD-003 | SG-001, SG-003, SG-011, SG-012, SG-015, SG-018, SG-023 |
| FFD-004 | SG-005, SG-013, SG-019, SG-025 |
| FFD-005 | SG-006, SG-019, SG-025 |
| FFD-006 | SG-005, SG-013 |
| FFD-007 | SG-010 |
| FFD-008 | SG-007, SG-009, SG-024 |
| FFD-009 | SG-008 |
| FFD-010 | SG-016 |
| FFD-011 | SG-020 |
| FFD-012 | SG-021 |
| FFD-013 | SG-022 |
| FFD-014 | Post-baseline P04 production control; no `SG-*` row |

## Coverage invariants

- Every baseline gap string appears exactly once as an `SG-*` row.
- Every `SG-*` row maps to at least one `FFD-*` defect.
- Every baseline defect `FFD-001` through `FFD-013` covers at least one
  authoritative source gap. FFD-014 is separately admitted post-baseline
  production-control evidence and does not create or claim `SG-026`.
- Multiple output-surface signals remain manifestations, not additional gaps.
- Accepted differences and fixed cases are excluded from this open-gap denominator.

## Validation disposition note

- SG-020's exact detached-duplicate symptom passes the fresh immutable
  `20260813T151137Z-FFD-011-focused` source/Markdown/UI-DOM/JSON comparison.
  It remains in the open baseline denominator because FFD-011 is now `Blocked`:
  FFD-014 owns the two Clinical terminal visual-overlay custody failures, and
  the independent NY control remains separately governed. Exact capture shows
  an included placeholder/contributor versus an empty omitted
  `unsupported_primary_ocr` reconstruction with different graph custody, not
  an optional-null difference. This note does not rewrite the immutable source-
  gap wording, close FFD-011, close Postal (SG-021/SG-022 remain open), or start
  FFD-012/FFD-013.

## 2026-08-14 Clinical page-one local disposition

The bounded Clinical physical-page-1 release projection now corrects SG-005's
reviewed first-page sidebar/preamble manifestation and restores source-visible
header, article label, visual labels, and footer presentation. This is local
validation only. SG-005 remains in the frozen open denominator because
FFD-004/FFD-006 are not closed, the pre-existing Clean Energy ordering gate
keeps the dependent genericity audit open, no Clinical page-2 source was
inspected, and the complete defect/wave/final gates have not passed.

FFD-014 remains a post-baseline P04 control with no `SG-*` row. Its page-one
projection passes, but terminal P04 custody is unclosed, so FFD-014 is `In
Progress` and FFD-011 remains `Blocked`. No baseline gap wording or count is
changed. The Wave A all-15 drift gate and final frozen all-15 campaign remain
pending.

## 2026-08-15 Clinical page-three topology local disposition

The bounded current-code correction resolves the reviewed SG-007 manifestation
on Clinical physical page 3: one root, 15 nodes, 14 source-grounded directed
connectors, and 13 owned details render as one semantic nested list, with the
caption and `.g001` visual note exactly once and no unstructured-diagram
fallback. The fresh four-page service/render capture also places `.g001` zero
times on page 2 and preserves one structured candidate table on each of pages
2 and 4.

This is local implementation/UI validation only. SG-007 remains in the frozen
25-gap open denominator because aggregate FFD-008 is still `Proposed`, the
Component and Uber topology families remain unresolved, and the affected-
benchmark dual-system, Wave D, and final all-15 gates have not passed. No
baseline gap wording, mapping, defect, or count is added or changed.
