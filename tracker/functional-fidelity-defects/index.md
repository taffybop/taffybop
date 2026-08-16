# Defect Index

Inventory baseline: `source-grounded-final-disposition-v2.json`  
Current counts: **12 Proposed, 0 Ready, 1 In Progress, 0 Validating, 1 Blocked, 0 Done**

Every card is governed by the mandatory
[`generic production policy`](generic-production-policy.md), the recorded
[`pre-remediation genericity audit`](pre-remediation-genericity-audit.md), and
the [`immediate affected-benchmark validation gate`](immediate-affected-benchmark-validation.md),
which requires a fresh full-PDF LlamaParse/service comparison of raw Markdown,
actual rendered UI/DOM, and full JSON immediately after each fix. That gate
validates the particular defect's oracle, symptoms, and declared collateral
boundary, automatically drift-compares the complete outputs, and manually
reviews every changed outside-boundary region; exhaustive unaffected-region
review remains at the wave/final gates. It is followed by
the [`final all-15 validation gate`](final-all-15-validation.md). A benchmark
match cannot close a card whose production path contains document-specific
logic or lacks new-PDF variation evidence.

| ID | Root-cause defect | Severity | Priority | Cases | Primary owner | Status | First work item |
|---|---|---|---|---|---|---|---:|
| [FFD-001](issues/FFD-001-visual-text-owner-boundaries.md) | Legitimate native visual text is rejected at owner boundaries | Major | P0 | Health, Manufacturing, Uber | P03-US02 / P02-US06 | Proposed | 7 |
| [FFD-002](issues/FFD-002-visual-ocr-normalization.md) | Rotation, fusion, duplication, and ordering defects in visual OCR | Major | P0 | Catastrophe, Clean, ESG, Component | P02-US06 | Proposed | 13 |
| [FFD-003](issues/FFD-003-chart-semantic-assembly.md) | Printed chart semantics are not assembled into complete structures | Critical | P0 | Catastrophe, Clean, eGov, ESG, Health, Manufacturing, Uber | P05-US03 | Proposed | 12 |
| [FFD-004](issues/FFD-004-reading-order-and-running-regions.md) | Relationship-aware reading order and running/caption ordering are incomplete | Major | P1 | Clinical, ESG, Manufacturing, Uber | P03-US04 / P03-US08 | Proposed | 8 |
| [FFD-005](issues/FFD-005-heading-and-callout-hierarchy.md) | Heading, section, and callout hierarchy is flattened or mistyped | Major | P1 | Clinical, Manufacturing, Uber | P03-US07 | Proposed | 8 |
| [FFD-006](issues/FFD-006-inline-typography-and-unicode.md) | Native inline typography and Unicode semantics are lost | Major | P1 | Clinical, ESG | P02-US01 / P03-US05 | Proposed | 6 |
| [FFD-007](issues/FFD-007-private-use-glyph-recovery.md) | Component NOTE private-use glyph lacks safe recovery | Minor | P3 | Component | P02-US01 | Proposed | 5 |
| [FFD-008](issues/FFD-008-diagram-topology.md) | Diagram topology is incomplete for source-visible geometry | Major | P1 | Clinical, Component, Uber | P05-US10 + new stories | Proposed | 19 |
| [FFD-009](issues/FFD-009-photo-diagnostic-ocr.md) | Board-photo diagnostic OCR remains noisy in JSON | Minor | P3 | Component | New diagnostics story if retained | Proposed | 22 |
| [FFD-010](issues/FFD-010-acord-coverage-grid-ownership.md) | ACORD lower coverage grid lacks one semantic owner | Critical | P1 | Insurance ACORD | P03-US06 / P04-US04 | Proposed | 4 |
| [FFD-011](issues/FFD-011-postal-detached-fers-duplicate.md) | Detached FERS paragraph duplicates the glossary row | Major | P1 | Postal | P02-US04 / P04-US01 | Blocked | 1 |
| [FFD-012](issues/FFD-012-postal-table-inline-emphasis.md) | Table-cell italics are not serialized or rendered | Minor | P2 | Postal | P03-US05 / P04-US01 | Proposed | 2 |
| [FFD-013](issues/FFD-013-postal-table-em-dashes.md) | Source em dashes become ASCII hyphens in table cells | Minor | P2 | Postal | P02-US04 / P04-US01 | Proposed | 3 |
| [FFD-014](issues/FFD-014-clinical-crossmark-visual-overlay-custody.md) | Clinical Crossmark visual overlay blocks terminal table custody | Major | P1 | Clinical | P04-US01 / P01-US03 | In Progress | 1a |

## Release tracking

- FFD-011's first fresh dual-system complete-PDF
  attempt corrected FERS but exposed material CARES/Exchange collateral and is
  preserved as failed. The bounded generic refinement, independent production
  review, and second fresh complete-PDF attempt now pass the exact target and
  declared collateral on all three surfaces. The card is now `Blocked`, not
  `Validating`: FFD-014 is the sole `In Progress` production defect and owns
  the exact Clinical included-placeholder-versus-omitted-visual graph-custody
  transition. The separately governed NY document/page deadline blocker also
  remains. FFD-012 is unstarted and the other 12 cards remain `Proposed`.
- FFD-014 is post-baseline control evidence. It does not add an `SG-*` row or
  rewrite the immutable 25-gap v2 disposition. Its user-authorized first
  segment is Clinical physical page 1 only and pauses before page-2-specific
  work; production remains at 5.0 seconds/document and 0.500 seconds/page. The
  final bounded page-one HTTP/Full-renderer handoff passes, but terminal P04
  custody remains unclosed and the result is not the fresh transaction-
  exercising dual-system closure bundle required for `Done`. See the
  [`page-one release-slice amendment`](decisions/2026-08-14-ffd-014-clinical-page-one-release-slice-amendment.md).
- FFD-014 returned from `Validating` to `In Progress` on 2026-08-14. The latest
  named production-5-second and test-only-10-second custody observations both
  lack `canonical_source_custody`; they predate the final footer replay and
  remain unresolved rather than settled current-candidate verdicts. Production
  deadlines are unchanged, no page-2 Clinical source was inspected, FFD-011
  remains `Blocked`, and Wave A/final all-15 validation remains pending.
- A PDF becomes `fixed` only when every source-grounded defect affecting it is
  Done. Closing one manifestation does not close a case with other gaps.
- Release readiness requires zero open P0/P1 defects and a fresh all-15 final
  benchmark. P2/P3 exceptions require explicit source-grounded acceptance,
  not silent deferral.
- FFD-008's bounded Clinical physical-page-3 directed-raster implementation is
  green in the current API and four-page rendered capture: one semantic list
  represents 15 nodes, 14 connectors, 13 owned details, and one root; its
  caption and `.g001` note occur once, page 2 has no `.g001`, and pages 2 and 4
  retain one structured candidate table each. This is not aggregate closure or
  the mandatory fresh dual-system transition bundle. Component and Uber
  topology remain unresolved, so FFD-008 remains `Proposed`. FFD-014 remains
  `In Progress`, FFD-011 remains `Blocked`, and registry status counts remain
  **12 Proposed, 0 Ready, 1 In Progress, 0 Validating, 1 Blocked, 0 Done**.
