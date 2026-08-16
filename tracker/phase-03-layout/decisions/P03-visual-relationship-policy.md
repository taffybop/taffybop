# P03 visual-caption and internal-child policy

Status: Accepted for P03-US02 on 2026-07-31  
Owners: P03-US01 common caption arbitration and P03-US02 visual projection

## Decision

Visual relationships are a conservative, default-off compatibility projection
over the retained Phase 01 IR. Graph roles establish semantic candidates;
geometry can validate or refuse a candidate but cannot invent or swap roles.
The canonical presentation continues to consume the same IR and gains only the
small presentation rule needed to keep an explicitly promoted caption separate
from its visual owner.

## Caption rules

- Eligible owners are presented `image`, `chart`, and `diagram` elements with a
  public legacy item.
- A source-visible, textual `caption_of` node may project when its finite
  same-page/same-unit bbox:
  - overlaps the owner's horizontal span by at least 20%;
  - overlaps no more than 20% of the smaller region;
  - has a vertical gap no greater than 72 points; and
  - is unambiguously above or below the owner.
- Above captions are inserted immediately before the owner. Below captions are
  inserted immediately after it. Multiple valid captions remain distinct and
  use declared order within each side.
- Empty, non-text, generated/derived/model-marked, missing-geometry,
  cross-page, cross-unit, internal, distant, shared, or otherwise ambiguous
  captions remain evidence-only with sanitized concerns. Eligibility is
  established from accepted raw source methods and raw generation markers;
  inherited legacy evidence cannot upgrade an ineligible raw node.
  Inferred-derived punctuation is never eligible as a caption.
- Equivalent graph routes at one physical location project once. A source node
  declared as both caption and child projects only as an externally validated
  caption; its duplicate child route is diagnostic.
- Caption ownership is pre-arbitrated across enabled table and visual
  projections. A physical caption claimed by more than one owner, including
  cross-type claims, is promoted by none.
- The accepted raw-provenance gate is shared by visual and table caption
  projections. When raw graph evidence exists, inherited legacy native/OCR
  evidence cannot launder a generated, model-derived, malformed, or
  budget-exhausting raw caption. The legacy-only table path remains available
  only when the element has no raw-reference evidence.
- Stable public relationship IDs derive from relationship type and public
  endpoint IDs. The caption uses the established P03-US01 additive shape, and
  the owner carries the backlink descriptor.

The five reviewed linked positives are catastrophe Exhibit 8 and manufacturing
Figures 2.2, 2.7, 2.8, and 4.3. Their exact text, geometry, and side-aware order
are story-test and retained-evidence contracts.

## Contained-child rules

- A `contains` edge always remains owner-to-child and is never reclassified as
  `caption_of`.
- A uniquely owned source-visible child with finite same-page/same-unit geometry
  and at least 80% child-area containment may be exposed as one nested
  `contained_items` entry.
- Boundary, outside, shared, cross-page, missing-geometry, empty, unsupported,
  derived, generated, or model-marked children remain retained IR evidence
  with concerns. Raw eligibility is checked independently of inherited legacy
  diagnostics. Geometry conflicts do not turn ordinary children into captions.
- A narrow child-only exception preserves source-visible punctuation whose
  alphanumeric method inference is `derived`: every raw record must carry a
  nonempty punctuation/symbol-only value of at most 4 KiB and a raw bbox, be
  free of generated/model/malformed provenance, and match trusted retained
  native, OCR, mixed, vector, embedded, or recovered evidence. This exception
  cannot promote a caption or inherited-only text.
- `contained_items` is separate from existing OCR line-diagnostic `items`.
  Each entry retains a stable public ID, `visual_text` type, source value, exact
  bbox, source, confidence, `presentation_role=subordinate`, `contained_by`,
  and relationship metadata.
- Owners add `contains_ids` and typed `relationships`. Every relationship
  endpoint resolves to a page item or to the same owner's `contained_items`.
  Nested children never become page items or document prose.

## Owner-content and bbox invariant

Once an eligible visual has declared caption/child relationships, the flag-on
projection removes legacy scalar document-caption fields. It rebuilds `value`
and `md` only from existing `ocr_text` when
`include_ocr_in_primary is True` and every normalized OCR contribution is
backed by an accepted OCR diagnostic bbox fully inside the unchanged owner bbox
in the same coordinate unit. Otherwise it uses the existing empty-visual
fallback. It never obtains primary prose by subtracting strings from the merged
legacy value. The owner bbox, classification, OCR diagnostics, parse concerns,
and retained IR evidence are unchanged.

This guarantees that a public visual never claims text outside its bbox. It also
keeps Uber photograph OCR subordinate unless an existing authorized field has
explicitly enabled primary OCR.

## Canonical and frontend behavior

Promoted visual captions and their owners are separate canonical blocks in the
same geometry-aware order. Both blocks retain the public relationship ID, while
the visual block omits the promoted caption contribution and contains only
authorized visual OCR. The frontend renders canonical caption blocks through
the same escaped `.parsed-caption` milestone as legacy caption items and never
renders `contained_items` as prose. JSON, copy, and download preserve the
additive fields byte-for-byte.

An owner that is actually processed by this projection carries
`layout_visual_relationships_projected=true`. Frontend suppression semantics
apply only to that explicit marker, and marked raw OCR is exposed only when
`include_ocr_in_primary=true`. Unmarked UI and normalization retain their exact
legacy field precedence, including explicitly present empty strings.

## Bounds and failure behavior

- 64 caption references per owner.
- 256 contained-child references per visual.
- 512 eligible visual owners per page.
- 512 combined table-and-visual caption candidates per page.
- 128 combined same-normalized-text caption candidates per page.
- 64 KiB UTF-8 per caption.
- 256 KiB canonical JSON for `contained_items` per owner.
- 16 emitted visual concerns per owner and 256 per page, followed by one
  sanitized aggregate for suppressed diagnostics.
- Raw generation/model provenance scanning permits at most 4 nested levels,
  64 entries per nested mapping or sequence, 256 mapping/sequence nodes total,
  16 declared evidence methods, and 32 bytes per method name. Unknown,
  malformed, or budget-exhausting declarations fail closed.

Caption and child payload sizes are streamed through bounded preflight before
normalization, geometry, or public copying. An overflow rejects the complete
affected owner or page candidate set before pairwise geometry work. Raw IR
remains intact. Concern identity uses bounded constant-time deduplication, and
concerns expose only bounded counts, limits, IDs, and text hashes. Story-level
projection works on a deep copy; validation failure returns the predecessor
plus a sanitized concern.

## Scope boundary

The component-datasheet photo caption has no graph ownership edge, so it is
preserved exactly once without an invented link. Source notes, chart values,
classification, running headers, printed page identity, and child-text repair
belong to later stories.
