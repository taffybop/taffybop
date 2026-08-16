# Generic Production Remediation Policy

Status: **Mandatory for every functional-fidelity defect**  
Applies to: **production code, prompts, configuration, schemas, renderers, and
post-processing changed for this tracker**

## Purpose

Every correction must improve a reusable parsing capability for new and
previously unseen PDFs. A benchmark document may expose and prove a defect, but
it must never become the condition that activates the correction. Passing the
15-PDF benchmark by recognizing its fixtures is not functional fidelity and
does not satisfy this tracker.

This policy is a release gate. If a proposed change cannot meet it, the defect
remains open until a generic design is available or the remaining gap is
explicitly approved as acceptable.

## Non-negotiable production prohibitions

Production behavior must not branch on, look up, special-case, or otherwise
depend on any of the following:

- PDF filenames, filesystem paths, upload names, document titles used as
  fixture identifiers, or benchmark case IDs.
- Source-file hashes, byte signatures used to recognize a benchmark fixture,
  LlamaParse job IDs, or benchmark/reference artifact paths.
- Fixed physical page numbers, printed-page labels unique to a fixture, or
  stable element/node/component IDs observed only in benchmark output.
- Exact benchmark strings, captions, table values, chart labels, coordinates,
  bounding boxes, or coordinate ranges used as activation rules.
- Prompts, examples, retrieval entries, mapping tables, or caches that look up
  or reproduce a benchmark's expected answer.
- Memorized Markdown, JSON, DOM, OCR text, table cells, chart values, diagram
  relationships, or LlamaParse output for a known document.

The prohibition includes indirect forms such as encoded hashes, normalized or
substring filename matches, arrays of known benchmark phrases, combinations of
page number and coordinates, or a general-looking condition whose constants
identify one fixture in practice.

Fixture-specific names, hashes, page numbers, text, coordinates, job IDs, and
artifact paths are allowed **only** in test fixtures, assertions, evidence,
benchmark manifests, and tracker documentation. They must not be imported,
generated into, bundled with, or read by production runtime code.

This rule applies to the complete production path after remediation, not only
to lines added by the current fix. Before implementation, inspect the affected
and dependent path for pre-existing prohibited logic. Any existing fixture
recognizer, coordinate/string exception, expected-output lookup, or benchmark
gate in that path must be removed or generalized and covered by the same
variant/adversarial tests before the defect can close. Historical behavior or
snapshot compatibility is not an exemption. The initial known finding is
recorded in [`pre-remediation-genericity-audit.md`](pre-remediation-genericity-audit.md).

## Required implementation shape

Each remediation must define a **reusable capability contract** before code is
changed. The contract must state:

1. The observable document feature being handled, such as spatial ownership,
   reading-order precedence, row/column geometry, merged-cell topology,
   image-derived text provenance, chart-series association, connector
   topology, form grouping, or Markdown serialization.
2. The invariant or bounded algorithm that recognizes that feature independent
   of document identity.
3. The expected behavior on raw Markdown, public JSON, and rendered DOM,
   including page association, order, nesting, and provenance.
4. Ambiguity limits and fail-closed behavior. When evidence is insufficient,
   the system must preserve attributable source content or emit a bounded
   unresolved representation; it must not invent text, values, cells, links,
   arrows, hierarchy, or semantic relationships.
5. The malformed or partial inputs that the bounded change must handle safely.
6. Compatibility boundaries, deployment flag, and rollback path where the
   change alters shared extraction, ordering, serialization, or rendering.

Implementations must be bounded, deterministic for the same inputs and
configuration, reviewable, and provenance-preserving. Extracted or inferred
content must remain traceable to its page and source region/component. Shared
rules must have explicit tie-breaking and must not silently discard content.

This is a functional and output-quality policy. It requires safe behavior for
malformed inputs that exercise the changed boundary, but it does not expand the
benchmark into exhaustive security hardening, performance, latency, CPU, or
memory work unless such a problem directly prevents correct parsing or output.

## Required genericity tests

A benchmark reproduction is necessary but insufficient. Each remediation must
also include all applicable controls below:

- **Positive variants:** at least two structurally relevant variants that do
  not copy the triggering fixture's complete content. Vary layout, wording,
  dimensions, font, spacing, row/column count, visual placement, or topology as
  appropriate to the capability.
- **Identity independence:** rename the triggering PDF and confirm identical
  behavior; where applicable, reorder documents in a batch and insert/remove
  leading pages so the target content moves to a different page offset.
- **Negative controls:** documents that resemble the trigger superficially but
  do not satisfy the capability invariant must not be transformed.
- **Adversarial/ambiguous controls:** incomplete geometry, overlapping regions,
  malformed tables, uncertain OCR, disconnected connectors, or conflicting
  ordering evidence must take the documented fail-closed path.
- **Unrelated-PDF controls:** run at least two unrelated PDFs, including one
  previously correct or accepted benchmark, to detect shared-pipeline drift.
- **Cross-surface contract:** public JSON/schema, canonical/raw Markdown, and
  rendered DOM must agree on content, order, grouping, page association, and
  provenance. A correction on only one surface is incomplete unless the
  capability contract explicitly proves the other surfaces are unaffected.

For fixture-dependent formats such as forms, tables, or charts, synthetic test
fixtures are encouraged when they isolate the invariant. Their values must
differ from the benchmark values, and they must not encode a lookup route back
to expected benchmark output.

## Immediate affected-PDF closure validation

After a production fix passes its focused automated tests and reaches the
integrated validation build, every benchmark PDF named as affected by that
defect must be validated immediately, one complete PDF at a time, before the
defect can be marked `Done`. Do not defer this check to the final all-15
campaign, and do not submit only the pages or regions that exposed the issue.

For each affected PDF, run the exact same full source bytes freshly through
both LlamaParse and the integrated service build. Preserve, without rewriting
or normalizing the originals:

- LlamaParse raw Markdown bytes, full original JSON response bytes, and the
  actual LlamaParse rendered Markdown UI as screenshots plus DOM/rendered or
  accessibility representation where capture is available;
- service raw and canonical Markdown bytes, full original public JSON response
  bytes, and the actual product UI as post-render DOM plus full-page and
  affected-region screenshots; and
- source SHA-256/size/page count, hashes of every captured artifact, parser and
  request profiles, LlamaParse project/job/attempt identifiers, service
  request/job identifiers, backend and frontend build identities, browser and
  renderer settings, timestamps, and the selected-attempt decision.

The product UI must be rendered by the integrated production frontend and its
real Markdown pipeline. A generic Markdown previewer, test renderer, generated
HTML approximation, or screenshot reconstructed from raw Markdown is not UI
evidence for either system. When LlamaParse does not expose its DOM, retain the
actual LlamaParse UI screenshots and every available rendered/accessibility
representation, and record the limitation; do not substitute another
renderer.

The focused comparison must prove both of the following:

1. **Issue resolution:** the exact pages, regions, components, selectors, and
   cross-surface symptoms recorded in the defect now satisfy the approved
   source-grounded expectation in raw Markdown, actual rendered UI/DOM, and
   full public JSON wherever the defect can be represented. A surface may be
   `not_applicable` only with a capability-contract rationale.
2. **Bounded collateral integrity:** automated structural diffs over the
   complete pre-fix and post-fix Markdown, rendered snapshot/DOM, and JSON show
   all changes. The reviewer manually checks the declared defect paths,
   collateral paths reasonably reachable from the changed capability, and
   every unexpected changed area. Unchanged, unrelated document features do
   not require manual re-review at this per-defect gate.

Automated diffs and snapshots may locate changes, but a named reviewer must
adjudicate the affected symptoms, declared collateral paths, and every
unexpected change against the source PDF and both systems. The defect card
must declare these target and collateral boundaries before capture. Store each
attempt under a new, append-only run ID and link its manifest and verdict from
the defect card. Failed and superseded attempts remain immutable evidence.

If any affected symptom remains unresolved on a relevant public surface, a
required artifact is missing, or the drift scan and bounded review expose a
new material regression elsewhere in the PDF, the defect stays open (or is
reopened). Record the failure, correct the generic capability, and repeat the
full dual-system targeted run under a new run ID. Unit/integration tests,
component snapshots, normalized JSON, a text-similarity score, or parsing only
the affected page cannot satisfy this closure gate.

This immediate focused validation is a per-defect closure gate. It does not
require an exhaustive manual audit of unchanged, unrelated features in the
same PDF. It does not replace broad wave-level drift review or the independent
final all-15 validation on the frozen release candidate after all remediation
is complete.

## Genericity Definition of Ready

A defect is not `Ready` until its card records all of the following:

1. A capability contract naming the reusable document feature and invariant;
   “make benchmark PDF/page match” is not a valid contract.
2. The planned production decision inputs, none of which identify a fixture.
3. The ambiguity boundary and expected fail-closed output, including how source
   provenance and uncertain content are retained.
4. At least two positive variant cases with materially varied identity/content
   or structure.
5. A rename test, and applicable batch-reorder and page-offset tests.
6. At least one negative and one adversarial case that exercise the proposed
   discriminator without qualifying for the correction.
7. At least two unrelated-PDF controls and the affected family/all-15 rerun
   obligation.
8. Assertions covering public JSON/schema, raw/canonical Markdown, and rendered
   DOM consistency.
9. A bounded production change surface, deterministic tie-breaking, and a
   flag/rollback decision where relevant.
10. A planned pre-implementation repository search for prohibited fixture
    identifiers in the proposed production surface, including inherited and
    dependent code rather than only the planned diff.

## Genericity Definition of Done

A defect is not `Done` until the closure evidence proves all of the following:

1. The implementation satisfies the recorded capability contract without
   branching on any prohibited identifier.
2. The original source-grounded reproduction and every positive variant pass.
3. Rename independence passes; applicable batch-reorder and page-offset cases
   also pass without changed semantics.
4. Negative and adversarial cases do not receive an unsupported transformation
   and take the documented fail-closed path.
5. At least two unrelated PDF controls pass, along with the named shared-family
   suite and required all-15 drift gate.
6. Public JSON validates against its schema, and JSON, canonical/raw Markdown,
   and rendered DOM agree on content, page/order, grouping, and provenance.
7. No content or semantics unsupported by the source were invented, copied from
   LlamaParse, or recovered from a benchmark-specific answer store.
8. The production diff is reviewed for suspicious constants and fixture
   knowledge, and a repository search over production code finds no triggering
   PDF names, hashes, case IDs, page-specific keys, exact benchmark strings or
   coordinates, Llama job IDs, or artifact paths. The commands and results are
   recorded in the defect card. Pre-existing prohibited logic in the affected
   or dependent capability path has also been removed or generalized.
9. Determinism and safe handling of malformed inputs at the changed boundary
   are covered by tests.
10. Any applicable rollout flag and rollback path are documented and exercised
    or explicitly reviewed as not required.
11. Every affected benchmark PDF has passed the immediate complete-input,
    dual-system targeted closure validation above on the integrated build; its
    immutable manifest, source and artifact hashes, profiles, job/request IDs,
    build and browser identities, declared defect/collateral boundaries,
    relevant three-surface findings, complete-output drift scan, reviewer
    verdict, and all failed/retried attempts are linked from the defect card.

Fresh LlamaParse parity for a benchmark is evidence of fidelity, not evidence
of genericity by itself. Unit tests, snapshot equality, or an all-15 pass cannot
waive any genericity gate above.

## Review procedure

Before approval, the reviewer must inspect both the production diff and the
search results recorded in the issue card. The review must answer:

- Would the correction still activate if the PDF were renamed, moved to a
  different page, and populated with different text or values while retaining
  the relevant structure?
- Would a superficially similar but structurally different document remain
  unchanged or fail closed?
- Can every emitted token, cell, relationship, and ordering decision be traced
  to source evidence or an explicit generic invariant?
- Are all three public surfaces consistent, and can the change be disabled or
  reverted safely if it affects a shared boundary?
- Does the linked immediate affected-PDF run use fresh full-PDF outputs from
  both systems and the actual product UIs, and does it prove the recorded
  symptom plus bounded collateral integrity on the integrated build?

Any “no” or unproven answer blocks closure.
