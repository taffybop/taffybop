# Final All-15 Functional-Parity Validation Gate

Status: **Mandatory release gate; not yet executed**  
Applies after: **all 23 remediation slices have a final disposition**  
Scope: **functional correctness and output fidelity only**  
Reference baseline: **a fresh LlamaParse run for every benchmark PDF**  
Implementation under test: **the frozen release-candidate build of this service**

This gate is normative. The product must not be described as functionally on
par with LlamaParse until every required capture, comparison, source review,
genericity check, and approval below is complete.

## Gate principles

1. The source PDF is the authority for what exists, where it appears, and what
   relationships are visibly supported. LlamaParse is the requested reference
   baseline, not authority for invented prose, interpolated values, guessed
   arrows, or other content unsupported by the PDF.
2. All 15 PDFs must be parsed again after the last production fix. Historical
   outputs may inform investigation but cannot satisfy this final gate.
3. The exact same source bytes must be submitted to LlamaParse and the service.
   Source identity is established by SHA-256, byte size, and page count.
4. Each side must preserve three independently reviewable surfaces:
   **raw Markdown**, the **actual rendered Markdown UI/DOM**, and the **full
   public JSON response**.
5. A matching aggregate score, a unit-test pass, or a plain-text diff is never
   sufficient. The page-level content, semantics, order, ownership, and
   rendered presentation must be examined.
6. Every production fix must be generic, production-grade, and driven by
   source features. Filename-, hash-, page-number-, benchmark-slug-, fixture-,
   job-ID-, or document-specific production behavior is forbidden.
7. A difference may be accepted only through an explicit, source-grounded
   decision. Silence, deferral, inability to inspect, or a favorable score is
   not acceptance.
8. Before any defect is marked `Done`, every benchmark PDF affected by that
   defect must already have passed its own immediate full-PDF, dual-system
   targeted three-surface validation on the integrated build. Those focused
   runs prove the particular defect and bounded collateral safety; they do not
   replace this final all-15 campaign's broad review.

## Per-defect focused validation precondition

The final campaign is the last integrated release gate, not the first time a
fix is checked against its benchmark PDFs. Immediately after each generic fix
passes focused tests and is available in the integrated validation build, run
every affected benchmark PDF by itself through both LlamaParse and the service
before marking the owning FFD `Done`.

Each focused run must use the same complete source bytes on both sides and
preserve an append-only evidence set containing:

- source SHA-256, byte size, MIME type, and page count;
- fresh LlamaParse raw Markdown, full original JSON bytes, actual rendered UI
  screenshots and DOM/rendered/accessibility evidence where available, plus
  project, profile, job/attempt, settings, and timestamp metadata;
- fresh service raw and canonical Markdown, full original public JSON bytes,
  actual release-frontend post-render DOM and screenshots, plus request/job,
  request profile, backend/frontend build, renderer/browser, viewport, theme,
  font, and timestamp metadata; and
- hashes for every artifact, selected-attempt records, comparator version and
  settings, source-grounded adjudication, reviewer identity, and verdict.

Use the actual LlamaParse UI and the actual integrated product frontend. A
generic Markdown renderer, reconstructed HTML page, unit-test component, or
synthetic screenshot cannot stand in for either rendered UI. If LlamaParse DOM
capture is unavailable, retain its actual UI screenshots and all available
rendered/accessibility evidence and document the limitation.

The defect card must declare the exact page/region/component symptoms, relevant
Markdown/DOM/JSON paths, expected source-grounded result, and bounded
collateral paths reachable from the changed capability. The reviewer manually
compares those targets across every relevant surface. A complete automated
pre-fix/post-fix structural diff must scan the full Markdown, rendered
snapshot/DOM, and JSON outputs; the reviewer also adjudicates every unexpected
changed area. Unchanged, unrelated features in that PDF do not require an
exhaustive manual audit during this per-defect run.

If the symptom remains on a relevant surface, a required artifact is absent,
the relevant surfaces disagree, or the full-output drift scan and bounded
review expose a material collateral regression, the FFD must remain open or
be reopened. Preserve that failed attempt, correct the generic capability, and
run both systems again under a new immutable run ID. Unit and integration
tests, partial-page parses, snapshot-only checks, normalized JSON, similarity
scores, and historical LlamaParse artifacts are insufficient for closure.

This targeted closure check is deliberately narrower than the wave gates and
this final campaign. Wave validation reviews integrated capability-family
drift, and the frozen all-15 campaign performs the broad, page-by-page and
document-level comparison across every required fidelity dimension.

Recommended focused-run layout:

```text
tracker/benchmarks/llamaparse-15/runs/<UTC-run-id>-<FFD-id>-focused/
  run-manifest.json
  source-manifest.json
  reference/<case>/attempt-<n>/
  service/<case>/attempt-<n>/
  comparison/<case>/
  review-verdict.json
```

All successful focused-run manifests and verdicts must be linked from their
FFD cards and the final campaign's `genericity-summary.json`. The final all-15
run remains mandatory after the last fix and must use a newly frozen release
candidate with fresh captures for all cases; focused-run artifacts cannot be
reused as final-campaign rows.

## The 15 required cases

Every row starts `Pending`. No row may inherit a final status from an earlier
campaign.

| Case | Llama raw MD | Llama UI/DOM | Llama JSON | Service raw MD | Service UI/DOM | Service JSON | Source review | Genericity linked | Final status |
|---|---|---|---|---|---|---|---|---|---|
| catastrophe-recap | Pending | Pending | Pending | Pending | Pending | Pending | Pending | Pending | Pending |
| clean-energy | Pending | Pending | Pending | Pending | Pending | Pending | Pending | Pending | Pending |
| clinical-study | Pending | Pending | Pending | Pending | Pending | Pending | Pending | Pending | Pending |
| component-datasheet | Pending | Pending | Pending | Pending | Pending | Pending | Pending | Pending | Pending |
| egov-survey | Pending | Pending | Pending | Pending | Pending | Pending | Pending | Pending | Pending |
| esg-metrics | Pending | Pending | Pending | Pending | Pending | Pending | Pending | Pending | Pending |
| finance-10k | Pending | Pending | Pending | Pending | Pending | Pending | Pending | Pending | Pending |
| health-report | Pending | Pending | Pending | Pending | Pending | Pending | Pending | Pending | Pending |
| insurance-acord | Pending | Pending | Pending | Pending | Pending | Pending | Pending | Pending | Pending |
| manufacturing-report | Pending | Pending | Pending | Pending | Pending | Pending | Pending | Pending | Pending |
| ny-timetable | Pending | Pending | Pending | Pending | Pending | Pending | Pending | Pending | Pending |
| postal-10k | Pending | Pending | Pending | Pending | Pending | Pending | Pending | Pending | Pending |
| purchase-agreement | Pending | Pending | Pending | Pending | Pending | Pending | Pending | Pending | Pending |
| settlement-agreement | Pending | Pending | Pending | Pending | Pending | Pending | Pending | Pending | Pending |
| uber-earnings | Pending | Pending | Pending | Pending | Pending | Pending | Pending | Pending | Pending |

Allowed final case statuses are:

- `match` — no substantive cross-system difference remains.
- `fixed` — a previously tracked discrepancy is corrected and the fresh run
  passes every affected surface and control.
- `acceptable_difference` — the outputs differ, but a named reviewer approved
  a bounded source-grounded rationale and confirmed no user-visible or
  downstream functional loss.
- `discrepancy_found` — at least one material or unadjudicated difference
  remains. This status fails the release gate.
- `blocked` — a required output, source oracle, capture, or review is missing.
  This status fails the release gate.

The final report must record a status and a concise rationale for every PDF,
including the three cases previously marked fixed and the previously accepted
Settlement difference. Those earlier dispositions remain regression history,
not final-run exemptions.

## Freeze and rerun procedure

### 1. Freeze the release candidate

Before the first submission, record:

- repository commit and dirty-tree diff hash, or an immutable source archive
  hash when no commit represents the build;
- service build/image identifier, dependency lock hashes, feature flags,
  extraction profile, OCR/chart/diagram settings, and public API version;
- frontend commit/build identifier, Markdown renderer and sanitization
  configuration, browser name/version, viewport, device scale, theme, and
  relevant fonts;
- LlamaParse project, parser settings, requested output options, UI version if
  exposed, and any model/parser version exposed by the service; and
- UTC run ID, operator, reviewer, host/environment identity, and start time.

No production behavior or comparison rule may change after this freeze. If it
does, invalidate the campaign and begin a new all-15 run under a new run ID.

### 2. Establish source custody

For each case, record its canonical filename only as metadata—not as an
extraction input—plus SHA-256, byte size, MIME type, page count, and canonical
source path. Confirm that the bytes submitted to both systems have the same
hash. Preserve source-page renders used during adjudication with renderer and
resolution metadata.

A source mismatch, substituted page range, or partial-PDF parse invalidates
that case. Every submission must contain the complete PDF.

### 3. Run LlamaParse fresh

Submit each full PDF to LlamaParse after the freeze. For every attempt,
preserve:

- request/settings metadata, submission timestamp, project ID, parse/job ID,
  terminal status, completion timestamp, and output URLs or identifiers;
- the full original JSON response bytes, without field removal or reordering;
- the raw Markdown bytes exactly as downloaded or returned;
- the actual LlamaParse rendered Markdown UI as displayed, including
  full-page screenshots and a DOM/rendered representation where the browser
  permits capture; and
- all referenced image/asset outputs needed to reproduce the displayed result.

Do not overwrite a failed, retried, or superseded attempt. Select one complete
attempt explicitly in the manifest and preserve the reason for selection. If
the UI DOM is inaccessible, preserve the actual UI screenshots, an accessible
tree or rendered snapshot, the raw Markdown used by the UI, and a documented
limitation. An absent view with no equivalent visual evidence is a blocker.

### 4. Run the release-candidate service fresh

Submit the same full-PDF bytes with the frozen public request settings. For
every attempt, preserve:

- request ID/job ID, request metadata, timestamps, terminal status, HTTP
  status, response headers relevant to representation, and build identity;
- the full original public JSON response bytes before normalization;
- raw Markdown returned by the service and canonical full Markdown as separate
  byte-preserved files; they must be byte-identical unless a reviewed public
  contract explicitly distinguishes them;
- the actual Clearleaf UI rendered from that result: serialized post-render
  DOM, accessibility tree where available, full-page and page/region
  screenshots, browser console errors, and referenced assets; and
- any source-grounded diagnostic/evidence sidecars needed to adjudicate the
  public result, without treating private sidecars as substitutes for missing
  public content.

Do not synthesize a service UI from the Markdown in a different renderer. The
actual release-candidate frontend and its production Markdown pipeline must be
used.

### 5. Preserve immutable artifacts

Use a new append-only root such as:

`tracker/benchmarks/llamaparse-15/runs/<UTC-run-id>-final-all-15/`

Recommended layout:

```text
run-manifest.json
source-manifest.json
reference/<case>/attempt-<n>/
service/<case>/attempt-<n>/
comparison/<case>/
genericity/<FFD-id>/
approvals/
final-status.json
consolidated-report.md
```

The manifest must hash every source and captured artifact, identify selected
attempts, and record all settings and identities required to reproduce the
run. Credentials and tokens must not be stored. A corrected or regenerated
artifact receives a new path and hash; it never replaces the original.

## Required per-PDF comparison

Each case receives a page-by-page and document-level review. Automated
comparators should locate differences, but the final verdict must be based on
the source PDF, both public outputs, and both rendered presentations.

### Document structure and order

Compare page sequence and association; headings and levels; sections;
paragraphs; lists and nesting; captions; footnotes; headers/footers/running
regions; callouts; columns; grouping; and the reading order within and across
pages. Record missing, added, truncated, duplicated, or incorrectly ordered
content and any ownership conflict between prose, table, form, image, chart,
or diagram components.

### Text, OCR, and source integrity

Compare exact text, Unicode, punctuation, whitespace that changes meaning or
rendering, ligatures, superscripts/subscripts, emphasis, links, code spans and
blocks, line/word joining, and repeated content. Review OCR originating from
scans, images, figures, charts, diagrams, or embedded visual content for
recognition, rotation, fusion, omission, duplication, order, confidence, and
source attribution. Content unsupported by the PDF is a defect even when it
matches the LlamaParse output.

### Tables and merged cells

For every visible table or table-like region, compare detection, semantic
ownership, page and document order, row/column count, headers, row and column
order, every cell value, empty cells, row/column spans, merged-cell behavior,
multi-page continuation, footnotes, captions, and serialization. Inspect the
raw Markdown representation, the rendered table layout/alignment, and JSON
cell coordinates/span metadata. A visually plausible table with shifted cells
or lost span semantics does not pass.

### Forms

Compare form detection, field labels, values, check/radio state, groups,
sections, key/value association, source order, repeated labels, blank fields,
and table-versus-form ownership. Confirm the same meaning is available in
Markdown, UI, and public JSON without duplication.

### Charts and graphs

Compare chart detection and placement; panel boundaries and order; title,
caption, source note, axes, units, ticks, legend, categories, series, printed
labels/values, and the association of marks to labels. Distinguish printed or
source-provable values from interpolated or invented values. Compare the
semantic JSON representation and the Markdown/UI presentation, including
once-only placement relative to surrounding content.

### Diagrams and visual models

Compare detection and placement; nodes, labels, containers, groups,
connectors, endpoints, directionality, undirected associations, and visible
topology. Every emitted relationship must close over source evidence. Spatial
proximity or plausible language alone cannot justify a connector or edge.

### Images and image-derived content

Compare image detection, page association, bounding placement, reading order,
caption/source-note custody, alt or semantic description where applicable,
and OCR derived from the image. Confirm that photographs, logos, decorative
content, charts, diagrams, and forms are not misclassified or duplicated, and
that diagnostic OCR does not leak into primary Markdown/UI unless the public
contract calls for it.

### Markdown and rendered presentation

Compare raw Markdown syntax and hierarchy, whitespace where it affects
rendering, escaping, links, emphasis, lists, code blocks, tables, images, and
component order. Then inspect the actual rendered UIs side by side for visual
structure, order, grouping, alignment, indentation, spacing, table geometry,
line wrapping where meaningful, captions, image placement, and accessible
semantics. A raw-text match cannot waive a rendered-UI regression, and a
similar screenshot cannot waive malformed Markdown or DOM.

### Full public JSON

Compare the full response schemas as well as values: component types, page
association, stable ordering, nesting, identifiers, fields, null/empty
semantics, coordinates, spans, evidence/provenance, extracted content,
relationships, and serialized representation. Preserve original byte streams
and separately produce normalized/semantic comparison views; normalization
must never replace or modify the original response.

## Discrepancy record and adjudication

Every observed difference must have a stable record containing:

- case, source hash, physical and printed page, bounded source region, output
  surface, and severity;
- exact LlamaParse result, exact service result, source-PDF finding, and
  reproducible artifact pointers or JSON/DOM selectors;
- screenshots or crops when rendering, layout, visual content, or OCR is at
  issue;
- classification as harmless presentation difference, acceptable functional
  difference, functional regression, or source-unsupported baseline behavior;
- owning FFD/story, fix or acceptance decision, reviewer, timestamp, and
  rationale; and
- confirmation of whether the manifestation is primary or correlated with an
  already tracked root cause.

A material discrepancy includes any missing, false, duplicated, truncated, or
misordered meaning; incorrect table/form ownership or cell/span ordering;
material OCR corruption; incomplete or invented chart/diagram semantics;
wrong image/caption placement; malformed or misleading Markdown/UI; or wrong
JSON type, page association, nesting, order, relationship, or public content.

An `acceptable_difference` requires a signed decision naming its precise
scope and demonstrating from the PDF that it is harmless, equally functional,
or more source-faithful than the baseline. Approval must identify the product
owner or designated reviewer, source evidence, affected surfaces, downstream
impact review, and expiry/revisit condition if any. It cannot cover a class of
unknown differences.

## Genericity and production-grade gate

Every resolved FFD card must link a genericity packet under
`genericity/<FFD-id>/`. The packet is mandatory even when the benchmark case
passes and must contain:

Before a remediation slice may enter `In Progress`, its issue card must define
items 1–3 and the planned tests for items 4–7 below. The implementation review
must reject the design before code is changed if its behavior is activated by
document identity rather than reusable source evidence. Results for all ten
items are then required before the slice or final campaign can close.

1. **Capability invariant:** a plain-language rule describing the source
   feature and expected behavior independently of any benchmark document.
2. **Activation evidence:** the structural, geometric, typographic, content,
   or model evidence used by the implementation. A benchmark identity is not
   valid activation evidence.
3. **Forbidden-key audit:** code and configuration review showing no branch,
   allowlist, prompt, regex exception, lookup, threshold override, or fixture
   dependency keyed to PDF filename, path, SHA/hash, case slug, title, customer
   text, Llama job ID, hard-coded page number, element ID, or benchmark-only
   coordinates.
4. **Focused regression:** a failing-before/passing-after test at the reusable
   capability boundary, not merely a golden assertion against the complete
   benchmark output.
5. **Variation evidence:** tests that vary identity and layout as applicable,
   such as renaming the file, prepending a page to shift page numbers,
   translating/scaling the target region, changing neighboring content,
   altering row/column counts or merged spans, rotating text, or changing font
   and image resolution. The applicable perturbations must still pass without
   code changes.
6. **Cross-document evidence:** at least one related positive on a different
   document structure and one unrelated non-target proving the fix neither
   overfires nor regresses adjacent content. Prefer a previously unseen or
   purpose-built fixture in addition to benchmark controls.
7. **Negative/adversarial evidence:** ambiguous, malformed, incomplete, or
   source-unsupported input fails closed instead of generating plausible
   content or relationships.
8. **Surface consistency:** the reusable result reaches JSON, canonical/raw
   Markdown, and the actual UI consistently; the frontend does not contain a
   benchmark-specific repair.
9. **Operational quality:** error handling, schema validation, deterministic
   ordering, and backward-compatibility review appropriate to the changed
   capability. Performance work remains out of scope unless it prevents
   correct completion.
10. **Independent review:** a reviewer records changed files, test commands,
    results, control PDFs, remaining limits, and a direct conclusion that the
    correction is generic and production-grade.

The final run must include a `genericity-summary.json` mapping every resolved
FFD and production change to this evidence. The all-15 benchmark demonstrates
fidelity on the benchmark set; the genericity packets demonstrate that the
implementation rule is intended and tested for new PDFs. Neither substitutes
for the other.

At campaign review, the genericity summary must also show the applicable
variation coverage below. A fix need not implement an unrelated capability,
but it must pass the rows its changed code can affect.

| Capability | Minimum varied-document evidence |
|---|---|
| Document structure | Different page counts, section depths, single/multi-column layouts, sidebars, and repeated regions without document-specific ordering rules |
| Reading order | Main text, columns, captions, callouts, headers/footers, and visual owners reordered from source geometry/relationships rather than known phrases or pages |
| Tables and merged cells | Bordered and borderless tables, empty cells, row/column spans, repeated headers, and changed row/column counts with exact cell ordering |
| Forms | Key/value, grouped fields, check/radio states, blanks, and form/table boundary negatives |
| Images | Photographs, logos, decorative images, image captions, and image-versus-chart/diagram/form classification controls |
| OCR content | Native, scanned, rotated, multilingual/Unicode, low-resolution, fused, and duplicate candidates with attributable fail-closed selection |
| Charts and graphs | Bar, line, combination, and multi-panel layouts with changed labels/scales and explicit printed-versus-inferred value controls |
| Diagrams and visual models | Directed flow, undirected grouping, containment, and engineering/pinout layouts with missing/ambiguous connector negatives |
| Formatting and UI | Headings, lists, links, emphasis, code, whitespace, table rendering, sanitization, accessibility, and responsive/viewport presentation controls |

## Required artifact checklist

The final campaign is incomplete unless all boxes can be evidenced.

### Campaign level

- [ ] Frozen backend/frontend build identity and dirty-tree/archive hash.
- [ ] Source manifest with 15 SHA-256 hashes, byte sizes, MIME types, and page counts.
- [ ] LlamaParse and service settings/configuration snapshots.
- [ ] Browser/renderer environment and capture settings.
- [ ] Append-only manifest with hashes for every captured artifact.
- [ ] Selected-attempt ledger retaining all failures and retries.
- [ ] Comparator version/command/configuration and deterministic output.
- [ ] Genericity summary covering every resolved FFD and production change.
- [ ] Every resolved FFD links successful immediate complete-input targeted
      runs, including immutable manifests, declared defect/collateral scope,
      relevant three-surface findings, complete-output drift reports, and
      reviewer verdicts; failed and retried attempts remain preserved.
- [ ] Named independent reviewer and review timestamps.

### Each of 15 PDFs

- [ ] Fresh complete LlamaParse job ID and successful terminal status.
- [ ] LlamaParse full original JSON response.
- [ ] LlamaParse raw Markdown bytes.
- [ ] Actual LlamaParse rendered UI screenshots and DOM/rendered evidence.
- [ ] Fresh complete service request/job ID and successful terminal status.
- [ ] Service full original public JSON response.
- [ ] Service raw Markdown and canonical Markdown with parity result.
- [ ] Actual Clearleaf post-render DOM, screenshots, assets, and console result.
- [ ] Page-by-page structured comparison across every required dimension.
- [ ] Source-PDF adjudication for every nontrivial difference.
- [ ] Per-surface verdict for Markdown, rendered UI/DOM, and JSON.
- [ ] Final case status, rationale, linked FFDs, approvals, and reviewer.

### Consolidated result

- [ ] All 15 rows have a non-pending final status.
- [ ] All material discrepancies are fixed or explicitly approved as acceptable.
- [ ] All accepted differences have bounded source-grounded approval records.
- [ ] No open or unadjudicated FFD affects the release candidate.
- [ ] No regression is present in previously fixed or accepted control cases.
- [ ] Final comparator, manifests, per-case evidence, approvals, status JSON,
      and consolidated report are preserved and cross-linked.
- [ ] Genericity evidence passes for every fix; no forbidden benchmark-specific
      production rule exists.

## Non-negotiable failure conditions

The gate fails, and the product remains not ready, if any of the following is
true:

- even one of the 15 PDFs lacks a fresh complete run through either system;
- source bytes differ between systems, only selected pages were parsed, or
  source identity cannot be proven;
- any raw Markdown, actual rendered UI/DOM evidence, or full public JSON
  response is missing, stale, truncated, overwritten, or not tied to a job ID;
- the service output was produced by a different build/configuration from the
  frozen release candidate, or production behavior changed mid-campaign;
- a case is `discrepancy_found`, `blocked`, or still `Pending`;
- a material discrepancy remains unresolved or lacks an explicit bounded
  source-grounded acceptance approval;
- an approval relies only on LlamaParse behavior, a similarity score, or lack
  of time rather than the source PDF and user/downstream impact;
- public JSON is invalid/incomplete, raw and canonical Markdown violate their
  declared contract, or actual UI rendering was not inspected;
- a table, merged cell, form field, chart/diagram relationship, image-derived
  label, OCR token, reading-order relationship, or component ordering remains
  materially wrong on any reviewed surface;
- matching LlamaParse requires content unsupported by the source PDF;
- any fix depends on a filename, hash, path, benchmark slug, title/customer
  phrase, page number, job ID, fixed benchmark coordinate, or other
  document-specific production exception;
- any resolved fix lacks the required genericity packet, cross-document
  controls, variation test, or negative/adversarial evidence;
- any resolved FFD lacks a successful immediate complete-input dual-system
  targeted run on the integrated build, or that run lacks immutable raw
  Markdown, actual rendered UI/DOM evidence, full original JSON, hashes,
  profiles, job/request IDs, build identities, a declared defect/collateral
  boundary, complete-output drift scan, targeted review, or a named verdict;
- a failed per-defect focused run was overwritten, ignored, or closed without
  correcting the generic capability and repeating both systems under a new
  run ID;
- a unit/integration test result or aggregate comparator score is offered in
  place of fresh JSON, Markdown, and rendered-UI evidence; or
- the artifact manifest, reviewer decision, per-case status, or consolidated
  release report is incomplete.

On failure, preserve the campaign as evidence, reopen or create the owning FFD
and story, correct the generic capability, and execute a new all-15 campaign
after the next release-candidate freeze. Do not patch final artifacts or reuse
successful rows from the failed campaign as the next final gate.

## Required release declaration

Only when every gate above passes may the consolidated report use this
declaration:

> **Functional parity gate: PASSED.** Under run `<run-id>` on `<UTC-date>`, the
> frozen release-candidate service is functionally on par with the selected
> fresh LlamaParse baseline for all 15 benchmark PDFs across raw Markdown,
> actual rendered Markdown UI/DOM, and full public JSON. Document structure and
> reading order, text/OCR integrity, tables and merged cells, forms,
> charts/diagrams, images and image-derived content, formatting, visual
> presentation, and JSON component ordering were reviewed against the source
> PDFs. All material discrepancies were resolved or explicitly approved as
> acceptable, all artifacts were preserved, and every production fix passed
> its genericity and non-benchmark-specific evidence gate.

If any condition does not pass, the report must instead state:

> **Functional parity gate: FAILED — NOT RELEASE READY.** The service must not
> be described as functionally on par with LlamaParse. See the named failing
> cases, surfaces, open FFDs, missing evidence, or genericity failures below.

This declaration is bounded to the documented 15-PDF campaign and the frozen
configuration. It does not excuse benchmark-specific logic or claim perfect
behavior for every possible PDF; production-grade applicability to new PDFs is
supported by the separate genericity evidence required for every correction.
