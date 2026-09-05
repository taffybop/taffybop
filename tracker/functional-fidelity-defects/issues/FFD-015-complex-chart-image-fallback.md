# FFD-015 — Detected charts lack source-asset-first semantic arbitration

Status: **Proposed**

Severity: **Major**

Priority: **P1**

Primary story: **P05-US01 / P05-US05, with canonical/frontend asset projection**

Dependencies: **FFD-001 for visual-text owner boundaries; prerequisite substrate for FFD-003**

## Scope and impact

- Affected PDFs: `catastrophe-recap`, `clean-energy`, `egov-survey`,
  `esg-metrics`, `health-report`, `manufacturing-report`, and `uber-earnings`.
- Initial visual oracle: `benchmark-expertmodeldata/health-report.pdf`, SHA-256
  `fe0bd5c224d5df5cedf26129a04980ac06b67e165875bca0296c6f2cd483b181`,
  physical p1 / printed p103.
- Initial regions: the two Health chart owners, including the combined
  bar/marker chart and the multi-encoding bubble chart. The complete seven-PDF
  chart-owner inventory from FFD-003 becomes the Ready custody oracle.
- Surfaces: public JSON state/asset/provenance, canonical/raw Markdown,
  Clearleaf DOM, native/OCR transcript, captions, source notes, and immutable
  export evidence.
- Impact: current chart records can retain flat text and metadata without
  guaranteeing the actual source visual. When semantic extraction is absent,
  unsupported, or incomplete, users lose the graph they could inspect now or
  submit to a later independently governed advanced-OCR/model workflow.

This is a post-baseline user requirement. It does not add `SG-026`, rewrite the
immutable 25-gap baseline, or close FFD-003. FFD-015 owns detection handoff,
source-asset custody, family/complexity classification metadata, terminal-state
arbitration, and asset-preserving enrichment lineage. FFD-003 owns semantic
chart assembly and its family-specific completeness validators.

Non-goals:

- Do not convert every chart to image-only output or discard a complete,
  source-grounded structured result.
- Do not use `regular`/`complex` classification alone to select the primary
  representation. A complex chart can still be completely understood.
- Do not invent series, data points, values, relationships, alt text, or prose.
- Do not implement advanced OCR/model enrichment in this card. This card
  preserves the immutable source asset and promotion contract for later work.
- Do not promote photos, logos, forms, tables, diagrams, backgrounds, or
  decorative regions into the chart pipeline.

## Source-grounded oracle

For every region admitted by the conservative chart-detection gate, the
pipeline performs these stages in order and commits them atomically:

1. bind exactly one chart owner, source order, page, and reviewed bbox;
2. retain one deterministic source-faithful asset with integrity custody;
3. classify chart family and bounded `regular`/`complex` evidence;
4. dispatch an approved semantic analyzer when the capability matrix permits;
5. apply the versioned family-specific semantic-completeness gate; and
6. select exactly one public primary while retaining the original asset.

Complexity is routing and risk evidence, not the semantic promotion gate. It
uses generic features such as mark-type count, panels, axes/scales, visual
encodings (position, size, color, and shape), label density/rotation/overlap,
callouts, and legend/owner ambiguity. A complete complex chart is structured-
primary; an ordinary chart without an approved analyzer remains image-primary.

The terminal public contract is:

| `chart_resolution.status` | Required outcome | Primary representation | Supplemental evidence |
|---|---|---|---|
| `structured_primary` | Asset retained; analyzer completed; family completeness gate passed | One structured chart | Same source asset, transcript, and custody |
| `image_primary_unsupported` | Asset retained; no approved analyzer for the family/configuration | One source image | Attributable transcript/caption; no authoritative semantics |
| `image_primary_incomplete` | Asset retained; attempted analysis was incomplete, ambiguous, failed, timed out, or resource-refused | One source image | Independently valid partial facts in JSON only |
| `asset_unavailable` | Chart detected, but its exact owner asset could not be safely rendered, validated, or retained | Grounded predecessor text/caption or unresolved placeholder | Explicit concern; no image reference or semantic authority |

`family_classification` and `complexity_classification` are independent of this
terminal state. `dense_or_multiencoding_marks` may be a complexity reason, but
it never causes image-primary output by itself. `semantic_family_not_supported`
selects `image_primary_unsupported`; it is distinct from an attempted analyzer
that fails the completeness gate and selects `image_primary_incomplete`.

Actual: current visual records can retain owner bboxes, labels, OCR, warnings,
and chart concerns, but no public chart-crop bytes are guaranteed, Clearleaf has
no source-image chart renderer, and chart-to-table/VLM output has no shared
source-grounded completeness arbitration. Metadata-only retention does not
satisfy this requirement.

Before Ready, enumerate every chart owner in all seven affected PDFs: bbox and
coordinate system, included plot/legend/axis/label regions, excluded neighbors,
caption/source-note ownership, source-visible transcript, family and complexity
decision/evidence, analyzer capability, semantic-completeness requirements,
render parameters, and crop/pixel/byte caps. Health supplies the initial crop
and complexity oracle, not a filename-specific production rule.

Ready must choose one public asset transport and versioned schema. Inline
transport defines encoding and exact byte caps. Endpoint-backed transport
defines same-origin/auth behavior, asset-ID plus SHA binding, validity window
and `expires_at`, replay/expiry semantics, atomic creation/cleanup, quotas, and
archived evidence after eviction. A successful response is availability-
checked atomically and remains resolvable throughout its declared validity
window; immutable export evidence retains the bytes afterward.

## Root cause

- State: **Confirmed missing source-asset-first arbitration; complete seven-PDF
  crop/state oracle pending**
- Boundary: chart detection handoff, bounded page-region rendering, asset
  custody, family/complexity classification, semantic capability dispatch,
  completeness arbitration, canonical projection, and frontend rendering.
- Why separate from FFD-003: source-image transport and terminal-state custody
  remain useful even when no semantic analyzer exists. A retained image does
  not claim its axes, categories, series, or points were understood.
- Safety: no stage may branch on a benchmark filename/hash/case, page number,
  title/label text, owner ID, fixed bbox, pixel hash, or fixture lookup. A
  nonempty model/table response or model confidence alone is never semantic
  completeness.

## Acceptance criteria

1. Every canonical chart owner enters the asset stage before family
   classification or semantic dispatch. It has one stable owner ID, page,
   source order, bbox/coordinate system, and evidence lineage. Non-chart
   impostors are refused before this stage.
2. Unless safely refused as `asset_unavailable`, each owner retains exactly one
   deterministic source-faithful bounded PNG. The asset ID, bytes, SHA-256,
   bbox/transform, and render policy remain unchanged through classification,
   analysis, validation, presentation, fallback, and later enrichment.
3. The asset record includes source document SHA-256, physical page, bbox and
   coordinate unit, transform, renderer/version, color/alpha and antialiasing/
   interpolation policies, bbox rounding/padding, DPI/scale, effective
   resolution, pixel dimensions, MIME, byte size, and asset SHA-256. Minimum
   legibility and resolution floors apply in addition to maximum caps.
4. Public output exposes the actual bounded bytes through the selected inline
   or integrity-bound retrieval contract. Server-local paths, external URLs,
   dangling IDs, and metadata-only placeholders do not count. Endpoint-backed
   references resolve for their declared validity window and retain an
   immutable export copy after eviction. Per-asset, total-byte, pixel,
   response-size, quota, and deadline caps fail closed.
5. Each crop contains the complete plot, axes, legend, labels, and marks for one
   owner while excluding neighboring prose, notes, footers, and other owners.
   Clipped, overlapping, or ambiguous ownership selects `asset_unavailable`
   rather than manufacturing a crop.
6. Native/OCR text remains a separately attributable chart transcript with
   exact occurrences and provenance. It may support accessibility and later
   analysis but cannot reappear as detached primary prose or a duplicate chart
   block. Every source-present caption/source note occurs exactly once; absent
   content remains absent.
7. Ready defines one context-free versioned schema with exact paths, types,
   enums, caps, and impossible-combination validation for
   `chart_resolution.status`, `asset_status`, asset ID/metadata/bytes or URL,
   `family_classification`, `complexity_classification` and ordered reasons,
   `semantic_attempt_status`, `completeness_gate_status`, deterministic primary
   reason, ordered subordinate concerns, `primary_representation`, transcript,
   caption/source-note links, and custody relationships.
8. Complexity classification records classifier/rule version and source
   evidence for `regular`, `complex`, or `undetermined`. Each supported family
   defines finite feature rules and thresholds/tolerances. Complexity cannot
   independently select image-primary output or substitute for semantic
   completeness.
9. The semantic capability matrix is closed and versioned. Each supported
   family defines required, optional, and deliberately unresolved panels,
   axes, legends, categories, series, labels, values, evidence, and tolerances.
   `complete` requires every mandatory relationship to be correctly owned,
   source-grounded, nonduplicated, and ambiguity-closed. Unprinted optional
   points may remain absent without making an otherwise valid result incomplete.
10. `structured_primary` requires one retained asset and a passed completeness
    gate. Structured JSON/Markdown/DOM is the only primary; the unchanged asset
    and transcript remain supplemental JSON/export evidence and never form a
    second primary chart block.
11. `image_primary_unsupported` requires one retained asset and
    `semantic_attempt_status: "not_run_no_approved_analyzer"`. It emits no
    authoritative series/points and presents exactly one source-image primary
    with attributable transcript/caption.
12. `image_primary_incomplete` requires one retained asset plus analyzer
    identity/version/configuration, a required-versus-observed completeness
    ledger, missing/ambiguous evidence IDs, and a closed failure reason. Valid
    partial facts remain JSON-only subordinate evidence and cannot create a
    structured Markdown/DOM primary.
13. `asset_unavailable` requires a closed asset-stage reason and records
    classification, semantic dispatch, and completeness as not run. It emits no
    image URI, no semantic authority, and no dangling reference while
    preserving parse success and existing grounded transcript/caption when safe.
14. State-to-surface mapping is exact: `structured_primary` has one structured
    primary; both image-primary states have one ID/SHA-bound resolvable Markdown
    image reference and one safe `<figure data-item-type="chart"><img>`; and
    `asset_unavailable` has neither image nor structured chart projection. JSON,
    canonical/raw Markdown metadata, and DOM attributes expose the same terminal
    state, owner, order, caption, and accessibility disposition.
15. Asset bytes deterministically decode to the declared safe MIME, dimensions,
    and hash. Unknown MIME, malformed bytes, unsafe URL, hash mismatch, or
    oversized input fails atomically to `asset_unavailable` without breaking the
    rest of the document parse.
16. The capability is independently gated and rollback-safe. The umbrella flag
    governs the complete transaction; inner analyzer flags cannot bypass asset
    custody while it is on. Flag-off output is byte-for-byte predecessor
    behavior. Later advanced enrichment is append-only and records analyzer,
    model/version, configuration, and provenance; only a revision passing the
    same completeness gate may atomically promote image-primary to structured-
    primary. Partial, failed, or conflicting enrichment leaves the prior primary
    and original asset/custody record unchanged.

## Generic-production requirements

- Apply the asset-first stage to every conservatively detected chart owner,
  independent of family support or complexity. Family support controls semantic
  dispatch, not asset retention.
- Production behavior must not branch on a benchmark name/hash/case, page,
  title/labels, owner IDs, expected bboxes, pixel hashes, or fixture-specific
  state/reason lookup.
- Add renamed/reserialized, page-prepended, moved/rescaled, relabeled, revalued,
  panel-reordered, legend-moved, and axis-varied chart fixtures spanning simple,
  mixed bar/marker, bubble/multi-encoding, multi-panel, line, and unsupported
  families.
- Negative/adversarial fixtures include a chart-like table, ACORD form grid,
  Clinical diagram, photograph, logo, decorative grid, overlapping chart/table
  owners, clipped/ambiguous bbox, corrupt page, render timeout, oversized crop,
  pixel/byte caps, hash/MIME mismatch, disagreeing analyzers, and a nonempty but
  incomplete or fabricated chart table.
- Treat every chart-to-table/VLM response as derived evidence until its family
  completeness gate passes. It cannot replace, rerender, or mutate the retained
  source asset.
- Any future detection-family expansion must promote newly affected benchmarks
  into the registry, issue card, and immediate dual-system rerun matrix before
  Ready; they cannot remain labeled controls.

Genericity closure gates:

- [ ] Genericity review records detection, classification, capability,
  completeness, arbitration, transformed-positive, adversarial, and non-chart
  control evidence
- [ ] Production diff/search attestation finds no benchmark/file/hash/case/page/
  owner/string/coordinate/pixel branch, embedded expected output, or oracle leak

## Test and rerun plan

- Terminal-state matrix: supported and complete -> `structured_primary`; no
  approved analyzer -> `image_primary_unsupported`; attempted incomplete,
  ambiguous, timeout, or resource refusal -> `image_primary_incomplete`; unsafe
  crop/hash/MIME/size failure -> `asset_unavailable`.
- Complexity independence: regular and complex complete fixtures both become
  `structured_primary`; regular and complex fixtures without trustworthy
  semantics remain in the appropriate image-primary state. Complexity reasons
  never decide presentation by themselves.
- Transition tests: unsupported-to-image, incomplete-to-image, failed semantic
  promotion back to the unchanged image, successful enrichment promotion to
  structured with identical asset ID/SHA/bbox/bytes, and rollback to the last
  complete public state without partial output.
- Determinism: identical source/configuration produces identical owner, asset,
  family/complexity evidence, hashes, dimensions, transforms, transcripts, and
  canonical references.
- Frontend: image-primary states render exactly one safe image and caption;
  structured-primary renders exactly one structured chart with no image clone;
  asset-unavailable renders no image; all states preserve order, accessibility,
  and nonduplicating transcript custody.
- Suites: P05-US01/03/05, P02-US06, P03 visual relationships/order,
  canonical/public models, serializer, frontend chart/image rendering, asset
  transport, response caps, timeouts, configuration truth table, and atomic
  rollback.

## Immediate affected-benchmark validation (mandatory)

- After the production correction and focused state/transition tests pass, run
  all seven complete affected PDFs through fresh LlamaParse and service jobs.
  Forced state profiles are supplemental evidence and cannot replace the normal
  integrated full-PDF closure runs.
- Preserve source identity, settings, build/job IDs, raw/canonical Markdown,
  full original JSON, actual LlamaParse and Clearleaf DOM/screenshots, every
  exact chart asset and hash, source-page renders, owner/crop overlays,
  family/complexity traces, capability dispatch, completeness ledgers, terminal
  states, primary arbitration, transcript provenance, and complete-output drift
  reports.
- Manually verify every routed chart crop against its source page for complete
  owner coverage, neighbor exclusion, legibility, once-only caption/transcript,
  exact custody, and absence of invented semantics. The focused matrix, not one
  final production run, proves every terminal state and transition.
- Run non-chart controls including `insurance-acord`, `clinical-study`,
  `component-datasheet`, `ny-timetable`, `postal-10k`, `finance-10k`, and
  `purchase-agreement`. Any chart-asset omission, state/schema mismatch,
  duplicate primary, dangling reference, false chart promotion, owner/order
  drift, or out-of-boundary material change returns the card to `In Progress`.
- FFD-015 can close only its asset/classification/arbitration contract. Every
  remaining incomplete or unsupported semantic family stays open under FFD-003
  until its independent source-grounded requirements pass.

## Story and closure

- Story action: **Add source-asset-first chart custody, classification,
  arbitration, and enrichment-lineage ACs to P05-US01/P05-US05 plus
  canonical/frontend projection; make FFD-003 semantic promotion preserve the
  same asset.**
- Production files/tests/artifacts/reviewer: pending Ready; no fix started.
- Closure must satisfy every Definition-of-Done item in `../README.md`, update
  story/evidence/registry/coverage/index, and record independent review.
