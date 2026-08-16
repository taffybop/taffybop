# P03 Running Regions and Page Identity Policy

Status: Accepted for P03-US08 implementation on 2026-08-01  
Date: 2026-08-01  
Scope: Running headers, footers, navigation, and printed page identity after
all other Phase 03 layout projections  
Delivery estimate: 5 points

## Decision

P03-US08 is a default-off, local-only projection over the accepted shared IR.
It separates physical position, embedded PDF page labels, source-visible
printed labels, and display identity without changing any legacy page-identity
field. It also classifies source-grounded running headers, footers, and bounded
top/bottom navigation so canonical body and full-document views have explicit,
stable custody.

The following invariants are normative:

- `page_index`, `page_number`, and `page_label` remain byte-for-byte unchanged
  from the configured P03-US07 predecessor in flag-on and flag-off output;
- every successfully projected public page and its matching canonical page
  receive the same strict `page_identity` sidecar;
- physical navigation uses `page_index` only;
- an unambiguous detected printed label outranks an embedded PDF label, which
  outranks the unchanged legacy `page_label` display fallback;
- when a detected and embedded label conflict, both are retained, detected
  promotion fails closed, the safe embedded label supplies `display_label`,
  and a bounded concern is emitted;
- top navigation maps to canonical `header`, and bottom navigation maps to
  canonical `footer`; canonical scope remains the existing closed enum
  `body | header | footer`;
- canonical page `body` excludes every accepted running region, while
  canonical page `full` contains every accepted running region exactly once;
- no page label is synthesized into Markdown, HTML, a URL, an element ID, a
  filename, a selector, or a physical navigation target; and
- ambiguity, malformed evidence, unsafe display text, ownership conflict,
  resource overflow, deadline overflow, or custody failure never guesses a
  label or removes source evidence.

JSON is normative. Detection may normalize a tightly bounded printed-label
phrase into a citation label, but the exact source-visible phrase, bbox, source
objects, and evidence IDs remain separately recorded. Rule scores are
deterministic acceptance indicators, not calibrated probabilities.

## Scope and exclusions

In scope:

- native-PDF embedded page labels and native, source-visible printed labels;
- existing layout `page_header` and `page_footer` records, exact cross-page
  boundary repetition, and conservative top/bottom navigation cues;
- physical index, embedded label, detected printed label, exact visible text,
  selected display label, evidence bbox/source, confidence, and concerns;
- strict IR, public-page, canonical-page, processing-summary, and frontend
  contracts;
- exact canonical body/full/header/footer views, page UI, copy/download,
  limits, rollback, terminal source-alignment replay, and retained metrics;
- coexistence with every completed Phase 03 projector.

Out of scope:

- changing, renumbering, repairing, or reinterpreting legacy `page_index`,
  `page_number`, or `page_label`;
- guessing an absent printed page or filling a gap in a printed sequence;
- using a printed or embedded label as an array index, PDF preview page, image
  frame, canonical lookup key, or stable-ID input;
- document-section, chapter, citation, hyperlink-target, or navigation-target
  inference;
- general merging, splitting, deleting, or rewriting of source-visible items;
  the sole exception is the bounded, evidence-preserving extracted-contribution
  projection defined below, which leaves its predecessor owner byte-identical;
- making a body number a page label from location alone;
- table, chart, form, outline, source-note, caption, or text repair;
- OCR-only, direct-image, image-only-PDF, or Office parity until their approved
  semantic twins and adapters exist;
- arbitrary Roman/custom printed-label recognition without a reviewed positive
  fixture; safe embedded labels may still contain such source metadata;
- hosted models, hosted OCR, language models, filename/hash/page-specific
  branches, dictionaries, or semantic plausibility; and
- calibrated confidence claims.

For non-PDF inputs the feature is `not_applicable`: no US08 source extractor or
projector runs, no sidecar is emitted, and the configured predecessor remains
exact.

## Immutable reviewed denominator and custody

The authoritative page map is the accepted Phase 00 registry:

`tracker/phase-00-baseline/evidence/P00-US04-corpus-registry.json`

- size: 20,744 bytes;
- raw SHA-256:
  `f8024ab7a47df2cedf2d10b996fc8eb140404cdafea0b0a0a9ae2bb059263ceb`;
- source use and derived annotations are governed by the accepted corpus
  custody and source-rights decisions; and
- runtime measurement makes zero hosted requests.

The configured feature-off predecessor is the retained post-US07 snapshot at
`tracker/phase-03-layout/evidence/P03-US08-post-US07-predecessor-20260801`.
Its 15 per-case `our-output.json` byte sizes and SHA-256 identities are sealed
in the machine oracle (4,614,035 bytes total). The generating configuration is
also sealed: shared IR, shared-IR normalization, canonical serialization,
table captions, visual relationships, source notes, relationship order, text
run semantics, forms, and outline structure are all enabled. Phase 00 parser
outputs are not accepted as US08 predecessor custody.

The reviewed denominator is 30 physical pages, 27 non-null printed labels,
and three explicit nulls:

| Case | Exact physical → reviewed printed identity |
|---|---|
| catastrophe-recap | `1 → 7` |
| clean-energy | `1 → 11` |
| clinical-study | `1 → 1/21`, `2 → 7/21`, `3 → 10/21`, `4 → 11/21` |
| component-datasheet | `1 → 3`, `2 → 7`, `3 → 11` |
| egov-survey | `1 → 37` |
| esg-metrics | `1 → 80` |
| finance-10k | `1 → 28`, `2 → 30`, `3 → 32` |
| health-report | `1 → 103` |
| insurance-acord | `1 → null` |
| manufacturing-report | `1 → 11`, `2 → 15`, `3 → 38` |
| ny-timetable | `1 → 2 of 28`, `2 → 3 of 28`, `3 → 4 of 28` |
| postal-10k | `1 → 2`, `2 → 46`, `3 → 49` |
| purchase-agreement | `1 → null` |
| settlement-agreement | `1 → 24` |
| uber-earnings | `1 → null` (white-on-white hidden glyph; legacy display fallback `1`), `2 → 5`, `3 → 6` |

All 15 reviewed PDFs currently expose an empty `pypdfium2` embedded page-label
value. Therefore embedded-label agreement, embedded-only, unsafe embedded, and
embedded-versus-visible conflict are mandatory generated fixtures, not claims
derived from the real-corpus denominator.

The two reviewed printed-identity non-targets are
`insurance-acord` page 1 item `p1-i21` (form/legal identifiers) and
`purchase-agreement` page 1 item `p1-i12` (document-control identifier).
Their accepted running-region status does not promote either item to printed
page identity.

The third null is a distinct compositing control: `uber-earnings` page 1 item
`p1-i4` contains a text-layer glyph `1`, but its native fill is effectively
white and the exact bbox renders uniformly white at the fixed 4-pixel/point
visibility probe. Text-layer presence is not source visibility, so this item
is neither a printed-label candidate nor a running region. The unchanged safe
legacy page label still supplies display fallback `1`. Exact source and render
custody are retained in the
[Uber page-1 visibility addendum](../evidence/P03-US08-uber-page1-visibility-addendum.md).

Before the story becomes Ready, a machine oracle must freeze for all 30 pages:

- the exact post-US07 predecessor root, configuration, per-output byte sizes,
  and SHA-256 identities;
- the complete closed source reports, including page source counts, 27 label
  candidates, 47 boundary candidates, and aggregate counts;
- the exact four identity inputs/outputs and display source;
- exact source character/word IDs and bboxes for every detected label;
- accepted running-region public paths, element IDs, bboxes, roles, repetition
  groups, and canonical block IDs;
- exact header/body/footer/full block membership and all required pairwise
  order assertions; and
- the three explicit null labels and every reviewed negative/non-target.

Production code may not branch on this registry, its hashes, case names,
filenames, page numbers, or oracle values.

## Identity terminology

The five identity concepts are deliberately independent:

- `physical_page_index` is the one-based position of the source page and must
  equal unchanged public `page_index`;
- `embedded_label` is a bounded, safe label decoded from the PDF page-label
  tree; it is metadata and has no visible bbox;
- `detected_printed_label` is the bounded citation label produced by the
  closed visible-label grammar below;
- `visible_text` is the exact source-visible character span supporting
  `detected_printed_label`, before label normalization; and
- `display_label` is selected by the closed precedence rule and is UI metadata,
  never physical navigation.

`page_number` and `page_label` retain their configured predecessor meanings.
US08 does not retroactively redefine them.

## Source extraction and visible-label grammar

Source extraction uses only local `pypdfium2` page-label metadata,
`pdfplumber` native characters/words with top-left page-space geometry, and
the bounded ephemeral `pypdfium2` visibility gate below. It records the source
SHA-256 and exact page count. Docling layout roles may corroborate region
ownership but may not replace native visible text or its bbox.

Projection authority is issued only from the configured predecessor document
and the exact PDF bytes whose SHA-256 equals that configured source identity.
The fixed post-US07 extraction path is run twice over those bytes; all semantic
fields must match after excluding only elapsed time. The resulting strict-JSON
report and explicit public-item -> IR-element -> canonical-block bindings are
frozen together. Caller-supplied reports, copied objects, mapping lookalikes,
direct construction, changed bytes, changed hashes, or a nondeterministic
extractor never confer projection authority. Authority objects are opaque,
nonserializable, noncopyable, identity-bound in a weak-reference registry of
at most eight live entries, and retain no raw PDF bytes. The authority token
exposes no report, plan, predecessor, or serialized-template payload. Those
immutable bytes live only in the frozen private registry record; projection
authenticates type-sensitive public and IR JSON bytes before thawing a fresh
factory-built predecessor clone. In particular, Boolean, integer, and float
substitution cannot pass through Python's cross-type numeric equality.

Every retained native character binds its declared scalar exactly:
`raw_text == chr(raw_code_point)`. Normalized/derived character text may only
come from the closed transform recorded by the extractor; caller-asserted code
points or derived strings are not source evidence.

A native printed-label span is eligible only if its exact bounded visible text
and candidate bbox also pass the generic rendered-visibility gate. The displayed top-left bbox is
pixel-aligned by multiplying every edge by exactly 4 pixels/point and applying
nearest-integer, ties-to-even rounding. That exact crop is rendered once with
PDFium against opaque white, with forms and annotations disabled. Its modal
RGB is the highest-count color with lexicographically smallest RGB as the tie
break. The maximum crop-to-modal channel delta and every selected PDFium
text-object-fill-to-modal channel delta must each be at least 16 byte levels.
Native finite DeviceGray, DeviceRGB, and DeviceCMYK values use the frozen
round-half-up RGB normalization; other color shapes fail closed.

Raster contrast alone is insufficient custody. Candidate-local PDFium text
objects first require positive bbox intersection. A match is then exactly one
unique ordered object-index sequence whose whitespace-compacted text equals
the whitespace-compacted candidate, or one rstripped object ending in the
exact candidate whose preceding character is whitespace or one of `|`, `:`,
`/`, or `-`. This bounded suffix admits source strings such as
`Form 10-K | 28` without treating an arbitrary numeric suffix as custody;
unrelated intersecting objects with different text cannot qualify or
contaminate the selected fill set. Every selected object must use a text
render mode that paints the fill (`0`, `2`, `4`, or `6`) and a non-stroking
fill alpha greater than zero. Normalized DeviceGray and DeviceRGB fills must
equal the selected PDFium RGB set exactly. DeviceCMYK uses the same
bidirectional set corroboration with a maximum per-channel delta of exactly
36, the independently exercised retained-source maximum; 37 rejects. The
selected PDFium RGB set is authoritative for rendered contrast. Stroke-only
modes `1`/`5`, invisible mode `3`, clip-only mode `7`, zero alpha, absent
candidate-text intersection, or fill disagreement is ineligible. Finite
degenerate text objects are skipped because they cannot positively intersect;
non-finite bounds fail closed. The gate retains no pixels or visibility proof.

The coordinate frame is closed. The displayed page box is the finite PDF
`CropBox` when present and contained by the finite `MediaBox`, otherwise the
finite `MediaBox`. The declared PDF rotation must be exactly `0`, `90`, `180`,
or `270`; the box is rotated and translated to a top-left origin before any
band test. Its resulting width and height, unit, rotation, and transform must
agree with the predecessor `PageRecord` within `0.001` point. An invalid box,
unsupported rotation, ambiguous transform, or dimension mismatch refuses the
page. Content bounds, whitespace trimming, OCR, and inferred crop margins may
not change this frame.

All source bboxes must be finite, positive-area, in the declared page unit,
and fully inside the matching page within `0.001` unit. Cross-page,
cross-coordinate-system, missing-transform, zero-area, non-finite, or
out-of-page geometry is ineligible and produces only a bounded concern.

The nominal boundary bands are the top and bottom 15% of that displayed page
box. The top band is never extended. One effective-content-bottom cluster may
extend the bottom band inward only when all of these hold:

- at least three unclaimed primary items form one contiguous trailing cluster
  in accepted P03-US04 presentation order after every remaining body item;
- every item has finite same-frame geometry inside the outermost 30% of page
  height, their vertical midpoints differ by at most 2% of page height, their
  horizontal intervals are disjoint or merely touch, and their union is
  separated from every remaining body bbox by a positive vertical gap;
- the cluster contains at least one exact closed `boundary_navigation` cue and
  a different item containing exactly one grammar-valid printed-label span;
- all cluster items have unique public/IR ownership, no earlier Phase 03
  semantic owner, and exact P03-US04 public/IR/canonical order parity; and
- there is one maximal cluster and one cut point. Overlap, mixed coordinates,
  a noncontiguous order, a second candidate cluster, or any ambiguity rejects
  the extension.

The effective bottom band begins at the minimum cluster `y` and ends at page
bottom; only cluster members gain eligibility from it. Membership alone is
never sufficient: the cue item must satisfy `boundary_navigation`, the unique
label item must satisfy the cluster-bounded `printed_label_boundary` rule, and
any other furniture member must satisfy the closed
`effective_boundary_cluster` method below. The label span must still pass the
closed grammar and ambiguity rules. This rule is generic and may not inspect a
filename, source hash, case ID, fixed public ID, page number, or oracle value.
It binds a source-proven P03-US04 lower navigation/footer row such as
`p1-i11 → p1-i19 → p1-i20` even when that row begins above the literal bottom
15%, without relaxing bare-number recognition outside the validated cluster.

The private effective-cluster method proof has exactly `items`,
`remaining_body_bboxes`, and `candidate_cut_count`. Both collections must be
ordered arrays, page dimensions must be finite positive non-Boolean numbers,
and the cut count must be the non-Boolean integer `1`. After the full cluster
proof succeeds, candidate admission independently finds exactly one proof item
whose ID equals the candidate's `public_item_id`, requires its bbox to equal the
candidate bbox, and requires both its `navigation_cue` and `normalized_label`
to be null. The numeric cluster-top result never substitutes for that exact
membership/furniture proof; an absent, duplicate, cue, or label member fails
closed.

The visible printed-label grammar is closed:

1. a positive ASCII integer token `[1-9][0-9]{0,5}`;
2. `<token> / <total>`, normalized by removing whitespace around `/`;
3. `Page <token> of <total>`, case-insensitive only for literal `Page` and
   `of`, normalized to `<token> of <total>`;
4. `PAGE | <token>`, case-insensitive only for literal `PAGE`, normalized to
   `<token>`; or
5. the same exact token as the final delimiter-separated field of an accepted
   header/footer source item.

`token` and `total` use rule 1, and a total form additionally requires
`token <= total`. The exact supporting phrase becomes `visible_text`; the
normalized result becomes `detected_printed_label`. No other punctuation,
word, Roman numeral, alphabetic prefix, date, currency, percentage, section
number, table cell, chart label, list marker, form value, or prose number is
eligible in v1.

A visible candidate is promotable only when all of these hold:

- it is a complete native character/word span with an exact bbox;
- it resolves to exactly one accepted running-region item, existing trusted
  `page_header`/`page_footer` item, or unique standalone boundary item under
  the closed native-source ownership rule below;
- a standalone bare token is in the bottom 15% of the page, except that the
  unique grammar-valid label item in a fully validated effective-bottom
  cluster may use that cluster band; a top-band bare token additionally
  requires an existing trusted header role;
- it is not owned by a table/cell, chart/diagram/image, caption, source note,
  footnote, form/key-value descriptor, outline descriptor, or another running
  region;
- the page has exactly one normalized candidate after exact duplicate source
  paths coalesce; and
- every supplied source/public/IR path and bbox agrees exactly with the shape
  it claims; a detached `native_source_only` identity never supplies or
  fabricates public/IR IDs.

The native-source ownership rule first accepts strict bbox containment within
`0.001` point. Only when strict containment fails, a detached
`native_source_only` candidate may instead bind one boundary owner when all of
these are true: the candidate's nonempty native word-ID set is an exact subset
of that owner's recomputed native word-ID set; the candidate intersection area
is at least `0.80` of the candidate area; the absolute vertical-center delta is
at most `0.002 * page_height`; and page, coordinate frame, band, source text,
and all other ownership rules agree. Exactly one owner must survive. The
alternative never creates an exact-public binding and never accepts a nearby
box, shared/duplicate owner, intersection-only match, or unlinked source ID.
This same containment-or-candidate-coverage predicate, including the mandatory
native word-ID intersection, applies when the effective-bottom method proof
binds its detached label member to the selected public owner.
The reviewed denominator has eight strictly contained candidates and 20 using
this alternative: ten exact word-set matches and ten complete native subspans
of composite trusted/accepted owners. Their candidate-area coverage is
`0.834671–0.973214` and their center delta is `0.029–1.0245` points.

Location by itself is never sufficient. Multiple distinct detected values,
multiple unmatched source paths, low-coverage or source-unlinked overlap, or
mixed ownership makes detected promotion ambiguous. The complete bounded
source report retains the candidates, while the public
`detected_printed_label` and `visible_text` are `null` and the page carries
`page_identity_detected_label_ambiguous`.

## Running-region recognition

The ordinary path reuses an existing source-visible primary item. It never
creates, merges, splits, or removes that item. A direct item can become a
running region by one of five methods:

1. `trusted_layout_role`: the raw layout role is exactly `page_header` or
   `page_footer`, its complete nested ownership is valid, and its bbox lies in
   the corresponding nominal or valid effective boundary band;
2. `cross_page_repetition`: the same normalized source text occurs at most
   once per page on at least two pages, always in the same boundary band, with
   vertical position differing by at most 2% of page height and reciprocal
   horizontal overlap of at least 0.50; an accepted page-label span may be
   replaced by the literal repetition placeholder `{page}` before grouping;
3. `boundary_navigation`: one unclaimed boundary item contains a source-visible
   arrow/chevron or a case-insensitive complete navigation cue from
   `TABLE OF CONTENTS`, `CONTENTS`, `PREVIOUS`, `NEXT`, `BACK`, or `HOME`, and
   satisfies the same geometry and ownership rules; or
4. `printed_label_boundary`: one unclaimed item contains the page's unique
   accepted visible-label span and lies in its qualifying nominal/effective
   band. A bare top token still requires the trusted-header condition. A bare
   bottom token outside the literal bottom 15% qualifies only when it is the
   sole grammar-valid label member of the fully validated effective-bottom
   cluster; or
5. `effective_boundary_cluster`: one otherwise-unclaimed, non-label,
   non-navigation-cue furniture item is a member of that same uniquely
   validated effective-bottom cluster. It maps only to role/type/scope
   `footer`/`footer`/`footer`; it never applies outside the cluster, to a top
   band, or to body/table/form/outline/visual/caption/note ownership.

Repeated-text normalization is Unicode NFC, casefolding, and collapse of
Unicode whitespace to one ASCII space. It performs no stemming, translation,
dictionary lookup, punctuation repair, fuzzy matching, edit-distance match,
or semantic comparison. Grouping uses a bounded hash index, not all-pairs
text comparison.

Every complete set of eligible repeated candidates must declare its one
document-scoped repetition group and exact sorted member pages; a projector may
not null or partially declare an otherwise eligible group. Validation repeats
the 2%-of-page-height vertical tolerance, reciprocal horizontal overlap of at
least 0.50, common boundary band, normalized signature, exact member-page set,
and source-scoped stable-ID formula against the retained source report.

### Bounded extracted-contribution exception

When an otherwise eligible running header/footer contribution is fused into a
body, visual, caption, or other prior-projector owner, US08 may project that
contribution without taking or changing the owner's source ownership. This is
the sole creation/content exception in v1 and uses
`source_method = extracted_source_contribution`.

The exception is eligible only when all of the following are true:

- one nonempty sequence of native characters/words supplies exact
  `source_text`, ordered source-object IDs, evidence IDs, and a finite
  contribution bbox;
- the contribution independently satisfies trusted-role evidence or the exact
  cross-page repetition rule in a nominal or valid effective boundary band;
- it maps to exact ordered `presentation_fragments`, each occupying one or more
  complete delimiter-separated lines. The private plan uses one exact,
  unique, contiguous predecessor byte interval when available; otherwise it
  may use an ordered set of at most eight exact, unique, disjoint intervals.
  Every interval maps bijectively to one or more ordered native source
  character/word spans, includes only its complete running fragment plus one
  recorded adjacent delimiter, and includes no body byte. The plan records
  all original and residual insertion offsets, fragments, delimiters, the
  canonical residual, and hashes of `source_text`, joined
  `presentation_text`, every fragment/removed interval/delimiter, the
  predecessor scalar, the ordered plan, and the residual;
- `source_text` and `presentation_text` are NFC and each equals its Unicode
  edge-whitespace-stripped value, so every maximal whitespace run is internal.
  The two strings are either identical or differ only in mapped internal
  Unicode-whitespace runs: their ordered non-whitespace codepoint sequences
  are identical after the presentation fragments are joined in native
  source-span order, they have the same ordered maximal whitespace-run
  boundaries between those codepoints, and every source run maps bijectively
  to one exact UTF-8 byte range in the joined `presentation_text`. The bounded
  detached plan records each ordered source and presentation byte range. No
  non-whitespace insertion, deletion, substitution, or reordering, and no
  outer, unmapped, split, merged, or reordered whitespace run is permitted;
- exactly one predecessor public owner and one source element own it through
  exact graph/nested-native IDs and scalar intervals. Its native contribution
  bbox is either strictly contained within `0.001` point by the coarse owner
  bbox or has at least `0.99` candidate-area coverage; the latter alternative
  is valid only with the complete graph, source-object, interval, inverse, and
  hash proof and is never sufficient by overlap alone. The exact native
  evidence bbox equals the contribution bbox. Public nested children prove
  graph/value/order ownership rather than replacing that source bbox; their
  bbox union additionally covers at least `0.90` of the candidate area and its
  vertical center differs by at most `0.002 * page_height`. No center predicate
  is applied to the intentionally coarse fused root owner. The residual owner
  remains nonempty, all extracted intervals on the page are mutually
  disjoint, and no body byte, table/cell value, form value, outline entry,
  note, or label value is extracted; inverse reinsertion of every fragment and
  delimiter at its recorded offset reconstructs the configured predecessor
  scalar byte-for-byte; and
- the contribution and synthetic records satisfy every byte/count/reference
  limit below. Ambiguous mapping, partial overlap, repeated scalar matches,
  more than eight intervals, non-source fragment order, or a changed owner
  hash rolls the page back.

Projection creates one deterministic synthetic IR/public item of mapped
`header`/`footer` type whose value is exactly native `source_text` and whose
bbox is the exact native contribution bbox. It uses the same three US08 marker
keys and the same closed running descriptor as a direct item. Its source public
ID/path bind the unchanged fused predecessor owner. Its synthetic element owns
one additive deterministic contribution EvidenceRecord bound to that element
and the exact contribution bbox; the record aliases only the exact ordered
native source-object IDs as provenance. The record has method `native`, value
equal to exact `source_text`, confidence
`{"scope":"evidence","score":null,"unavailable_reason":"not_calibrated"}`,
and metadata with exactly `policy_id` plus the ordered `source_object_ids`.
The fused owner's evidence, element,
bbox, public value, Markdown, type, ID, nested records, prior semantic
descriptor, graph edges, and hash remain byte-for-byte unchanged. Terminal
stripping removes the synthetic evidence together with the synthetic
element/item/block.

Canonical construction alone replaces the fused owner's presentation with
the recorded residual and emits a synthetic block containing exact
`presentation_text` in `header` or `footer`. Every removed adjacent delimiter
is recorded and hashed for inverse reconstruction. `presentation_text` joins
the exact fragments in native source-span order, inserts each recorded
delimiter only between successive fragments, and omits the terminal outer
delimiter required to keep canonical block text free of outer whitespace. It
never copies intervening body bytes.
Thus `body` contains the residual with zero running contribution, while
`full` contains the residual plus the synthetic contribution exactly once.
The raw public owner remains preserved evidence and is not itself a second
canonical contribution. Stable synthetic IDs hash policy/source identity,
physical index, owner ID, source-object IDs, bbox ID, and role—never
contribution text. The acyclic formulas are closed: the synthetic element ID
uses those inputs without an evidence ID; the contribution evidence ID uses
prefix `running-region-evidence` over policy ID, source-document SHA-256,
physical page index, fused-owner public item ID, ordered native source-object
IDs, contribution bbox ID, and role; and the synthetic public-item ID then
uses that resulting evidence ID in its longer tuple. No arbitrary substring
extraction, semantic repair, prior-projector rewrite, or circular ID input is
permitted.

Accepted roles are exactly:

- `header` → public/IR type `header`, canonical scope `header`;
- `footer` → public/IR type `footer`, canonical scope `footer`;
- `navigation_top` → public/IR type `header`, canonical scope `header`;
- `navigation_bottom` → public/IR type `footer`, canonical scope `footer`.

The running-region descriptor preserves the distinct navigation role even
though canonical scope remains closed. A standalone accepted printed-label
item maps to `header` or `footer` according to its accepted owner/band; printed
identity remains page-level metadata and is not a fourth canonical scope.

An item already claimed, suppressed, or semantically owned by a prior Phase 03
projection is ineligible for direct retyping. Existing valid header/footer
ownership is preserved. The extracted-contribution exception may reference a
claimed owner only because it leaves that owner and its prior ownership
byte-identical. Its one additive evidence record is owned only by the
synthetic contribution element and aliases only exact native source-object
IDs; it receives canonical presentation custody only for the separately proven
contribution interval. Nested header/footer children remain owned
by their one primary furniture anchor and may not become separate canonical
blocks.

## Exact identity precedence

After safe-string validation, display selection is:

1. an unambiguous `detected_printed_label`;
2. otherwise a non-null safe `embedded_label`;
3. otherwise a nonempty safe unchanged legacy `page_label` as
   `legacy_display_fallback`; and
4. otherwise the decimal string of `physical_page_index` as `physical`.

The fourth tier is a display-only availability fallback. It neither changes
nor reinterprets legacy `page_label`, and it cannot be used for detected or
embedded agreement. A nonempty unsafe legacy value is retained byte-for-byte
outside the sidecar, emits `page_identity_display_unsafe`, and selects
`physical`; an empty/null legacy value selects `physical` without promoting a
concern. A valid positive `physical_page_index` always produces a safe display
string, so hostile legacy metadata alone cannot fail the document.

Agreement between a detected and embedded label means exact equality after
the closed detected normalization and embedded NFC/edge-whitespace
normalization. On agreement, `display_source` remains
`detected_printed_label`.

If both are non-null and differ:

- both fields and the detected `visible_text`/bbox/source remain present;
- `page_identity_source_conflict` is emitted;
- detected promotion fails closed;
- `display_source` is `embedded_label`; and
- `display_label` is the embedded label.

No sequence continuity, neighboring page, filename, page count, or legacy
value breaks a conflict. When multiple visible candidates conflict,
`detected_printed_label` and `visible_text` are null in the public sidecar,
the source report retains every bounded candidate, and selection falls through
to embedded, safe legacy, or physical display fallback.

If an earlier projection failure prevents a sidecar from being committed, the
predecessor page fields remain present, but a frontend that sees a
non-projecting US08 summary displays physical identity only and never renders
the unvalidated legacy label as UI chrome.

## Safe string and JSON byte rules

Semantic labels are Unicode NFC, nonempty, single-line strings with no outer
whitespace and at most 256 UTF-8 bytes. `visible_text` is the exact source span,
must be nonempty and single-line, and is capped at 512 UTF-8 bytes. Running
item text is not copied into a sidecar and remains subject to its configured
predecessor limits.

For the bounded extracted-contribution exception, private `source_text` is the
exact native character/word sequence used by the synthetic public/IR item and
private `presentation_text` is the exact ordered join of one to eight
predecessor presentation fragments used by the synthetic canonical block.
Both are equal to their Unicode edge-whitespace-stripped values; all retained
whitespace runs are therefore internal and explicitly mapped.
Every removed adjacent delimiter remains separately recorded and hashed for
inverse reconstruction; `presentation_text` inserts a recorded delimiter only
between successive fragments and omits the terminal outer delimiter.
`presentation_text` may contain no other bytes and is not a semantic label or
`visible_text`. Both strings, every fragment, and their ordered whitespace
mapping remain bounded by the contribution and detached-plan limits below.

Labels and visible text reject:

- C0/C1 controls, NUL, DEL, U+2028, U+2029, unpaired surrogates, and Unicode
  noncharacters;
- bidi embedding, override, isolate, and pop controls U+202A–U+202E and
  U+2066–U+2069;
- backslash, backtick, `<`, `>`, `&`, square/curly braces, and any character
  outside Unicode letters/numbers plus ASCII space, `.`, `_`, `-`, `:`, `/`,
  `|`, `(`, and `)`; and
- any string which changes under its required normalization unexpectedly.

The exact source bytes remain available only through bounded private evidence
hashes when public string safety rejects them. Diagnostics never log source
text, embedded metadata, visible labels, paths, URLs, or raw PDF objects.

All contract hashes and byte caps use compact UTF-8 JSON with sorted keys,
`allow_nan=false`, and separators `,` and `:`. Unknown or missing keys fail
validation. Booleans never satisfy integer fields. Floats must be finite.

## Closed machine contracts

Policy ID is `p03-running-regions-page-identity-v1`. Source report and public
sidecar schema versions are `1.0`.

### Source report

| Object | Exact keys |
|---|---|
| source report | `report_version`, `policy_id`, `source_sha256`, `status`, `pages`, `counts`, `concern_codes`, `extraction_ms` |
| source page | `page_index`, `page_width`, `page_height`, `unit`, `coordinate_system_id`, `source_character_count`, `source_word_count`, `embedded_label`, `label_candidates`, `boundary_candidates`, `concern_codes` |
| label candidate | `id`, `visible_text`, `normalized_label`, `bbox`, `source_object_ids`, `source_method`, `confidence`, `concern_codes` |
| boundary candidate | `id`, `public_item_id`, `public_path`, `element_id`, `predecessor_type`, `bbox`, `bbox_id`, `evidence_ids`, `source_object_ids`, `raw_layout_role`, `normalized_signature`, `boundary_band`, `source_method`, `confidence`, `concern_codes`, `disposition` |
| source counts | `page_count`, `source_character_count`, `source_word_count`, `embedded_label_count`, `label_candidate_count`, `boundary_candidate_count`, `concern_count` |

Source-report status is exactly `available`, `unavailable`, or `refused`.
Pages are ordered by unique one-based `page_index`; report `page_count` and all
aggregate counts equal exact page sums. An ordinary page reports exact counts.
A page-level source refusal has empty candidate arrays and exactly one concern;
its character/word counters are bounded sentinels while the private document
ledger charges exact observed totals.

For a direct boundary candidate, `public_item_id`, `public_path`, and
`element_id` bind that item and its existing element. For an
`extracted_source_contribution` candidate, the public ID/path bind the
byte-identical fused predecessor owner, `element_id` is the deterministic
synthetic contribution element, `bbox`/`bbox_id` bind only the contribution,
and `predecessor_type` is the fused owner's exact type. The exact ordered
scalar byte intervals, `source_text`/`presentation_text` hashes, ordered
source-span and whitespace byte-range mappings, delimiters, residual, and
their custody hashes live only in the bounded detached projection plan; the
closed source-report keys do not expand.
Every range is a half-open UTF-8 byte interval within its named string or
predecessor scalar. Exact range coverage, string hashes, owner-before hash,
each removed-interval and delimiter hash, ordered-plan hash, and residual hash
are replay-validated; unknown keys, overlapping ranges, an out-of-bounds
range, or more than eight intervals fail closed.

The authoritative source-to-projection binder receives the projected public
document and source report together with an explicit configured
`predecessor_document`. Supplying projected IR also requires explicit
`predecessor_ir`; a predecessor IR without projected IR is invalid. Extracted
plans and the bounded comparison ledger are explicit keyword ledgers, never
reconstructed from public descriptors or defaults. The binder validates those
private ledgers before accepting public/canonical/IR custody.

### Bbox, confidence, and source objects

A contract bbox has exactly `x`, `y`, `width`, `height`, and `unit`. Unit is
`pt` for this native-PDF v1.

Confidence has exactly `scope`, `score`, and `unavailable_reason`:

- accepted deterministic recognition uses
  `{"scope":"deterministic_rule","score":1.0,"unavailable_reason":null}`;
- accepted embedded metadata uses
  `{"scope":"source_metadata","score":1.0,"unavailable_reason":null}`;
- legacy fallback uses scope `unavailable`, null score, and reason
  `page_identity_source_unavailable`;
- physical fallback uses scope `unavailable`, null score, and reason
  `page_identity_display_fallback_physical`; and
- a non-null score is finite in `[0,1]`; score and unavailable reason are
  mutually exclusive.

A boundary candidate's `disposition` is exactly `accepted` only when its
confidence is deterministic recognition at score `1.0` and it has no concern
codes; every other candidate is `rejected`. Projection consumes only accepted
candidates. All 47 reviewed oracle boundary candidates satisfy the accepted
rule.

Source object IDs are bounded opaque IDs derived from reader object identity,
never raw object dumps. Arrays are ordered, unique, and have no empty string.
Candidate IDs are deterministic and text-free. A label-candidate ID uses the
`label-candidate` prefix over policy ID, source-document SHA-256, physical page
index, ordered native source-object IDs, and exact candidate bbox. A boundary-
candidate ID uses the `boundary-candidate` prefix over policy ID,
source-document SHA-256, physical page index, fused/direct owner public item
ID and path, source element ID, bbox ID, ordered evidence IDs, ordered source-
object IDs, boundary band, and source method. Report validation recomputes
both formulas; an opaque but otherwise coordinated replacement ID fails.

### Public and canonical `page_identity`

The exact keys are:

| Key | Contract |
|---|---|
| `schema_version` | literal `1.0` |
| `policy_id` | literal `p03-running-regions-page-identity-v1` |
| `page_id` | nonempty stable IR page ID |
| `physical_page_index` | strict positive integer equal to public and canonical `page_index` |
| `embedded_label` | safe semantic label or null |
| `detected_printed_label` | normalized detected label or null |
| `visible_text` | exact safe source-visible span or null |
| `display_label` | safe selected semantic label |
| `display_source` | `detected_printed_label`, `embedded_label`, `legacy_display_fallback`, or `physical` |
| `evidence_bbox` | exact source bbox whenever a detected value is retained, including conflict; otherwise null |
| `evidence_source` | exact closed source binding below |
| `confidence` | exact confidence object |
| `concern_codes` | sorted unique known page-identity concern codes |

`evidence_source` has exactly:

`method`, `reader`, `page_index`, `public_item_id`, `public_path`, `element_id`,
`bbox_id`, `evidence_ids`, and `source_object_ids`.

Its allowed triples and nullability are:

- detected: method `native_printed_label`, reader `pdfplumber`, exact page,
  nonempty ordered native source-object IDs, nonempty retained source-report
  label-candidate evidence IDs, and non-null exact `evidence_bbox`. The
  remaining public binding is exactly one of two all-or-nothing shapes:
  `exact_public_binding` has a non-null public item, nonempty public path, and
  non-null element/bbox IDs, and the resolved retained public bbox equals
  `evidence_bbox`; `native_source_only` has null public item/element/bbox IDs
  plus an empty public path;
- embedded: method `embedded_pdf_label`, reader `pypdfium2`, exact page, null
  public item/element/bbox IDs, empty public path, nonempty page-label evidence
  and source-object IDs, and null `evidence_bbox`;
- legacy fallback: method `legacy_display_fallback`, reader
  `configured_predecessor`, exact page, null IDs, empty public path/evidence
  arrays, one bounded predecessor page source-object ID, and null bbox. That
  ID is source-scoped as
  `configured-predecessor:{source_sha256}:page:{physical_page_index}:page_label`;
  it contains no case name or filename.
- physical fallback: method `physical_page_index`, reader
  `configured_predecessor`, exact page, null IDs, empty public path/evidence
  and source-object arrays, and null bbox.

When detected and embedded sources conflict, evidence binding remains the
detected source even though embedded supplies `display_label`; both sources
remain represented by their dedicated fields and the conflict concern.
`confidence` always describes the selected `display_label`; in this one
conflict case `evidence_source` and `evidence_bbox` deliberately preserve the
rejected detected provenance instead of describing the embedded selection.

Every page with exactly one eligible retained label candidate must select that
candidate as `detected_printed_label`; projection may not silently downgrade
it to embedded, legacy, or physical fallback. Zero or ambiguous eligible
candidates follow the closed precedence/failure rules above.

The detected source-only shape is required whenever no retained public item
has exactly the native span bbox. Its evidence IDs bind the retained private
source-report label candidate; they are not IR `EvidenceRecord` IDs and IR
validation must not try to resolve them. It never fabricates a public item, IR
element, bbox/evidence record, or canonical block merely to provide a page
label binding. Its selected boundary owner is private validation custody, not
an ID substituted into the public sidecar. A partial/mixed shape, an empty
candidate/source-object array, a nearest or enclosing item substituted for an
exact-public span, a source-only owner lacking the closed native-word/geometry
proof above, or a claimed exact-public binding whose resolved bbox differs
fails validation.
Running-region descriptor public bindings are independent and remain
mandatory for every accepted direct or extracted region under their rules
below.

`public_path` is an ordered array of nonempty strings and nonnegative strict
integers rooted at `pages`. It must resolve to the exact source value and bbox
in the public predecessor. The public and canonical `page_identity` objects
must be recursively equal.

`page_identity` is optional only when US08 is absent, unavailable,
not-applicable, or failed closed. With processing status `projected`, every
public page and every canonical page has exactly one sidecar and the sidecars
cover the same unique sorted physical indexes as the document pages.

### Running-region public descriptor

An accepted public item has all three marker keys:

- `layout_running_region_projected: true`;
- `running_region_policy: "p03-running-regions-page-identity-v1"`; and
- `running_region`: the closed descriptor below.

The descriptor has exactly:

`id`, `page_id`, `physical_page_index`, `role`, `canonical_scope`,
`source_public_item_id`, `source_public_path`, `source_element_id`,
`predecessor_type`, `predecessor_item_sha256`, `bbox_id`, `bbox`,
`evidence_ids`, `source_object_ids`, `source_method`, `repetition_group_id`,
`repetition_page_indexes`, `confidence`, `concern_codes`, and
`canonical_block_id`.

Validation requires:

- the role/type/scope mapping frozen above;
- for a direct descriptor, source public item ID equal to the marked owning
  public item ID and source path resolving exactly to that item;
- for an `extracted_source_contribution` descriptor, source public item ID/path
  resolving to the unchanged fused predecessor owner while the marked outer
  item is the deterministic synthetic contribution item;
- page, element, bbox, evidence, and canonical block references resolving on
  the same page;
- bbox equality with the direct source item's canonical page-space bbox or,
  for extraction, with the exact native contribution bbox;
- `predecessor_type` equal to the exact direct-item type before US08
  reclassification or the exact fused-owner type for extraction;
- `predecessor_item_sha256` equal to the compact JSON hash of the restored
  direct item or the byte-identical fused predecessor owner, respectively;
- `source_method` exactly `trusted_layout_role`, `cross_page_repetition`,
  `boundary_navigation`, `printed_label_boundary`, or
  `effective_boundary_cluster`, except that the bounded exception uses
  exactly `extracted_source_contribution`;
- a null repetition group with an empty page-index array, or a non-null stable
  group ID with at least two unique sorted physical page indexes including the
  current page; and
- one included canonical block whose primary element is the descriptor source
  element, whose ID equals `canonical_block_id`, and whose scope equals
  `canonical_scope`; and
- for extraction only, exact synthetic public/IR value equal to `source_text`,
  exact synthetic canonical-block content equal to `presentation_text`, and a
  fully replayed detached whitespace mapping and hash set. Text is excluded
  from all deterministic ID inputs.

For predecessor-item hashing, the compact public item is the exact feature-off
wire `ContentItem`: top-level fields whose value is JSON `null` are omitted,
while nulls inside additive nested extension objects remain byte-significant.
The raw mapping must validate to that same compact typed payload without value
or type coercion before hashing. This keeps an intermediate materialized
optional default from changing custody and rejects boolean/string numeric
drift. A direct descriptor retains only the ordered element evidence records
whose element and bbox IDs equal its selected owner element and bbox; unrelated
nested-provenance evidence remains unchanged in the IR and is not claimed by
the descriptor.

Direct region IDs are stable hashes of policy ID, source document identity,
physical page index, source element ID, bbox ID, and role. Extracted region and
synthetic public-item IDs use prefixes `running-region` and
`running-region-item`, respectively, over the same longer tuple: policy ID,
source-document SHA-256, physical page index, fused-owner public item ID,
ordered native source-object IDs, ordered synthetic evidence IDs,
contribution bbox ID, and role. Repetition group IDs hash the policy ID,
source-document SHA-256, boundary band, and normalized signature, so textually
identical signatures from different documents cannot collide. Raw
label/display text is never an ID input.

### IR bindings

`PageRecord.page_identity` is the same strict descriptor serialized publicly.
`ElementRecord.running_region` is the typed equivalent of the public running
descriptor. Both are optional only outside a committed US08 projection.

IR validation additionally requires:

- exact one-to-one public/IR page identity;
- exact public/IR running-region ID, role, source, bbox, and canonical binding;
- no running region on a diagnostic/alternate element;
- no duplicate or cross-page ownership;
- no form, outline, table/cell, visual, caption, note, or prior-projection
  contributor overlap, except that one eligible extracted contribution may
  bind its sole unchanged fused owner under the closed exception; and
- every retained predecessor evidence record to remain present and singly
  owned; an extracted synthetic element owns one additive contribution
  EvidenceRecord at the exact contribution bbox, whose native source-object
  provenance may alias the fused owner's source objects without changing the
  owner's evidence.

Outside the bounded extracted-contribution exception, US08 adds no new public
item or synthetic content relationship. The exception adds one synthetic
contribution element/item/block, one contribution bbox, and one contribution
EvidenceRecord, but no relationship and no predecessor-owner change. US08
never adds a physical page ID. Raw predecessor graph, source elements,
evidence, bboxes, and prior Phase 03 descriptors remain present and
byte-equivalent except for a direct item's explicit US08 type/sidecar, the
strict page sidecar, and those additive extracted-contribution records.

### Processing summary

`processing.running_regions` has exactly:

`policy_id`, `status`, `reason`, `source_page_count`, `identity_count`,
`detected_label_count`, `embedded_label_count`, `legacy_fallback_count`,
`candidate_count`, `comparison_count`, `running_region_count`, `header_count`,
`footer_count`, `top_navigation_count`, `bottom_navigation_count`,
`concern_count`, `extraction_ms`, `projection_ms`, and `total_ms`.

Status is `projected`, `unavailable`, `not_applicable`, or `failed_closed`.

- `projected` has null reason, identity count equal to source/public/canonical
  page count, display-source counts summing to identity count, region role
  counts summing to running-region count, and exact candidate/comparison/
  concern counts;
- `legacy_fallback_count` is the stable fallback-tier counter and includes
  both `legacy_display_fallback` and `physical` display decisions; exact
  per-source identity remains available in each sidecar;
- `unavailable` uses reason `running_region_source_evidence_unavailable` or
  `running_region_source_limit` according to the source-report outcome;
- `not_applicable` is PDF-extractor-inert and uses reason
  `running_region_input_not_applicable`;
- `failed_closed` uses reason `running_region_projection_failed_closed`; and
- every non-projecting status has zero feature counts, no page/region
  sidecars, and the exact configured predecessor under all pre-existing keys.

Timings are finite nonnegative milliseconds rounded to three decimals, and
`total_ms = extraction_ms + projection_ms` after the same rounding rule.
`candidate_count` includes direct and extracted-contribution candidates;
`running_region_count` and role counts include committed synthetic regions.
The closed processing keys do not expose content, owner IDs, or separate
extracted counts; those are verified from strict descriptors and the private
bounded plan ledger.

## Known concern codes

Only these US08 concern codes are public:

- `running_region_source_evidence_unavailable`;
- `running_region_source_limit`;
- `running_region_candidate_limit`;
- `running_region_geometry_ambiguous`;
- `running_region_repetition_ambiguous`;
- `running_region_navigation_ambiguous`;
- `running_region_ownership_conflict`;
- `page_identity_embedded_label_invalid`;
- `page_identity_detected_label_ambiguous`;
- `page_identity_source_conflict`;
- `page_identity_display_unsafe`;
- `running_region_canonical_custody_invalid`;
- `running_region_projection_failed_closed`; and
- `running_region_concerns_truncated`.

Concern arrays are sorted, unique, and bounded. IR concern records contain a
stable code, physical `source_ref=page:<index>` when page-scoped, bounded
counts/caps, and optional exception class only. They contain no label, visible
text, item value, raw metadata, path, URL, or PDF object.

## Stage order and coexistence

Source evidence is extracted only when the flag is enabled, but projection is
the final Phase 03 layout stage. The exact order is:

1. accepted table captions, visual relationships, and source notes;
2. P03-US04 relationship order;
3. P03-US05 text runs;
4. P03-US06 forms/key-values;
5. P03-US07 outlines;
6. P03-US08 running regions and page identity;
7. strict IR/public validation and canonical serialization; and
8. optional terminal source-text alignment with strip/replay.

When a preceding optional flag is disabled, US08 still occupies the same final
layout slot. The direct path may change only an accepted unclaimed item's
`type` to the role-mapped `header`/`footer` value and add its strict sidecar.
The extracted-contribution path may instead add exactly one synthetic
item/element/block and one canonical-only owner presentation override per
accepted contribution. Neither path changes predecessor page IDs, values,
Markdown, nested records, bboxes, source, confidence, evidence, relationships,
array order, or `reading_order`. Synthetic public evidence items are appended
in stable ID order after every predecessor item and receive the next
contiguous ranks, so predecessor item bytes/ranks remain unchanged; their
canonical blocks occupy the deterministic source-proven P03-US04 positions.

P03-US04 order remains authoritative. Direct US08 changes canonical scope, not
page array topology. Prior projector ownership always wins; an overlap retains
the predecessor and emits `running_region_ownership_conflict`, except that a
fully eligible extracted contribution may be added beside its unchanged owner
under the narrow rules above.

## Canonical and serializer custody

Canonical `schema_version`, `source_ir_version`, policy ID, and block-scope
enum remain unchanged. `page_identity` is the sole US08 additive optional key
on a canonical page and is required on every page only for a projected US08
summary.

For each accepted direct running region:

- its one existing primary block changes scope according to the frozen role
  mapping;
- `body` excludes it;
- `header` or `footer` includes it once;
- `full` includes it once at the accepted P03-US04 presentation position;
- nested furniture children contribute only through their one anchor block;
  and
- no synthetic page-label block or duplicate text is created.

For each accepted extracted contribution:

- one synthetic contribution block is included once in `header` or `footer`;
- the fused predecessor owner's canonical block is rebuilt from its exact
  recorded residual for `body` and `full`, while the public owner is unchanged;
- the synthetic block is absent from `body`, present once in its mapped scope,
  and present once in `full` at the source-proven P03-US04 position; and
- under the recorded delimiter rule, inverse reinsertion of every exact
  presentation fragment and every separately recorded adjacent delimiter at
  its recorded residual offset must reconstruct the configured predecessor
  canonical bytes byte-for-byte. The synthetic canonical text is their
  native-source-order `presentation_text`, with delimiters inserted only
  between fragments and the terminal outer delimiter omitted; the public/IR
  synthetic value remains exact native `source_text`. Body retains only the
  residual, while header/footer and full contain the joined running
  contribution exactly once. A missing byte,
  duplicate byte, changed non-running byte, invalid span/whitespace mapping,
  non-source fragment order, or second canonical claim fails closed.

Complete canonical validation requires every included element to be claimed
once, every running descriptor to bind its exact block, every extracted owner
to bind its predecessor and residual hashes, and the public and canonical page
identities to be recursively equal. Any mismatch, duplicate, missing
contribution, extra scope member, or changed core page field fails the US08
document transaction closed.

Serialization policy is exact:

- backend `/v1/parse?output_format=markdown`, document Markdown copy/download,
  and normalized-document `markdown_full` and `text_full` use canonical
  document `full`;
- canonical page `body` is the authoritative page-body Markdown/text;
- normalized JSON `markdown.pages[].markdown` and `text.pages[].text` use
  canonical page `body` and expose canonical header/footer views separately;
- an explicit frontend `Body | Full` page-view control selects exact stored
  canonical page views; it does not rebuild them. A validated `projected`
  US08 result initializes this control to `Body`; absent and nonprojecting
  US08 results retain legacy initial-selection behavior. Compatibility
  serializers may continue to default to `Full` unless the caller passes an
  explicit view; and
- page-scoped copy/download copies the selected stored view and labels the
  action accurately.

The frontend is never a second running-region detector.

## Frontend validation, navigation, and injection safety

The frontend first performs an O(1) own-property check for
`processing.running_regions`. When absent, it performs zero US08 page traversal,
validation, indexing, rendering, or serialization work. When present:

- `projected` requires a strict exact-key validator over the publicly
  observable contract: the processing summary, every public/canonical page
  sidecar, every running item descriptor, lowercase-64 compact-hash shape plus
  exact owner ID/path correlation, synthetic append/value custody, canonical
  block IDs/scopes/views/counts, bboxes, roles, public source paths, and
  public/canonical equality;
- the validator permits source-owner/marked-item ID inequality only for
  `source_method = extracted_source_contribution`, then requires the synthetic
  append position and value, exact source-owner ID/path correlation, a
  lowercase-64 descriptor compact hash, contribution bbox, exact canonical
  ID/scope/view memberships and counts, and single inclusion defined above;
- `unavailable`, `not_applicable`, and `failed_closed` require zero US08
  sidecars and accept only the predecessor canonical contract;
- a present malformed, partial, unknown-version, count-inconsistent, or
  cross-page contract raises typed `invalid_running_regions`; it never falls
  back to client inference or raw page labels; and
- only absence selects legacy behavior.

The frontend neither receives nor validates the private source report or
detached extraction plan. Backend validation alone proves source-candidate
selection, repetition signature/member geometry, native source-object
geometry, byte intervals, residual reconstruction, delimiter/source-span/
whitespace mappings, their private hashes, and recomputation of every
`predecessor_item_sha256`. No public proof object is added for those checks;
the frontend validates only the public custody correlations and digest shape
listed above. In particular, it never recomputes Python compact-JSON hashes
from JSON-parsed JavaScript numbers.

Physical UI navigation, preview synchronization, canonical lookup, keyboard
navigation, page input, and announcements use one-based `page_index` only.
Projected output requires unique, contiguous page indexes `1..page_count` and
exact public/canonical coverage. `page_number`, legacy `page_label`, embedded,
detected, visible, and display labels never enter `mapPhysicalPages`.

The validated `display_label` is rendered only as React text in a bidi-isolated
element such as `<bdi dir="auto">`. It is never passed to
`dangerouslySetInnerHTML`, a Markdown renderer, URL, style, selector, filename,
or ARIA page-number control. Accessibility text states physical page first and
then the optional printed display label. When US08 is present but not
projected, UI chrome shows physical identity only.

Body/full selection, rendered/source views, normalized JSON, copy, and download
must all consume the same validated canonical object. Normalized per-page
`text.pages[].text` and `markdown.pages[].markdown` remain the stored `body`
view regardless of the interactive page-view selection; document
`text_full`/`markdown_full` remain stored `full`. Mobile and desktop page bars
use the same physical-page map and display-label component.

## Page rollback, document rollback, and fail-closed behavior

Projection starts from a fresh detached clone of the exact post-US07 configured
predecessor, thawed only from the factory-validated private authority template.
Each page is built and validated on a detached candidate. A failed page thaws
its rollback source from that same private template rather than rereading
caller-owned state.

A page-scoped candidate, repetition, navigation, geometry, ownership,
comparison, or page-limit failure:

- discards every running-region type/sidecar mutation on that page;
- removes every synthetic contribution item/element/block and canonical-only
  presentation override planned or applied on that page;
- preserves all pre-existing page keys/items byte-for-byte;
- commits a fresh strict `page_identity` by applying normal precedence to
  independently validated identity evidence; if the identity decision itself
  failed, detected promotion is discarded and selection uses safe embedded,
  safe legacy, then physical fallback, with bounded concerns;
- gives the canonical page the recursively equal fallback sidecar; and
- allows unaffected pages to commit.

This additive sidecar and content-free concern are the only allowed
differences on a rolled-back page. Only an invalid/nonpositive physical index
or inability to bind the exact predecessor page escalates identity fallback
to document scope; unsafe/empty legacy display text selects `physical`.

Source SHA/page-count mismatch, report/refusal schema failure, document count
or byte overflow, source/projection document deadline, display identity from
an invalid/nonpositive physical index, duplicate/cross-page identity, final
IR/public validation failure,
canonical custody failure, or terminal identity failure restores the complete
post-US07 predecessor. No US08 page/region sidecar or type change survives.
Only the exact non-projecting processing summary and one content-free document
concern are added.

No exception text, source content, raw object, path, URL, or embedded label is
copied into a public warning or concern.

## Terminal source-alignment strip and replay

US08 must participate in the existing terminal source-alignment transaction.
Before source alignment, a strict reverse projector receives the exact
configured `predecessor_document` and, whenever projected IR is present, the
exact configured `predecessor_ir`. It never infers either predecessor merely
by deleting fields. The reverse projector:

1. validates the complete processing summary, public/canonical page identity,
   running descriptors, canonical bindings, and hashes;
2. removes every public/IR/canonical `page_identity` sidecar;
3. validates each direct running descriptor, restores `predecessor_type`,
   removes the three US08 marker keys, and verifies
   `predecessor_item_sha256`;
4. for each extracted descriptor, verifies the unchanged fused owner, every
   detached interval/delimiter hash, the ordered plan hash, and inverse
   reconstruction, deletes the synthetic public/IR/canonical record,
   discards the canonical-only presentation override, and restores the exact
   predecessor public/canonical arrays and ranks;
5. removes US08 processing/concern records;
6. compact-JSON-byte-compares the fully derived public predecessor and, when
   present, derived IR predecessor with their explicit configured inputs; and
7. refuses stripping if any US08-looking field is partial, malformed, unknown,
   multiply owned, plan-incomplete, or not exactly reversible.

The stripped document is the sole input to terminal source alignment. When
alignment selects content, the complete configured IR/layout/canonical stack
re-enters once, including the original bounded US08 source evidence.

Before strip, the pipeline records an ordered US08 replay identity containing:

- each page ID, physical index, embedded/detected/visible/display labels,
  display source, evidence bbox/source, and concerns; and
- each region ID, role, source public item/element/path, bbox, evidence IDs,
  source method, source-object IDs, predecessor-owner hash, ordered extracted
  interval/delimiter hashes and offsets when applicable,
  `source_text`/`presentation_text` hashes, source-span/whitespace/plan hashes,
  repetition identity/pages, and canonical block ID.

After replay, status must again be `projected`; page/region/count identity must
match exactly. Running item text, its predecessor hash, or an extracted
owner/residual hash may differ from the pre-strip witness only when the
terminal alignment summary proves the selected source text in that exact
owner; those alignment-authorized hash values are deliberately excluded from
graph identity and become the new replay witness. Page labels and their
visible source evidence may not drift. A fewer/different region, changed
role/page/bbox/source/canonical binding, missing page sidecar, changed display
decision, changed synthetic/residual identity, or failed replay restores the
complete pre-alignment public and canonical predecessor atomically and reports
source alignment unavailable.

Repeated terminal application is idempotent.

## Resource, deadline, and complexity limits

Production limits are inclusive:

| Resource | Limit | Overflow scope |
|---|---:|---|
| source PDF bytes | 25 MiB (26,214,400 bytes) | document |
| pages | existing parser limit, at most 100 | document |
| native source characters/page | 500,000 | page |
| native source characters/document | 2,000,000 | document |
| source words/page | 100,000 | page |
| source words/document | 500,000 | document |
| embedded/detected/display label | 256 UTF-8 bytes | page/document if required fallback |
| visible label text | 512 UTF-8 bytes | candidate/page |
| running candidate source text | 16 KiB | candidate/page |
| extracted contribution text | 4 KiB | contribution/page |
| predecessor intervals/extracted contribution | 8 | contribution/page |
| extracted contributions/page | 8 | page |
| extracted contributions/document | 64 | document |
| extracted residual-plan bytes/page | 16 KiB | page |
| extracted residual-plan bytes/document | 256 KiB | document |
| printed-label candidates/page | 64 | page |
| non-stroking fills/printed-label candidate | 256 | candidate/page |
| intersecting text objects/printed-label candidate | 256 | candidate/page |
| scanned PDF text objects/printed-label candidate | 10,000 | candidate/page |
| PDF form-object depth for printed-label custody | 8 | candidate/page |
| rendered candidate dimension | 2,048 px/axis | candidate/page |
| rendered candidate pixels | 262,144 | candidate/page |
| displayed PDF page dimension for visibility | 20,000 pt/axis | page |
| live source-projection authorities | 8 | process/document |
| boundary candidates/page | 512 | page |
| boundary candidates/document | 10,000 | document |
| accepted running regions/page | 64 | page |
| accepted running regions/document | 2,048 | document |
| repetition groups/document | 2,048 | document |
| pages/repetition group | 100 | group/document |
| evidence IDs or source-object IDs/record | 64 each | record/page |
| public path segments | 16 | record/page |
| indexed comparisons/page | 4,096 | page |
| indexed comparisons/document | 65,536 | document |
| complete page-identity JSON | 64 KiB | page/document |
| complete running descriptor JSON | 256 KiB | region/page |
| complete source report | 8 MiB | document |
| US08 concerns/page | 64 | page |
| US08 concerns/document | 256 | document |
| source extraction deadline | 2.0 s/document | document |
| projection deadline | 250 ms/page and 2.0 s/document | page/document |

Exact observed counts are charged before allocation/comparison. Page-scoped
overflow emits one candidate-free page refusal and continues with unaffected
pages; document-ledger/report/deadline overflow refuses the complete report or
projection. String caps use UTF-8 bytes and JSON caps use the compact rule.

Recognition is bounded `O(C log C + E)` for candidates `C` and retained
evidence references `E`: candidates are indexed by page, boundary band, and
normalized signature; no all-pairs page/item/text scan, regular expression
with unbounded backtracking, recursive source walk, or unbounded diagnostic
materialization is permitted. Deadline checks span matching, repetition,
planning, detached mutation, canonical build, validation, and final commit.

Every integer/byte cap requires exact-limit and maximum+1 witnesses that invoke
the production validator or accounting hook. Compact-JSON byte witnesses use
complete contract-valid identity, descriptor, and source-report objects, not a
standalone JSON-string comparator. Deadlines require injected monotonic-clock
witnesses at page, document-projection, and source-document boundaries.

## Feature flag and exact rollback

The public setting is `parser.layout.running_regions.enabled`; the environment
variable is `PARSER_LAYOUT_RUNNING_REGIONS_ENABLED`. It defaults to `false` and
requires:

- `PARSER_SHARED_IR_ENABLED=true`;
- `PARSER_SHARED_IR_NORMALIZATION_ENABLED=true`;
- `PARSER_CANONICAL_SERIALIZATION_ENABLED=true`; and
- `PARSER_LAYOUT_RELATIONSHIP_ORDER_ENABLED=true`.

It does not require text-run, forms, outlines, or terminal source alignment,
but coexists with any enabled combination.

With the flag off there is zero US08 source extraction, module import,
argument forwarding, projection, page traversal, processing summary, public/
IR/canonical field, item type change, concern, warning, frontend validation,
or serialization work. The exact configured predecessor—including the current
legacy page identity—is byte-identical.

Rollback is one setting change:

`PARSER_LAYOUT_RUNNING_REGIONS_ENABLED=false`.

No other Phase 03 setting changes.

## Mandatory fixtures and adversarial tests

Before Ready, the following deterministic artifacts must exist and be locally
readable by both `pdfplumber` and `pypdfium2` where applicable:

- exact 30-page real-corpus page/running-region oracle;
- embedded-only safe label, detected/embedded agreement, detected/embedded
  conflict, unsafe embedded label, Roman/prefixed embedded label, and absent
  embedded label;
- detected exact-public-binding and native-source-only positives, including
  the real-corpus source-only exact-word and composite-subspan cases, plus
  mixed-shape, fabricated-item, empty-candidate-evidence, empty-source-object,
  mismatched-exact-bbox, unlinked/partial native-word set, duplicate owner,
  less-than-`0.80` candidate coverage, over-`0.2%` center delta, and
  sliver-only overlap negatives;
- safe legacy fallback, empty legacy physical fallback, hostile legacy
  physical fallback, and invalid physical-index document refusal;
- `Page X of Y`, `X / Y`, `PAGE | X`, composite-footer suffix, trusted top bare
  label, and standalone bottom bare label positives;
- body number near an edge, heading near the top, date/currency/percentage,
  table cell, chart label, form value, outline marker, source/footnote, and
  multiple-visible-candidate negatives;
- visible and white-on-white candidates at intrinsic rotations `0`, `90`,
  `180`, and `270`; exact delta-16 and below-delta-16 threshold witnesses;
  light-on-dark, transparent, unpainted, stroke-only, clip-only, absent-object,
  mismatched-fill, malformed-fill, degenerate-object, and bounded text-object
  scan/form-depth controls;
- repeated boundary positive, repeated body-text negative, single-page
  navigation positive, single-page heading negative, varying-page placeholder,
  and inconsistent-band/geometry negatives;
- the source-grounded three-item same-baseline effective-bottom cluster and
  exact `boundary_navigation` / `effective_boundary_cluster` /
  `printed_label_boundary` role split, plus its missing-cue, missing-label,
  two-item, overlapping-body, claimed-owner, noncontiguous-order,
  outer-30%-overflow, and ambiguous-cut negatives;
- the repeated manufacturing header fused into a visual/body owner, exact
  native `source_text`/bbox for the synthetic public/IR header, exact
  predecessor `presentation_text` for the synthetic canonical header, the
  bounded ordered multi-interval/source-span and one-to-one whitespace-run
  mappings, inverse byte-exact reconstruction, all custody hashes, canonical
  residual, unchanged public owner, and
  negatives for non-native, non-repeated, non-line, leading/trailing/both outer
  source whitespace, multi-match, overlapping, body-byte capture,
  more-than-eight-interval, non-source-order, table/form/outline-owned,
  missing nested-native graph ownership, less-than-`0.99` root-owner coverage,
  less-than-`0.90` child-union coverage, over-`0.2%` child-center delta,
  mismatched native evidence bbox, overlap-only ownership, over-limit, and
  changed-owner contributions;
- invalid/cross-unit/cross-page/NaN/zero/out-of-page bboxes, duplicate paths,
  shared owners, prior-projector ownership, malformed counts, unknown keys,
  wrong versions/policies, and public/canonical mismatch;
- exact/max+1 resource and byte cases plus all injected deadlines;
- partial mutation, page rollback, document rollback, canonical failure,
  direct/extracted stripping refusal, successful terminal replay, hostile
  fewer/different or residual-drift replay, idempotence, and flag-off zero
  work; and
- hostile labels containing HTML/script-like text, Markdown links/images,
  percent/entity encodings, CR/LF/tab/NUL, C0/C1, bidi overrides/isolates,
  U+2028/U+2029, unpaired surrogates, noncharacters, outer whitespace,
  overlong UTF-8, and unsupported punctuation.

Backend tests must prove raw-graph, ID, bbox, evidence, relationship, prior
semantic sidecar, array order, `reading_order`, and legacy identity coexistence.
Frontend tests must prove strict schema refusal, physical-only navigation,
canonical/body/full parity, safe bidi-isolated text rendering, no raw HTML,
copy/download parity, mobile behavior, and the O(1) flag-off guard.

## Quality, performance, and retained custody

The fixed quality gates are:

- exact 30/30 reviewed physical/printed outcomes, including all three nulls;
- exact accepted running-region roles/bboxes and 100% of the frozen pairwise
  order denominator;
- exact repeated manufacturing report header recovery on every reviewed page,
  including the fused-page extracted contribution with unchanged public owner
  and exact native source geometry/text, byte-exact predecessor presentation
  reconstruction, and zero canonical body/full duplication;
- exact ESG effective-bottom navigation/footer cluster custody under the
  generic geometry rule, with its body clean and full view singly inclusive;
- zero printed-label promotion on every negative/control;
- zero duplicate or missing canonical contribution in body/header/footer/full;
- byte-identical legacy `page_index`, `page_number`, and `page_label` in all
  modes; and
- deterministic IDs, sidecars, canonical views, summaries, and concerns over
  repeated projection and terminal replay.

Whole-parser `PAIRED_CASES` is exactly
`("uber-earnings", "ny-timetable")`. Enumeration is target-major, then
ascending pair index, then state order within the pair. Each target uses five
pairs and ten new OS workers, for sequential `worker_index` values `0..19`:
Uber occupies `0..9` and timetable `10..19`. Pair indexes `0..4` run exactly
`off/on`, `on/off`, `off/on`, `on/off`, `off/on`; each state has its own
process and no sample is dropped or retried. A timeout, nonzero worker exit,
nonfinite measurement, or source/code/custody mismatch fails the measurement
candidate. The worker reads and verifies the source and loads imports/settings
before timing, then places `time.perf_counter_ns()` immediately around the
production `parse_document(source_bytes, filename, settings)` call. Post-parse
serialization is outside that interval, and process exit releases the output.
Operating-system caches are not flushed and no cold-cache claim is made.

Every retained stage mapping uses the exact frozen target set and an ordered
prefix of the frozen target sequence. Prefix validation is based on target-set
membership, never canonical-JSON mapping-key order; ledgers inside a target
remain in their separately declared order. If all samples for a paired target
complete but its latency or RSS aggregate fails, the artifact retains that
complete target evidence and one target-scoped `stage_failed` record with null
pair/state, the complete worker plan, and the first failed target. It may not
encode a completed target as an omitted prefix.

For a finite nonnegative sequence `xs`, inclusive nearest-rank p95 is exactly
`sorted(float(xs))[ceil(0.95 × len(xs)) - 1]`; there is no interpolation. For
each pair `i`:

- `signed_i = on_i.wall_seconds - off_i.wall_seconds`;
- `clipped_i = max(signed_i, 0.0)`;
- `overhead_p95 = p95(clipped_0..clipped_4)`;
- `off_p95 = p95(off_0..off_4)`;
- `relative_ceiling = 0.05 × off_p95`; and
- `effective_ceiling = min(relative_ceiling, fixed_ceiling)`.

The fixed ceilings remain the M0 guards: Uber
`29.15 s × 5% = 1.4575 s` and timetable
`46.76 s × 5% = 2.3380 s`. A target passes only when
`overhead_p95 <= relative_ceiling` and
`overhead_p95 <= fixed_ceiling`, equivalently when it does not exceed the
effective ceiling.

Each worker records raw
`resource.getrusage(resource.RUSAGE_SELF).ru_maxrss`, platform, normalization,
and normalized bytes. Darwin values are already bytes; Linux values are
multiplied by 1,024; any other platform fails the candidate. For each pair,
`rss_delta_i = max(on_i.rss_bytes - off_i.rss_bytes, 0)`. The authoritative
memory gate for each target is
`max(rss_delta_0..rss_delta_4) <= 67,108,864` bytes (exactly 64 MiB).

Isolated source extraction and running-region projection are measured on both
paired targets. Latency uses exactly two successful warmups followed by 20
measured calls for each case/stage. Inputs are prepared before each target
call; `time.perf_counter_ns()` encloses only that production call;
`tracemalloc.is_tracing()` must remain false; automatic cyclic garbage
collection is disabled immediately before the first clock tick and its prior
enabled/disabled state is restored immediately after the second clock tick;
explicit garbage collection and output release occur outside the timed
interval. Source extraction is the production
US08 source-report extraction over verified source bytes and requires
nearest-rank p95 at most 250 ms/document (`0.250 s/document`) plus compact
report size at most 8,388,608 bytes. Projection is the production US08
projector over a deep copy of the sealed post-US07 predecessor and a validated
retained report; it requires nearest-rank p95 at most 50 ms/document
(`0.050 s/document`), leaves the predecessor unchanged, and is idempotent.
Comparison instrumentation runs in a third, untimed projection call and is
never charged to either isolated latency or allocation.

Traced allocation is a separate invocation sequence for each case/stage: one
successful warmup and five measured samples, with
`tracemalloc.start()`, `tracemalloc.reset_peak()`, target call, peak read, and
`tracemalloc.stop()` performed for every sample. It makes no timing claim;
inputs are prepared before tracing, and outputs are released and garbage
collected after the peak is recorded. The maximum traced peak must be at most
67,108,864 bytes. Any warmup or measured call that raises, returns the wrong
status/custody/counts, produces nonfinite timing, or violates its output gate
fails the complete candidate; no replacement sample is permitted. Formula,
sample-count, reset/release, and failure-scope unit witnesses are mandatory.
The exact maximum-page synthetic workload uses the injected monotonic page
timer and must complete within 0.250 s; the source-extraction and projection
document deadlines remain 2.0 s each.

That workload is the one closed fixture
`synthetic:p03-us08:maximum-page-performance-v1`, retained at
`measurement.maximum_page_workload`. Its exact keys and values are:

- `fixture_id = synthetic:p03-us08:maximum-page-performance-v1`,
  `policy_id = p03-running-regions-page-identity-v1`, and
  `physical_page_index = 1`;
- `source_character_count = 500000`, `source_word_count = 100000`,
  `label_candidate_count = 64`, `boundary_candidate_count = 512`, and
  `accepted_running_region_count = 64`;
- `extracted_contribution_count = 8`,
  `extracted_intervals_per_contribution = 8`, and
  `extracted_residual_plan_bytes = 16384`;
- `indexed_comparison_count = 4096`, `concern_count = 64`, and
  `deadline_seconds = 0.250`.

The metrics runner rejects an unknown/missing field or any different value;
the workload is passed to the production accounting/deadline hooks rather
than treated as a descriptive fixture label.

Whole-output semantic determinism removes exactly these ten timing paths and
no other field:

- `processing.duration_ms`;
- `processing.form_semantics.extraction_ms`;
- `processing.form_semantics.projection_ms`;
- `processing.form_semantics.total_ms`;
- `processing.outline_structure.extraction_ms`;
- `processing.outline_structure.projection_ms`;
- `processing.outline_structure.total_ms`;
- `processing.running_regions.extraction_ms`;
- `processing.running_regions.projection_ms`; and
- `processing.running_regions.total_ms`.

Private source-report determinism removes exactly its root `extraction_ms` and
no other field. The retained metrics artifact semantic digest removes exactly
top-level `generated_at` and `semantic_sha256`; measured samples remain inside
that digest.

The only passing artifact path is
`tracker/phase-03-layout/evidence/P03-US08-running-region-metrics.json`.
Failed candidates use monotonically increasing two-digit names
`P03-US08-running-region-metrics-attempt-NN-failed.json`, beginning at `01`.
Every artifact is exclusive-created: an existing failed or final file is never
overwritten, renamed, deleted, or relabeled. A failed worker still produces a
closed failure envelope containing completed samples and a typed failure
record; its status remains `failed_measurement_candidate`. The final status is
`final_measurement_candidate`, is emitted only when every aggregate gate is
true, and may list the immutable identities of prior failed candidates.

Both an artifact write and a prior-attempt read are capped at exactly
8,388,608 bytes with max/max+1 witnesses. This retained-envelope cap is not a
per-variant parser-output cap: output variants are retained as size/SHA-256
identities, while the public identity, descriptor, and source-report limits
remain the only payload-size gates stated by this policy.

Both artifact kinds use `schema_version = 1.0`,
`record_kind = p03_us08_running_region_metrics`, `story = P03-US08`, and this
exact closed top-level key set:

`schema_version`, `record_kind`, `story`, `status`, `generated_at`,
`retained_path`, `semantic_sha256`, `measurement`, `policy`, `settings_delta`,
`m0_reference`, `input_custody`, `predecessor_custody`, `oracle_custody`,
`contract_custody`, `synthetic_fixture_custody`, `code_sha256`,
`dependency_custody`, `source_extraction`, `running_region_projection`,
`resource_boundaries`, `deadline_boundaries`, `paired_parser`, `quality`,
`control_matrix`, `comparison_ledgers`, `output_sizes`, `rollback`,
`prior_failed_candidates`, `failures`, `aggregate`, `hosted_requests`,
`hosted_tokens`, and `hosted_cost_usd`.

The historically named top-level `code_sha256` field is a closed custody object,
not a scalar. It has exactly `manifest_sha256`, `pre`, `post`, and
`pre_post_match`. `pre` and `post` are nonempty mappings with the same normalized
relative-path key set. Each value has exactly `path`, `size_bytes`, and
`sha256`; `path` equals its mapping key, is relative, contains no `..`, size is
a nonnegative integer, and SHA-256 is lowercase hexadecimal. `pre_post_match`
equals exact mapping equality, and `manifest_sha256` is the compact canonical-
JSON SHA-256 of `post`. Passing final custody requires the pre/post mappings to
match.

The required code manifest is an explicit, duplicate-free closure capped at
128 paths. It covers every current `app/**/*.py` parser source, the planned
US08 backend/frontend modules, tracked frontend source/configuration/tests,
the US08 oracle/contract/synthetic/story/performance runner and tests, and this
policy. The closure is checked against the repository inventory so a newly
introduced parser source cannot silently fall outside code custody.

`dependency_custody` has exactly `manifests`, `python_packages`, `local_tools`,
`runtime`, and `offline_environment`:

- `manifests` has exactly `pyproject.toml`, `uv.lock`,
  `frontend/package.json`, and `frontend/package-lock.json`, each using the
  same closed `path`/`size_bytes`/`sha256` file identity;
- `python_packages` has exactly `docling`, `docling-core`, `pdfminer.six`,
  `pdfplumber`, `pydantic`, and `pypdfium2`; each record has exactly
  `distribution` equal to its key and a nonempty `version`;
- `local_tools` has exactly `tesseract`, whose record has exactly
  `name = tesseract` and a nonempty `version`;
- `runtime` has exactly nonempty `python_version` and `platform`; and
- `offline_environment` has exactly `HF_HUB_OFFLINE = "1"`,
  `TRANSFORMERS_OFFLINE = "1"`, and
  `TOKENIZERS_PARALLELISM = "false"`.

Historical failed attempts validate their closed code-post, dependency, and
oracle/contract/synthetic component identities against the epoch recorded in
that attempt. They do not become invalid merely because a later retry changed
code or dependencies. Source inputs, the M0 reference, and sealed post-US07
predecessor outputs remain live-bound across epochs; the current candidate is
always bound to the current live code/dependency/component epoch.

`output_sizes` has exactly `paired_samples`, `source_reports`,
`isolated_projection_outputs`, `maximum_page_identity_json_bytes`,
`maximum_running_descriptor_json_bytes`,
`maximum_source_report_json_bytes`, and `all_within_limits`. A final artifact
has both performance targets in the first three mappings. Each paired target
contains the exact ten-sample worker-plan order; every sample has exactly
`target_id`, `pair_index`, `state`, and `variants`. `variants` has exactly
`raw_json`, `semantic_json`, `running_region_semantic_json`,
`serialized_markdown`, `canonical_body_text`, `canonical_body_markdown`,
`canonical_full_text`, and `canonical_full_markdown`. Every variant, source
report, and isolated projection identity has exactly nonnegative
`size_bytes` plus lowercase-64 `sha256`. The three maximum JSON byte fields are
nonnegative integers and `all_within_limits` equals their computed comparison
with the 64 KiB identity, 256 KiB descriptor, and 8 MiB report caps. A failed
artifact may retain only target subsets and an ordered prefix of completed
paired samples; it may not reorder or fabricate them.

All other nested artifact schemas are likewise closed and contract-tested.
The semantic digest is compact canonical JSON after removing only the two
fields stated above. Since an artifact cannot embed its own raw hash, its raw
byte size/SHA-256 are sealed externally by the retained-artifact test and
completion record. Settings custody retains complete canonical flag-off/on
objects and hashes, requires
`changed_fields = ["layout_running_regions_enabled"]`, and proves the ten
oracle predecessor flags are true and identical in both states. Input custody
retains all 15 source paths/sizes/SHA-256/page counts and all 15 sealed post-
US07 outputs; pre/post source and code custody must match. Output/report sizes,
comparison ledgers, all counts, zero hosted requests/tokens/cost, dependency
and code identities, rollback, and quality/control results remain in the same
artifact.

Repository custody reads traverse a retained no-follow directory-descriptor
chain, require a regular file, use bounded reads with pre/post descriptor
snapshots, reopen the basename through the held parent after reading, and then
compare a freshly opened directory chain before accepting bytes. Symlinks,
FIFOs, replaced parent directories, and observed path swaps fail closed. The
exclusive writer uses the same retained-directory discipline and never
overwrites a destination. These guarantees use the cooperative build threat
model; they do not claim to defeat a malicious same-user process that retains
independent authority to mutate repository entries after the final validation
instant.

## Manual UI milestone

Before Done, a production frontend connected to the local parser must be
checked on at least catastrophe, clinical, component, ESG, timetable, and one
explicit-null case. The record must show:

- page input, buttons, keyboard navigation, preview, and canonical result stay
  on the same physical page;
- exact printed display labels appear as secondary, bidi-isolated text and
  never change physical navigation;
- a validated projected result initially selects Body, while absent and
  nonprojecting results retain the legacy initial view;
- Body excludes and Full includes each accepted running region exactly once;
- rendered/source page views and page-scoped copy match the selected stored
  Body or Full view; normalized per-page text/Markdown remain stored `body`,
  while document `text_full`/`markdown_full` and document copy/download remain
  stored `full`;
- malformed/hostile labels do not render active markup or misleading page
  navigation;
- mobile and desktop page bars agree; and
- accessibility announcements lead with physical page identity.

If no controllable browser surface is available, record manual click-through
as unclaimed and require a retry. That external limitation is not by itself a
story blocker: the technical UI gate may be satisfied for the current run by
a live local parser connected to the production React renderer plus automated
interaction/proxy, strict-contract, accessibility, responsive, Body/Full,
physical-navigation, hostile-label, copy, and download tests. The retained
record must identify the missing surface and may not claim a human browser
check that did not occur.

## Readiness exit conditions

This policy became implementation-authoritative after:

1. the exact oracle, generated fixtures, closed schema contract, and dedicated
   readiness tests exist and pass;
2. the API/canonical/frontend optional-key changes are proven compatible with
   flag-off output;
3. every limit has an exact/max+1 measurement primitive and all deadline
   witnesses are bound;
4. independent source-truth, schema/frontend/security, algorithm/fixture, and
   metrics-plan reviews report no blocker; and
5. P03-US08 alone transitioned from Proposed to Ready/In Progress under the
   tracker rules on 2026-08-01.

No Phase 04 work is authorized by this policy.
