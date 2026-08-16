# P03 Relationship-Aware Reading-Order Policy

Status: Accepted for P03-US04 implementation  
Date: 2026-07-31  
Scope: Final page presentation order and source-evidence bbox-ownership
validation after P03-US01 through P03-US03

## Decision

P03-US04 is a default-off presentation projection over the accepted shared IR.
It may reorder complete, already-presented page elements when trusted typed
relationships or finite page-space geometry provide unambiguous evidence. It
may also place a bounded source-grounded title fragment before the unique
table that already overlaps that fragment. Its only content operations are
fail-closed removal of a scalar contribution proven by source evidence to lie
outside the unchanged owner bbox and reordering explicitly enumerated
contained source fragments whose finite non-overlapping boxes prove their
page-space order. It does not create prose, infer semantic columns, widen
bboxes, change semantic ownership, or repair table content.

The projector runs last in `apply_layout_projection`. Ordinarily it rewrites
only:

- `PageRecord.presentation_element_ids`;
- public `pages[].items` array order; and
- contiguous public `reading_order = 0..n-1`.

All public and IR IDs, relationship IDs, element types, table cells, bboxes,
evidence, provenance, links, classifications, owner backlinks, alternative
winners, suppression state, page identity, and scopes remain identical when
compared by stable ID. Values, Markdown, nested public diagnostic order, and
canonical block content also remain identical except for the two exact
reviewed source-grounded corrections under the ownership rule below. Schema
`1.0` and `canonical-presentation-v1` remain unchanged.

## Presentation ownership rule

An existing scalar `value` or `md` may be rebuilt only when all contributing
source fragments are explicitly enumerable and each has trusted same-page,
same-unit, finite geometry. Contributions wholly contained by the unchanged
owner bbox follow disjoint top-to-bottom then left-to-right page-space order;
the same order is applied to their existing nested public records and parent
scalar/canonical presentation. A contribution whose independent source bbox
is outside that owner is excluded from that owner's public and canonical
presentation but retained in raw IR evidence. Partial overlap, missing
provenance, generated/model/derived-only evidence, ambiguous text matching,
or a byte/reference limit fails closed to the exact predecessor page with
`relationship_order_bbox_ownership`.

The reviewed positive is clinical p1 item `p1-i14`, bbox
`[36.001,692.642,151.206,17.698]`. Its visible owned text ends at `obtained`;
the appended `RESEARCHARTICLE` token is independently outside that bbox and
must not remain in the item's value, Markdown, or canonical block. No other
clinical text is removed or moved by semantic inference. Finance remains an
exact content control.

The second reviewed correction is clean-energy p1 header `p1-i1`. Its two
existing nested source fragments have disjoint finite boxes: report title
`Clean Energy Market Monitor - March 2024`
`[56.64,52.803,159.674,7.556]` and `Overview`
`[735.36,48.909,44.409,9.360]`. Their source page-space order is report title
then `Overview`; the projector reorders the two existing nested records and
rebuilds only this parent's `value`, `md`, and canonical content to agree. It
does not create, merge, delete, or change either nested fragment or bbox.

These two content operations are exact audited signatures, not generalized
repair heuristics. The clean-energy signature requires the fixed public ID,
header type, two exact values, and the three reviewed owner/child boxes. The
clinical signature requires public ID `p1-i14`, the reviewed owner box, and
exactly one terminal outside contribution whose value is
`RESEARCHARTICLE`; an earlier duplicate or any additional rejected
contribution is ineligible. Source fragments prove coverage and ownership but
never reconstruct the scalar: the projector removes only that terminal token
and its immediately preceding separator whitespace from the predecessor
scalar, preserving every owned prefix byte. Lookalike content retains its
predecessor value, nested records, Markdown, and canonical presentation.

## Relationship bundles

Accepted P03-US01 through P03-US03 relationships form atomic contiguous
bundles. Table captions and above-visual captions precede their owner.
Below-visual captions follow their owner. Source notes and footnotes follow
the owner and any accepted below-owner caption. Multiple accepted captions or
notes retain their declared order and remain distinct.

This side-aware rule preserves the immutable P03-US02 contract. P03-US04 does
not reinterpret every caption as an above-owner caption. The five retained
US02 visual positives, including manufacturing Figures 2.2, 2.7, 2.8, and
4.3, keep their accepted placement.

Only same-page, endpoint-resolving, trusted typed relationships may impose
hard edges. Synthetic `reading_before` relationships whose basis is exactly
`legacy_reading_order` are predecessor tie hints, not hard edges. Explicit
source-grounded `reading_before` relationships are hard edges. Duplicate edge
triples coalesce; equal text never coalesces distinct elements.

Trust comes either from attached evidence whose methods are all accepted or
from an accepted predecessor-projector marker. Marker-based trust is bound to
the exact relationship ID, its matching predecessor story, and the
story-compatible relationship type: P03-US01/P03-US02 markers may attest only
`caption_of`, while P03-US03 markers may attest only `source_note_of` or
`footnote_of`. A relationship cannot borrow another relationship's marker,
and predecessor markers never attest `reading_before`.

## Geometry policy

Geometry is normalized only when every participating box has finite positive
area in the page's declared coordinate system and unit.

IR `transform_to_page` is authoritative. Raw-coordinate and already
page-normalized bbox routes may coexist; transformed routes that resolve to
the same page-space rectangle coalesce, while two distinct page-space
rectangles are ambiguous. Missing transforms, cross-page coordinates, or a
legacy box that matches neither its raw nor transformed IR box fail closed.

1. Disjoint vertical intervals order top-to-bottom.
2. Elements whose vertical intervals overlap form a band. Within a band,
   stable left-to-right order is permitted only for non-overlapping finite
   horizontal intervals; otherwise predecessor rank and stable ID break ties.
3. A block that vertically spans content in another column retains predecessor
   column order. No semantic column labels, generated text, language models,
   or all-pairs column inference are used.
4. Bottom navigation and running/footer candidates follow body blocks when
   finite geometry establishes a disjoint lower band.
5. Missing, invalid, cross-page, cross-unit, zero-area, out-of-page, or
   ambiguous geometry cannot create an order edge. A page with an ownership
   conflict remains in exact predecessor order with a concern.

This policy intentionally freezes the ESG page as the existing left body
through `p1-i10`, then the right body `p1-i12` through `p1-i18`, then lower
navigation/footer `p1-i11`, `p1-i19`, `p1-i20`. It moves the lower-left Table
of Contents after body content without guessing a semantic column sequence.
On clinical p1 only the disjoint title/author-versus-sidebar pairs are
required; overlapping later column material retains predecessor order.

## Bounded timetable-prefix rule

The `GAP-ORDER-001` timetable claim spans physical pages 1–3. The reviewed
US04 target is the two source-visible fragments on physical page 2 / printed
page `3 of 28`: `Weekdays` and `to The Bronx`, both at `y=31.2`, before table
`p2-i1`. The control-registry region suffix `source:p01` is a claim-level
locator artifact and does not override the source review's three physical
locators.

A fragment may move immediately before a unique overlapping table only when
all of these hold:

- its predecessor item is already source-grounded and marked
  `layout_omission_recovered_by_ocr`;
- confidence is at least `0.80`;
- provenance is native, OCR, vector, embedded, recovered, or mixed and is not
  generated/model/derived-only;
- it has its own finite positive same-page/same-unit bbox;
- it lies in the top 72 points and within the unique table's top band;
- it is absent from the table's presented value and Markdown; and
- ownership is unique under the bounded comparison limits.

The low-confidence physical-page-2 fragment `ew` at `y=151.2` is not title
evidence and must not move before the table. Physical-page-3 expert row 6 is
the negative control: its incorrect table row is neither repaired nor used as
order evidence.

## Fixed reviewed denominator

The numerator is the following **41 ordered pairs**. `A → B` means A appears
before B on the same page; it does not require adjacency unless A and B are
members of one atomic relationship bundle.

| Case | Reviewed ordered pairs |
|---|---:|
| catastrophe p1 | 7 — `p1-i2 → el-91373a72a9c9e4e6f91d → p1-i3 → p1-i4 → layout-caption-5a6f8b41401544adeb2a → p1-i5 → layout-note-af58a03da292b26ce13f → p1-i6` |
| clinical-study p1 | 3 — `p1-i15 → p1-i4`; `p1-i18 → p1-i4`; `p1-i14 → p1-i19` |
| component-datasheet p1 | 4 — `p1-i3 → p1-i4 → p1-i2 → p1-i5 → p1-i6` |
| esg-metrics p1 | 4 — `p1-i10 → p1-i12`; `p1-i18 → p1-i11 → p1-i19 → p1-i20` |
| manufacturing p2 | 6 — `p2-i1 → layout-caption-c89f2384aa740f5d02ce → p2-i2 → p2-i3 → layout-caption-daceff6ae2f2ee83c6d0 → p2-i4 → p2-i5` |
| purchase-agreement p1 | 3 — `p1-i9 → p1-i10 → p1-i11 → p1-i1` |
| clinical-study p2 | 2 — `p2-i3 → p2-i4 → p2-i5` |
| ny-timetable p2 | 2 — `Weekdays → to The Bronx → p2-i1`; `ew` is excluded |
| clean-energy p1 | 5 — nested report title → nested `Overview`; `p1-i1 → p1-i2 → p1-i3 → p1-i7 → p1-i8` |
| finance-10k p1 | 5 — `p1-i1 → p1-i2 → p1-i3 → p1-i4 → p1-i5 → p1-i6` |

Passing quality is exactly 41/41 pairs, zero accepted-owner bbox violations,
zero duplicate presentation, no keyed mutation outside the exact audited
clinical ownership correction and clean-energy nested reorder, exact finance
predecessor parity, and
unchanged page-3 timetable table data.
The P00-US09 control matrix remains mandatory: timetable target,
clean-energy related positive, finance non-target, and timetable p3 negative.

## Bounds, complexity, and diagnostics

Before geometry or ordering work, enforce:

- at most 512 primary presented anchors per page and 65,536 per document;
- at most 4,096 raw same-page relationship records before deduplication and
  accepted ordering edges per page, and 65,536 relationship records/edges
  per document;
- at most 64 relationship references per anchor;
- at most 64 source-contribution references per anchor;
- at most 512 recovered-prefix candidates per page;
- at most 65,536 prefix-to-owner comparisons per page;
- at most 1 MiB / 65,536 JSON-like nodes of inspected legacy presentation
  data and 1 MiB of inspected evidence text per page;
- at most 262,144 records in any indexed IR collection;
- at most 16 detailed US04 concerns per page and 256 per document, followed
  by one sanitized aggregate concern.

Processing is `O((V + E) log V)` time and `O(V + E)` memory outside the
explicitly capped prefix-owner comparisons. It performs no unbounded all-pairs
geometry or text comparisons.

Allowed detailed concern codes are:

- `relationship_order_cycle`;
- `relationship_order_geometry_ambiguous`;
- `relationship_order_bbox_ownership`;
- `relationship_order_page_limit`;
- `relationship_order_edge_limit`;
- `relationship_order_duplicate_anchor`;
- `relationship_order_projection_failed_closed`; and
- `relationship_order_concerns_truncated`.

Diagnostics contain fixed codes, bounded counts/limits, page identity, and an
allowlisted exception type only. They never contain document text, URLs, raw
references, or relationship metadata.

## Failure, idempotence, frontend, and rollback

A cycle in combined hard edges, duplicate primary anchor, ownership conflict,
limit overflow, or validation failure restores the exact affected predecessor
page and emits only bounded sanitized diagnostics. A complete candidate
`DocumentIR` is validated inside the rollback boundary before commit.
Repeated application produces the same IDs, page order, contiguous ranks,
canonical views, and diagnostics.

Backend legacy Markdown follows public item-array order. Frontend legacy
Markdown follows `reading_order`. Both must agree after the atomic rewrite;
the frontend continues to trust canonical order and never infers geometry.
Rendered view, source view, normalized JSON, copy, and download must expose
the same backend-authoritative sequence.

`PARSER_LAYOUT_RELATIONSHIP_ORDER_ENABLED` defaults to `false` and requires
shared IR normalization. It is included in both ordinary and terminal
source-alignment layout checks. Disabling this flag restores the exact
P03-US03 predecessor, including absence of US04 fields or concerns.

Final performance evidence uses five alternating fresh-process pairs with
P03-US01–US03 enabled and only US04 toggled. Inclusive clipped p95 overhead is
at most 0.579 seconds for manufacturing and 1.4575 seconds for Uber. The
isolated stage p95 is at most 50 ms for reviewed cases, a maximum-limit case
is at most 250 ms, and peak traced allocation is below 32 MiB. RSS is recorded
against 1,825.8 MiB and 2,589.5 MiB but is not the latency gate.
