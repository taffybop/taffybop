# FFD-008 — Diagram topology is incomplete for source-visible geometry

Status: **Proposed**  
Severity: **Major**  
Priority: **P1**  
Primary story: **P05-US10 for supported connectors; new stories required for pinout and undirected fan families**  
Dependencies: **FFD-001, FFD-002**

## Scope and impact

| PDF | Physical / printed page | Source truth | Current actual | Surfaces |
|---|---|---|---|---|
| `clinical-study` | p3 / 10/21 | raster flowchart has explicit labels and visible connectors | diagram/labels retained; connector topology unresolved | JSON diagram, Markdown/UI fallback |
| `component-datasheet` | p2 / visible 7 | pinout has explicit labels and spatial pin relationships | remains image; labels noisy/incomplete; no pin topology | JSON image/diagram, Markdown/UI |
| `uber-earnings` | p3 / 6 | two labelled association groups and unlabeled fan geometry; no visible arrowheads | two seven-node, zero-edge groups; fan geometry unresolved | JSON diagram/grouping, Markdown/UI |

Source SHA-256: Clinical
`4e33db9cb9171f0b274ab3ba20a288510b5aee309a723412e59f843b59c76ff2`;
Component
`5fc8143f33d156d914b0f139177344be6ad2b0a8d2906413424d6dda93fe36a4`;
Uber `76a4d3fb8af06adc88ed68538997ef28afb26b377f41014cd83eeaddcbcd29e5`.

Non-goals: no directed Uber arrows without arrowheads; no Llama Mermaid copy;
no domain-semantic interpretation; no invented pin functions or hidden edges;
label OCR/ownership belongs to FFD-001/002.

## Source-grounded oracle

- Clinical: enumerate visible nodes/connectors and classify each connector as
  endpoint/direction-proven, undirected-proven, or unresolved. Current evidence
  explicitly says endpoint/direction proof is insufficient; this enumeration is
  mandatory before Ready.
- Component: enumerate every visible pin label, pin position/number, side/group,
  and source-visible adjacency; decide a new pinout spatial-topology contract.
- Uber: retain the two established seven-node groups and zero unsupported
  directed connectors; enumerate the unlabeled fan shapes and define the
  source-grounded undirected/group relation required.

## Reproducible evidence

- `comparison-final-source-grounded-v2/{clinical-study,component-datasheet,uber-earnings}/evidence.json`
- `service-final-source-grounded-20260813-v2/<case>/`
- `visual-source-adjudication.json` cases 2, 3, 9
- `visual-source-semantics-resolution-ledger.json` reviewed Clinical/Component
  entries and Uber case
- References: `llamaparse-visual-routing-fix/clinical-study/`
  (`pjb-33emg9582knzmzw35de91sw2y56q`),
  `llamaparse/component-datasheet/` (`pjb-vwv4utu38pi1splat9jlfba1cqrc`),
  `llamaparse-visual-fix/uber-earnings/`
  (`pjb-skyvq5noznjko41p3fs2vxgfgptg`)

Primary candidates: `FID-CLINICAL-STUDY-1b2e7a33b2c3` and
`FID-UBER-EARNINGS-b9b1216e2d02`. They compare detection/placement, so their
source-backed topology subset must be isolated by the Ready oracle. Component
has no direct diagram signal; broad p2 text/image differences are correlated.
Markdown/DOM text differences and unsupported Llama arrows are not primary.

## Root cause

- State: **Confirmed missing family support; topology oracles pending**
- Boundary: visual family classification, node/shape detection, endpoint or
  spatial-group association, and diagram fallback serialization.
- Why one defect: all cases require structured source geometry, but remediation
  must be delivered as separate bounded family slices.
- Safety: only finite source-visible shapes/paths/labels; ambiguous crossings,
  endpoints, or direction remain unresolved and concern-bearing.

## Acceptance criteria

1. Ready provides exact node/shape/connector/group oracles for all three pages,
   including deliberately unresolved relations.
2. Clinical emits every oracle-proven node and connector once with endpoint and
   direction confidence; no unresolved connector is fabricated.
3. Component receives a source-grounded pinout type/schema and represents every
   oracle pin position/label/group once; no pin function is inferred.
4. Uber retains exactly two seven-labelled-node groups, zero directed edges
   without arrowheads, and represents every oracle fan/group shape under the
   new undirected grouping contract.
5. Public JSON validates context-free with bboxes/source IDs for every node and
   relation; Markdown/UI provide a deterministic accessible representation
   without duplicating visual OCR.
6. Crossing lines, missing arrowheads, floating labels, ambiguous endpoints,
   and unlabeled decorative shapes fail closed with concerns.
7. Fresh three-case dual-system/UI evidence and an all-15 visual drift screen
   prove no photo/chart/table regression.

## Generic-production requirements

- Construct diagram/pinout/group topology from reusable node, shape, connector,
  endpoint, arrowhead, containment, alignment, and source-provenance evidence.
  Production behavior must not branch on a filename/hash/case, page number,
  node/element ID, label string, expected edge list, or fixed coordinate/bbox.
- Capability evidence must document supported topology families and confidence
  rules and prove that relationship direction or pin semantics comes only from
  source-visible geometry/text, never from domain knowledge or LlamaParse output.
- Add transformed/synthetic variants that rename/reserialize the PDF, prepend a
  page, change every node label, translate/scale/rotate the graph, reorder pins,
  and vary fan/group spacing. The same source-visible topology must be recovered
  without changing production constants.
- Negative/adversarial variants must include crossing/near-touching lines,
  missing or ambiguous arrowheads, floating labels, disconnected endpoints,
  decorative shapes, unlabeled pins, and two plausible groups; unresolved
  relations must remain concern-bearing and absent from asserted topology.
- Run multiple unrelated real-PDF controls, including chart-heavy `clean-energy`,
  photo-bearing Uber p1, table-heavy `ny-timetable`, and `insurance-acord`, and
  retain evidence that charts, images, forms, and tables are not retyped.

Genericity closure gates:

- [ ] Genericity review records supported topology rules, transformed/synthetic
  proofs, adversarial outcomes, and unrelated real-PDF control results
- [ ] Production diff and repository-search attestation find no benchmark/file/hash/
  case/page/element/string/coordinate branch, expected-edge list, or oracle leak

## Test and rerun plan

- Separate failing slices: Clinical raster connector, Component engineering
  pinout, Uber undirected fan/group geometry.
- Adversarial: line crossing, near endpoint, absent arrowhead, floating label,
  symmetric fan, decorative ellipse, and overlapping owner.
- Controls: existing clean vector flowchart fixtures, Uber zero-arrow contract,
  Clinical once-only OCR, Component board photo, chart cases.
- Suites: P05-US01/P05-US10, new family stories, P03-US02/04, public model,
  canonical/frontend visual fallback.
- Rerun all three affected PDFs through both systems per family; all 15 at wave
  completion.

## Immediate affected-benchmark validation (mandatory)

- After each diagram-family production fix, immediately run the complete PDF(s)
  in that family through both systems. Before Done, run full `clinical-study`,
  `component-datasheet`, and `uber-earnings`; a crop of Clinical p3, Component
  p2, or Uber p3 is supporting evidence only.
- Put every attempt in a new immutable `FFD-008` rerun folder and record source
  hashes, parser/model/settings, LlamaParse job IDs, service build/commit and
  configuration, timestamps, and artifact paths/hashes.
- Preserve LlamaParse raw Markdown, actual rendered Markdown UI snapshot and
  DOM/rendered representation where available, and full original JSON. Preserve
  service raw and canonical full Markdown, actual Clearleaf DOM/snapshot, and
  full original JSON.
- This immediate gate is a **targeted validation of FFD-008**, not an exhaustive
  whole-PDF/all-feature re-audit. Complete PDFs are rerun to exercise topology
  assembly in normal pipeline context. For the diagram family fixed in the current
  slice, manually compare only its approved topology oracle and named owner below:
  the relevant Markdown diagram/fallback fragment and placement, rendered diagram/
  node/edge/group DOM selectors and snapshots, and JSON paths for owner linkage,
  nodes, ports, groups, edges/connectors, direction confidence, geometry, evidence,
  and provenance. Broader unrelated comparison belongs to the control, wave, and
  final all-15 gates.
- Apply each approved topology oracle: Clinical p3/10 flowchart connectors and
  labels; Component p2/visible 7 pin-label/spatial relationships; Uber p3/6 two
  association groups and fan geometry. Verify each supported relationship once,
  preserve unresolved geometry explicitly, and introduce no arrow, direction,
  label, or semantic relation absent from the source.
- Run an automated full-result drift screen over each complete Markdown, rendered
  DOM, and JSON result. Manually adjudicate changes inside the declared impact
  boundary: the target diagram owner, its labels/nodes/groups/connectors, caption,
  immediate neighboring content, ambiguity state, and local order. Any unexpected
  material change outside that boundary blocks closure and must be escalated as a
  cross-defect regression or separately tracked defect.
- Source-ground every target-diagram mismatch and every automated drift alert with
  the PDF and topology oracle, retaining page/owner snapshot or DOM selector/
  excerpt, Markdown fragment, JSON path, expected LlamaParse behavior, service
  behavior, and harmless/accepted/material adjudication.
- Unit/schema tests alone cannot close any family or this card. Any material
  topology, label, placement, fallback, Markdown, UI, JSON, ambiguity, or
  provenance symptom keeps it discrepancy/in progress; fix and repeat a fresh
  full-PDF two-system rerun until all issue-specific assertions pass.

## Story and change record

- Story action: **Add a Clinical correction AC to P05-US10. Create separate new
  stories (IDs assigned during Ready) for Component pinout spatial topology and
  Uber undirected fan/group geometry; the current directed-connector story does
  not promise those families.**
- Expected production files: unknown until each family is Ready.
- Changed files/tests/artifacts/reviewer: none.

## Closure checklist

- [ ] Three exact topology oracles complete
- [ ] New story IDs/acceptance contracts approved
- [ ] Focused tests fail before each family fix
- [ ] Bounded family corrections complete
- [ ] Adversarial/control suites pass
- [ ] Fresh LlamaParse/service JSON/Markdown/DOM retained
- [ ] No unsupported arrows, labels, or semantics introduced
- [ ] Raw Markdown equals canonical full Markdown
- [ ] Clearleaf accessible diagram presentation reviewed
- [ ] All-15 visual drift passes
- [ ] Stories/evidence/registry/coverage/index updated
- [ ] Independent closure review recorded

## 2026-08-15 Clinical-family implementation checkpoint

The bounded Clinical directed-raster family is green in current code. Physical
page 3 produces one semantic nested list from one source-grounded root, 15
nodes, 14 explicit-arrow connectors, and 13 node-owned details. The caption is
present once; the `.g001` visual note is present once after its diagram and is
absent from physical page 2; paragraph, Mermaid, and node/connection-debug
fallbacks are absent. The same fresh four-page API/current-renderer capture
retains one structured candidate table on each of physical pages 2 and 4.

The full Clinical integration passed **2 tests in 28.15 seconds**, the adjacent
backend family passed **523 tests in 6.38 seconds**, and the full frontend unit
suite passed **182 tests** together with TypeScript, focused ESLint, and the
production build/bundle. The production path uses reusable raster geometry,
OCR containment, explicit arrowhead, evidence, and closed-replay rules; it
contains no filename, source hash, case, fixed page, fixture label, expected
edge list, element-ID, or coordinate activation rule.

This is a current-code Clinical-family checkpoint, not aggregate FFD closure
and not a claim that the mandatory fresh dual-system immutable
Markdown/DOM/full-JSON transition bundle, Wave D gate, or final all-15 gate has
passed. Component pinout topology and Uber undirected fan/group geometry remain
unresolved, so **FFD-008 remains Proposed** and the historical closure
checklist above remains unchecked. No new root-cause defect is created.
