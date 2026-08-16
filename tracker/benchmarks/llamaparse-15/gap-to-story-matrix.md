# Gap-to-Story Matrix

Status: Complete  
Rule: every confirmed gap has a primary owning story; secondary stories consume
or validate that capability without duplicating its implementation.

| Gap | Primary story | Secondary stories | Story action | Dedicated test anchor | Milestone |
|---|---|---|---|---|---|
| GAP-BENCHMARK-001 | P00-US04 | P00-US01/US02/US05–US09 | Approved bounded registration chain | `test_p00_us04_corpus_registry.py` plus P00-US05–US09 anchors | M0 |
| GAP-BENCHMARK-002 | P00-US10 | P00-US03 | Approved 5-point runner story | `test_p00_us10_corpus_runner.py` | M0–M6 |
| GAP-COVERAGE-001 | P07-US02 | P07-US01/US08/US09 | Existing; readiness blocker | `test_p07_us02_image_parity.py` plus M5 twins | M5 |
| GAP-UNICODE-001 | P02-US01 | P02-US02/US03/US04 | Existing; evidence/acceptance expanded | `test_p02_us01_font_audit.py` | M1 |
| GAP-TEXT-001 | P02-US04 | P02-US03/US06 | Existing; evidence/acceptance expanded | `test_p02_us04_text_reconciliation.py` | M1 |
| GAP-OCR-001 | P02-US06 | P02-US04/US05, P05-US06 | Existing; evidence/acceptance expanded | `test_p02_us06_spatial_tokens.py` | M1/M4 |
| GAP-LAYOUT-001 | P03-US01 | P03-US02/US03/US04 | Existing; evidence/acceptance expanded | `test_p03_us01_table_captions.py` | M2 |
| GAP-ORDER-001 | P03-US04 | P01-US03 | Existing; evidence/acceptance expanded | `test_p03_us04_reading_order.py` | M2 |
| GAP-PAGE-001 | P03-US08 | P01-US03/US04 | New 3-point story | `test_p03_us08_running_regions.py` | M2 |
| GAP-REDLINE-001 | P03-US05 | P01-US01/US02/US03 | New 5-point story | `test_p03_us05_redline_runs.py` | M2 |
| GAP-FORM-001 | P03-US06 | P04-US04 | New 5-point story | `test_p03_us06_forms_key_values.py` | M2/M3 |
| GAP-LIST-001 | P03-US07 | P01-US02/US03 | New 3-point story | `test_p03_us07_outline_structure.py` | M2 |
| GAP-LINK-001 | P01-US01 | P01-US02/US03 | Existing; additive relation evidence | `test_p01_us01_ir_contract.py` | M2 |
| GAP-BBOX-001 | P01-US01 | P01-US02, P03-US04, P04/P05 | Existing; child-role validation expanded | `test_p01_us01_ir_contract.py` | M1–M4 |
| GAP-TABLE-001 | P04-US04 | P03-US06, P04-US02 | New 5-point story | `test_p04_us04_table_candidate_gate.py` | M3 |
| GAP-TABLE-002 | P04-US01 | P04-US02/US04 | Existing; re-estimated 3→5 | `test_p04_us01_span_fidelity.py` | M3 |
| GAP-TABLE-003 | P01-US03 | P01-US04, P04-US01 | Existing; parity assertions expanded | `test_p01_us03_canonical_presentation.py` | M3 |
| GAP-CHART-001 | P05-US03 | P05-US01/US06 | Existing; multi-panel/explicit-value cases added | `test_p05_us03_axes_legends.py` | M4 |
| GAP-CHART-002 | P05-US04 | P05-US02/US05/US07–US09 | Existing; expert-error negatives added | `test_p05_us04_vector_values.py` | M4 |
| GAP-DIAGRAM-001 | P05-US10 | P06-US05 | Existing; containment/direction cases added | `test_p05_us10_diagram_topology.py` | M4 |
| GAP-VISUAL-001 | P06-US05 | P06-US01/US04/US06 | Existing; generated-vs-explicit grounding expanded | `test_p06_us05_grounding.py` | M4/M5 |
| GAP-SERIALIZATION-001 | P01-US03 | P01-US04, P03-US08, P04/P05 | Existing; body/full and duplicate contracts expanded | `test_p01_us03_canonical_presentation.py` | M1–M6 |
| GAP-PROVENANCE-001 | P01-US01 | P01-US02, P08-US05/US06 | Existing; field-level methods and dimensions added | `test_p01_us01_ir_contract.py` | M1–M6 |
| GAP-DIAGNOSTICS-001 | P08-US04 | P08-US05/US06/US07 | Existing; silent/false concern fixtures added | `test_p08_us04_quality_cost_telemetry.py` | M6 |
| GAP-PERFORMANCE-001 | P08-US03 | P00-US10, P08-US10 | Existing; timetable/Uber gates added | `test_p08_us03_resource_telemetry.py` | M0/M6 |

## New-story justification

No new phase is required. Every new story is a coherent reusable capability with
its own dependencies, tests, feature flag or benchmark-only boundary, and
rollback:

The requester-approved denominator correction changes P00-US06 from 73 to 71
and the corpus from 212 to 210 without changing story points or dependencies.

| New story | Why existing scope is insufficient | Points |
|---|---|---:|
| P00-US04 | Portable identity/custody registration is independent of reviewed claims and controls | 3 |
| P00-US05 | General reviewed-claim and inclusion-mask contracts require their own backward-compatible gate | 3 |
| P00-US06 | First five-case, 71-claim batch is one bounded review/annotation unit | 5 |
| P00-US07 | Second five-case, 76-claim batch is one bounded review/annotation unit | 5 |
| P00-US08 | Final five-case, 63-claim batch closes the finite 210-claim inventory | 5 |
| P00-US09 | Twenty-five gap-owner control quartets and 109 case-gap rows form an independent registry | 5 |
| P00-US10 | The one-case baseline cannot absorb immutable corpus execution plus semantic milestone reporting | 5 |
| P03-US05 | Run-level redline evidence is legally material and independent of ordinary reading order | 5 |
| P03-US06 | Forms/controls/blank values require a distinct relationship contract from tables | 5 |
| P03-US07 | List/outline hierarchy is independently testable and not a form/table concern | 3 |
| P03-US08 | Printed page identity and running-region policy are independent of body ordering | 3 |
| P04-US04 | Table-versus-chart/form gating is explicitly outside the current table-reconciliation story | 5 |

P04-US01 is re-estimated from 3 to 5 points because the reviewed corpus expands
its required tests from one simple explicit table to rotated dense grids,
multi-level financial headers, blank/section rows, irregular form grids, and
multiline cell ownership. It remains one bounded cell/span-fidelity capability.

## Point and dependency impact

- Previous: 57 stories, 268 points.
- Approved: 69 stories, 322 points.
- Added stories: 12, adding 52 points.
- Re-estimate: P04-US01 adds 2 points.
- New Phase 00 gate: P01-US01 now depends on P00-US10 rather than P00-US03.
- P04-US03 now depends on P04-US02, P04-US04, and P03-US04 so multi-page logic
  consumes a validated canonical table candidate.
- No story exceeds 5 points.
