# P01 Canonical Presentation Policy

Status: Accepted  
Date: 2026-07-29  
Applies to: P01-US03 and P01-US04

## Decision

P01-US03 exposes one optional top-level `canonical_presentation` object behind
`PARSER_CANONICAL_SERIALIZATION_ENABLED`. Its contract version is `1.0` and it
is derived exactly once from the already-normalized `DocumentIR`.

Canonical serialization requires both
`PARSER_SHARED_IR_NORMALIZATION_ENABLED=true` and
`PARSER_SHARED_IR_ENABLED=true`. Invalid partial enablement fails settings
validation. When the canonical flag is false, the field is absent, the public
v1 pages and items remain byte-compatible, and the legacy Markdown serializer
is unchanged.

The additive object is validated by strict presentation models, including
strict scalar types that reject coercion, but remains an optional runtime
extension to the existing permissive `ParseResult`. This keeps the Phase 0
OpenAPI and required-field schema pins stable during the default-off rollout.
The nested contract declares its own version and is documented and tested
directly.

## Contract

The object contains:

- `schema_version`: canonical presentation contract version `1.0`;
- `source_ir_version`: the IR version used to build it;
- `policy_id`: `canonical-presentation-v1`;
- ordered page records;
- strict page blocks;
- page-level `full`, `body`, `header`, and `footer` views;
- document-level `full`, `body`, `header`, and `footer` views.

Each block records a stable block ID, page ID, primary element ID and type,
scope, Markdown, semantic text, contributing element IDs, asserting
relationship IDs, excluded contributions with reasons, and an optional block
omission reason. Every non-`READING_BEFORE` relationship assertion incident to
a represented element is retained on an included block for audit, even when it
is evidence-only. `READING_BEFORE` remains excluded from block-level assertion
audit because presentation anchor order is authoritative in this story.
Omitted blocks remain in the page record for auditability but do not enter any
rendered view.

Each view records its ordered block IDs, Markdown, and semantic text. Nonempty
rendered views end with exactly one newline. Blocks have no surrounding blank
lines. Document views concatenate page block order directly and add no
synthetic page markers.

## Ordering and identity

`PageRecord.presentation_element_ids` is the only anchor order. P01-US03 does
not geometrically reorder content; relationship-aware reading-order repair
remains P03-US04.

A presented element ID may contribute to at most one included block. Attachment
claims are allocated in page and anchor order, then relationship type, source
order metadata, and relationship ID. Equivalent assertions with distinct
relationship IDs coalesce into one contribution while retaining every
assertion ID.

Structured owners resolve their declared children recursively. Rendering uses
only the children actually claimed by that root block; rejected, shared, or
alternate descendants are redacted without text subtraction. A descendant's
identity and all of its non-ordering assertions remain auditable even when its
content is excluded.

Suppression is based on element and relationship identity, never equal text.
Distinct equal-text elements therefore remain present unless an explicit
relationship or the narrow diagnosed-table rule below declares an alternate
representation.

## Type and relationship rules

### Captions, notes, and footnotes

- `CAPTION_OF` is child to owner. A nonempty, source-supported caption is placed
  before the owner body and claimed once.
- Native, vector, embedded, recovered, and model evidence are
  source-supported. OCR-only captions are eligible only when the owner
  explicitly permits subordinate OCR; an explicit false value rejects them.
- A claimed caption takes precedence over subordinate OCR. OCR from that owner
  remains evidence and is recorded as excluded from primary presentation.
- `SOURCE_NOTE_OF` and `FOOTNOTE_OF` contributions follow the owner body in
  stable relationship order. Attachments on nested structured children are
  proxied to the root presentation block while retaining bridge identity.
- Legend, axis, annotation, reference, diagnostic, and rejected-alternative
  nodes remain evidence-only in this story unless they are independently
  ordered primary elements.

### Visuals

`image`, `chart`, and `diagram` share one rule:

1. use eligible related caption content;
2. otherwise use accepted subordinate OCR only when the owner explicitly
   permits it;
3. for direct `image` elements that are not layout `content_region` visuals,
   accepted OCR is permitted unless explicitly disabled; `chart` and
   `diagram` owners still require explicit permission;
4. never use a flattened legacy visual Markdown/value as an implicit fallback;
5. omit an empty or unsupported OCR-only visual with an explicit
   `empty_visual` or `unsupported_primary_ocr` reason.

The same precedence applies to visuals nested under lists, tables, forms,
key-value groups, headers, and footers: eligible caption, then allowed OCR,
then source notes and footnotes, otherwise an explicit omission. Flattened
parent content is never accepted as a substitute for the nested visual's
identity or relationship evidence.

This makes the Uber photograph's rejected OCR caption, unapproved logos, and
caption-plus-OCR chart variants deterministic without deleting their legacy
JSON evidence.

### Tables

Table Markdown prefers the element's span-capable HTML representation. It never
converts a span-bearing table to a pipe table. Semantic text is derived from
structured rows/value exactly once using row and cell boundaries; HTML is not
stripped to invent text.

When only selected table children may render, cells are mapped by positional
identity rather than equal text. Row and column spans are validated strictly:
booleans, non-integers, zero, negative values, and span-bearing non-HTML
fallbacks fail with contextual errors.

One narrowly bounded alternate rule is allowed for the reviewed health-report
false table: a table carrying the existing
`contains_empty_visual_rows` extraction concern is omitted only when at least
90% of its bbox overlaps a preceding `image`, `chart`, or `diagram` bbox on the
same page. The omitted block records the suppressing element ID and
`overlapping_visual_table`. No other cross-primary bbox or text heuristic is
permitted.

### Headers, footers, lists, and prose

- Nonempty primary `header` and `footer` anchors are included in the full view
  and their declared scope view; the body view excludes them explicitly.
- Header/footer child elements are claimed into their owner block once.
- Layoutless header/footer owners reconstruct Markdown and semantic text from
  their selected fragments. An authoritative atomic header/footer value that
  also contains a visual child is rejected until segmented layout provenance
  can identify which content belongs to which child; equal-text subtraction is
  forbidden.
- List children and structured fields represented by their owner are listed as
  contributors rather than emitted again. Lists, tables, forms, and key-value
  groups recursively reconstruct output from selected descendants so rejected
  or already-claimed children cannot leak through a flattened parent value.
- Headings, prose, code, formulas, and other body elements use their typed
  element value/Markdown rules and stay in anchor order.

### Alternatives, sharing, and malformed input

- The source of `ALTERNATIVE_OF` is an alternate and is omitted only when a
  target resolves to a presented block. Edges to omitted targets retain the
  source. Chains resolve to their final presented representative; malformed
  cycles retain the earliest anchor and audit every direct assertion.
- A shared contribution is claimed by the first eligible owner; later claims
  record `already_claimed` without repeating content.
- Duplicate relationship triples coalesce deterministically and preserve all
  relationship IDs.
- Empty visuals, conflicting caption/OCR, duplicate assertions, unsupported
  primary OCR, and consumed primary anchors produce explicit deterministic
  inclusion/exclusion outcomes.
- If `canonical_presentation` is present but malformed or uses an unsupported
  version, the backend serializer fails rather than silently falling back.

## Fixtures and reviewed differences

The immutable P00-US10 `20260729-03` outputs remain the flag-off authority.
Flag-on review covers:

- finance-10k and settlement-agreement byte-stable positives;
- clean-energy, health-report, esg-metrics, and uber-earnings duplicate targets;
- catastrophe table-caption ownership, an explicit upstream-missing source-note
  boundary, and a deterministic direct-image stream;
- postal-10k target, finance-10k and egov-survey related positives,
  purchase-agreement non-target, and component-datasheet negative controls from
  the P00-US09 registry.

Phase 0 retained outputs contain normalized v1 only; no raw Docling graph or
serialized IR was frozen. P01-US03 therefore adds a deterministic derived
IR/canonical fixture and a reviewed flag-on difference manifest without
rewriting any Phase 0 artifact.

## Performance and size

Canonical presentation is computed once in the pipeline and stored. The
Markdown serializer returns the stored document view and does not rebuild it.
Measurements record canonical build p50/p95/max, output bytes, process RSS, and
the conservative cumulative Phase 1 p95 against the immutable 46,706.960 ms
Phase 0 parse p95. The cumulative ceiling remains 5%.

## Rollback

Set `PARSER_CANONICAL_SERIALIZATION_ENABLED=false`. The additive object
disappears and backend/frontend clients use the unchanged legacy pages and
serializer. P01-US01/US02 evidence remains internal and unaffected.
