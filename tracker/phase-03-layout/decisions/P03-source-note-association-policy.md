# P03 Source-Note Association Policy

Status: Accepted for P03-US03 implementation  
Date: 2026-07-31  
Scope: Source notes, table footnotes, and source-visible/annotation-grounded
links outside structured-owner bboxes

## Decision

P03-US03 may project a note only from source-visible evidence on the same page
and in a compatible coordinate system as a presented table, chart, diagram, or
image owner. Notes remain distinct public elements with their own bbox,
provenance, stable ID, reading-order position, typed relationship, and exact
owner backlink. Owner bboxes never expand to contain a note.

The reviewed note denominator is exactly:

- catastrophe p1: `Data: Aon Catastrophe Insight`;
- clinical p2 Table 1: three source footnotes; and
- clinical p4 Table 2: four source footnotes.

This is 8 expected notes. Health-report note/source/StatLink blocks and the
clinical `.t001`/`.t002` table DOI links are related controls. The exact
clinical page-3 Figure 1 link
`https://doi.org/10.1371/journal.pmed.1004460.g001`, uniquely owned by diagram
`p3-i2`, is also a reviewed visual-link control. These controls test safe
association and link grounding without changing the 8-note denominator.

## Accepted evidence paths

1. A declared `source_note_of` or `footnote_of` raw-graph edge must agree with
   same-page external geometry.
2. An unowned source-visible candidate may be associated only when its bounded
   note/source/data marker or source link, below-owner geometry, and unique
   owner all agree.
3. A missing external note may use a separate bounded rendered band below a
   captioned visual. The band is not the owner crop, does not alter the owner
   bbox, and supplies only OCR evidence with its own line bbox.
4. A link target must be a bounded `http` or `https` URI that is either present
   in the visible source text or carried by a source PDF link annotation whose
   bbox agrees with the candidate. Semantic URL inference is forbidden.

Generated/model/derived-only text, inherited text without raw source evidence,
unsupported schemes, malformed targets, global crop padding, and arbitrary
semantic citation inference are rejected.

## Ownership and ambiguity

An accepted note is below and external to its owner, horizontally aligned, and
within 72 PDF points (or the corresponding declared page unit). A candidate
with exactly one agreeing owner is eligible. Multiple plausible owners,
multiple declared owners, graph/geometry conflict, cross-page or cross-unit
evidence, internal overlap, missing geometry, and distant notes promote to
neither owner and retain a sanitized concern.

Typed note candidates with no eligible owner retain an orphan-note concern.
Ordinary prose and running headers/footers are not note candidates and receive
no fabricated relationship.

## Public additive contract

An accepted note exposes:

- `type` equal to `source_note` or `footnote`;
- its own `id`, `value`, `md`, bbox, source, confidence, and reading order;
- `source_note_of` or `footnote_of` containing the public owner ID;
- one stable `relationship_id`, `relationship_type`, and
  `relationship_basis`; and
- only sanitized, source-grounded link descriptors when applicable.

The owner exposes the corresponding `source_note_ids` or `footnote_ids`, one
exact relationship descriptor, and
`layout_source_notes_projected=true`. Identifiers and relationship endpoints
must be unique and resolvable across the complete document. Notes serialize
once after the owner body and any attached below-owner caption, in source
geometry order.

## Bounds and failure behavior

The implementation must enforce, before pairwise association or serialization:

- at most 64 declared note references per owner;
- at most 256 structured owner candidates per page;
- at most 512 note/link candidates per page;
- at most 128 equivalent same-text candidates per page;
- at most 16 KiB of UTF-8 note text and 2 KiB per URI;
- at most 256 PDF link annotations per page and 1,024 per document;
- at most 16 separate missing-note visual bands per page;
- bounded serialized note output and bounded owner/page concerns.

Limit overflow fails closed to evidence-only behavior with content-free
aggregate diagnostics. Projection exceptions restore the exact predecessor IR
and add only a sanitized failure concern.

## Rollback and measurement

`PARSER_LAYOUT_SOURCE_NOTES_ENABLED` defaults to `false` and requires shared IR
normalization. Disabling this single flag restores predecessor public
relationships byte-for-byte and retains any text that was already emitted
independently of the story.

Final evidence must record exact 8/8 note recall, zero false associations,
relationship/backlink/bbox/order/link-grounding coverage, canonical and
frontend behavior, flag-off parity, latency, peak RSS, output size, and an
isolated p50/p95/max projection profile. P95 overhead must remain at or below
5% of the declared Phase 02 baselines.
