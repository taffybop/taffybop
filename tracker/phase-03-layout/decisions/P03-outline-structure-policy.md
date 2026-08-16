# P03 Outline Structure Policy

Status: Accepted for P03-US07 implementation  
Date: 2026-08-01  
Scope: Source-grounded list and legal-clause hierarchy after P03-US06
Delivery estimate: 5 points

## Decision

P03-US07 is a default-off, local-only semantic projection on the accepted
shared IR, P03-US04 relationship order, and the currently configured P03-US06
predecessor. It records exact source markers, marker ownership, sibling
ordinals, nesting levels, parents, and bounded intervening content without
using legal meaning or language plausibility.

The normative representation is strict additive JSON. Canonical Markdown is
generated from the same validated outline graph and uses safe, escaped HTML
list structure so unordered, ordered, legal, nested, and interrupted outlines
remain explicit. Canonical plain text uses the exact raw source marker once at
each depth. The legacy public page-item array, source-visible item values,
table rows/cells, and physical reading order remain authoritative.

An item is never made an outline node merely because its prose contains a
parenthesized expression, a number, or a marker-like prefix. A source marker
must be independently bounded at the start of the matched item, and the
complete group must satisfy the sequence, indentation, ownership, and resource
rules below. Ambiguity retains the configured predecessor and a bounded,
content-free concern.

## Critical source-truth correction

The settlement source, native characters, accepted expert output, and current
predecessor all contain literal `a.`, `b.`, and `c.` markers. Earlier tracker
shorthand incorrectly stated `(a)`, `(b)`, and `(c)`. Phase 00 hash-pinned
records remain immutable; the correction and exact custody are carried by the
[P03-US07 source-truth addendum](../evidence/P03-US07-settlement-marker-addendum.md),
this policy, and the machine oracle. Parenthesized inline `(i)` through `(iv)`
expressions remain inside clause `a.` prose and are not separate nodes.

The exact settlement marker bboxes in top-left PDF points are:

| Marker | x | y | width | height |
|---|---:|---:|---:|---:|
| `a.` | 180.000 | 169.644 | 8.280 | 12.000 |
| `b.` | 180.000 | 319.644 | 9.000 | 12.000 |
| `c.` | 180.000 | 598.524 | 8.280 | 12.000 |

## Scope and exclusions

In scope:

- native-PDF bullet, decimal, and lower-alpha ordered/legal markers;
- exact marker text and bbox, marker ownership, marker style, body text,
  sibling ordinal, nesting level, parent, and source custody;
- conservative continuation across one aligned same-page table;
- typed IR elements and relationships, strict additive public sidecars,
  canonical Markdown/text, frontend rendering, copy/download, diagnostics,
  resource limits, performance evidence, and exact rollback;
- coexistence with every completed Phase 03 projection and terminal
  source-alignment re-entry.

Out of scope:

- legal interpretation, obligation/party classification, or inferred scope;
- inventing omitted markers, repairing a broken sequence, or reordering from
  prose plausibility;
- changing predecessor text, including the known settlement `LookBack`
  predecessor spelling;
- treating inline enumerations inside one paragraph as separate nodes;
- table reconstruction, row/column repair, or making a table a clause;
- form/key-value ownership or any P03-US06 contributor;
- cross-page parent/continuation edges in v1;
- upper-alpha, lower/upper Roman, custom markers, and caption/callout
  continuations in v1; those require their own positive fixtures;
- OCR-only, direct-image, image-only-PDF, or Office outline parity until the
  authorized M5 twins/adapters exist;
- calibrated probability claims; deterministic scores, if exposed in
  diagnostics, are not calibrated confidence.

## Immutable source custody

The reviewed inputs are:

| Case | Bytes | SHA-256 |
|---|---:|---|
| `component-datasheet.pdf` | 329,199 | `5fc8143f33d156d914b0f139177344be6ad2b0a8d2906413424d6dda93fe36a4` |
| `settlement-agreement.pdf` | 164,483 | `adaaf7578748ec1c215ebdfd9601a9938ec1bee918316122c56b22212a3595bc` |

The machine-readable oracle is
`tests/fixtures/phase_03/outline_structure/oracle.py`:

- file SHA-256
  `65d6a1a95e5bb76af4220d87a287b30600171b9cc443c4798a7987a544d6a3ad`;
- semantic SHA-256
  `e3bddd0ce86ccbf1089b2e667b4b42922b41daaa20c5051634d21646d4f58bc5`.

The executable closed-schema/canonical/re-entry contract is
`tests/fixtures/phase_03/outline_structure/contract.py`, file SHA-256
`980e4622105cbe230c23889545cd083f5b88f0919b82b700169196787e655746`.

The accepted Phase 00 source-rights policy authorizes local use of the source
and derived test annotations. Runtime extraction makes zero hosted requests.

## Fixed reviewed oracle

### Component page 1

The exact denominator is two unordered outline groups and 16 leaf nodes:

- 11 level-zero nodes with exact raw marker `•` at `x=124.336`, marker width
  `4.704`, and height `14.000`;
- five level-one nodes with exact raw marker `◦` at `x=140.502`, marker width
  `6.538`, and height `14.000`;
- five `outline_parent_of` edges:
  - three children of `40 pin 21 × 51 'DIP' style...`;
  - one child of `Simple yet highly flexible power supply architecture`;
  - one child of `Dual-core cortex M0+ at up to 133MHz`;
- 11 `outline_next` sibling edges;
- 16 group-to-node `contains` edges; and
- no continuation edges.

The first group has 11 nodes: seven roots, three children of its third root,
and one child of its fifth root. The second has five nodes: four roots and one
child of its first root. Sibling ordinals restart at one for every parent.
The exact graph contains 32 relationships.

The PDF source glyphs are `•`/`◦`. Docling 2.114.0 currently reports the root
marker as normalized middle dot `·`; that raw-graph normalization may
corroborate list membership but may never override the exact native source
marker.

### Settlement page 1

The exact denominator is one ordered legal outline with three level-zero
nodes:

1. raw marker `a.`, ordinal 1;
2. raw marker `b.`, ordinal 2; and
3. raw marker `c.`, ordinal 3.

It has three group-to-node `contains` edges and two `outline_next` sibling
edges. The existing percentage table at
`[144.988,398.141,402.656,172.630]` is the single bounded interstitial between
`b.` and `c.`. It is related as `outline_continuation_of` the `b.` node, remains
a table, retains every row/cell and its top-level public item, and is not an
outline node. The exact graph contains six relationships.

The three predecessor values already own their `a.`, `b.`, and `c.` prefixes.
P03-US07 must not prepend another marker. The known predecessor spelling
`LookBack Date` is preserved; text-integrity repair is not smuggled into this
layout story.

### Acceptance denominator

Across both target cases the fixed total is three groups, 19 nodes, 14 roots,
five nested nodes, five parent edges, 13 next-sibling edges, one continuation
edge, 19 contains edges, and 38 outline relationships. Every marker, ordinal,
level, parent, continuation, bbox, source reference, and predecessor value
identity must match.

## Closed machine contracts

`tests/fixtures/phase_03/outline_structure/contract.py` is the executable
schema and byte-grammar authority. All named objects are closed: missing or
unknown keys fail validation. Tuples below serialize as ordered JSON arrays;
`source_public_path` and `anchor_public_path` are arrays of nonempty strings
and nonnegative integers rooted at `pages`. All JSON is UTF-8 compact JSON with
`allow_nan=false`, sorted keys, and separators `,` and `:` when hashed or byte
measured.

| Object | Exact keys |
|---|---|
| source report | `report_version`, `policy_id`, `source_sha256`, `status`, `pages`, `counts`, `concern_codes`, `extraction_ms` |
| source page | `page_index`, `page_width`, `page_height`, `unit`, `coordinate_system_id`, `source_character_count`, `source_word_count`, `markers`, `concern_codes` |
| source marker | `raw_marker`, `marker_style`, `ordinal`, `bbox`, `source_object` |
| source object | `reader`, `page_index`, `word_index` |
| public processing summary | `policy_id`, `status`, `reason`, `group_count`, `node_count`, `relationship_count`, `concern_count`, `extraction_ms`, `projection_ms`, `total_ms` |

The source report version is `1.0`; policy is
`p03-outline-structure-v1`; status is `available`, `unavailable`, or
`refused`; the source-object reader is `pdfplumber`; word indexes are
zero-based positions in the complete `extract_words()` result. Counts have
exact keys `pages`, `source_characters`, `source_words`, `marker_candidates`,
and `concerns`. Bboxes have exact keys `x`, `y`, `width`, `height`, `unit`, use
finite positive top-left PDF points, and remain within their physical page.

The processing summary exists only when enabled. Status is `projected`,
`no_candidates`, `unavailable`, or `failed_closed`; `reason` is null for the
first two and one closed content-free concern code for the latter two.
`unavailable` permits only `outline_source_evidence_unavailable` or
`outline_source_limit`; `failed_closed` permits a non-source code. Counts are
nonnegative integers. Timings are finite nonnegative milliseconds rounded to
three decimals and `total_ms == extraction_ms + projection_ms`. Terminal
re-entry counts extraction once and sums the initial and terminal projection
times.

The complete concern enum is:
`outline_source_evidence_unavailable`, `outline_source_limit`,
`outline_candidate_limit`, `outline_geometry_ambiguous`,
`outline_marker_ambiguous`, `outline_sequence_invalid`,
`outline_interstitial_ambiguous`, `outline_relationship_limit`,
`outline_canonical_custody_invalid`, `outline_projection_failed_closed`, and
`outline_concerns_truncated`. Report page/document arrays are unique, bounded
to 64/256, and contain only those values. No source text, path, URL, raw
object, or exception message may enter a reason/concern.

IR descriptor keys are exact:

| Descriptor | Exact keys |
|---|---|
| group | `policy_id`, `role`, `record_id`, `sequence_kind`, `marker_style`, `anchor_element_id`, `anchor_public_item_id`, `member_item_ids`, `member_element_ids`, `continuation_element_ids`, `relationship_ids`, `canonical_contributor_element_ids`, `canonical_relationship_ids` |
| item | `policy_id`, `role`, `record_id`, `group_element_id`, `public_anchor_element_id`, `source_public_item_id`, `source_public_path`, `sequence_kind`, `marker_style`, `raw_marker`, `marker_ownership`, `marker_separator`, `body_text`, `level`, `ordinal`, `parent_element_id`, `marker_bbox_id`, `marker_evidence_id`, `relationship_ids` |

The new group `ElementRecord` is exact: `id` is the derived group-element ID;
`page_id` is the anchor page; `type` is `outline_group`; `reading_order`,
`value`, and `markdown` are null; bbox/evidence arrays contain only the new
group bbox/evidence IDs; `outline_group` is the descriptor above;
`presentation_role` is `subordinate`; presentation directives retain their
null defaults; properties are exactly the policy ID and public anchor element
ID. It has no text-run, form, or item descriptor. It appends once to the
anchor page's `element_ids` and once to the unique region already containing
the anchor, but never to `presentation_element_ids`.

Every group adds one `IRBoundingBox` on the group element with role `region`
and one derived `EvidenceRecord`. Every marker adds one bbox with role
`annotation` and one native evidence record on its source element. Marker
evidence value is the exact raw marker; confidence is exactly
`{scope: evidence, score: null, unavailable_reason: not_calibrated}`; metadata
is the exact policy/group/item ID plus reader/page/word source object. Group
evidence value is the exact policy/group pair and its metadata names the
validated group-union derivation and anchor. These new records append to, and
never replace, predecessor bbox/evidence IDs. Every relationship evidence ID
must resolve to an existing or story-added record on an endpoint.

IDs use
`prefix + "-" + sha256(canonical_json(parts)).hexdigest()[:20]`. A group ID
hashes, in order, policy, source SHA-256, page index, anchor element ID, the
ordered member element IDs, and ordered continuation element IDs. Test-only
`oracle_id` labels never participate. Group-element, item, bbox, evidence,
continuation, and relationship IDs derive from that group ID plus only their
frozen endpoint/source-object parts.

## Marker and node contract

Every node records:

- stable `id`, `element_id`, `group_id`, and source public item/path;
- `sequence_kind`: `unordered`, `ordered`, or `legal`;
- `marker_style`: exactly `bullet`, `decimal`, or `lower_alpha`;
- exact bounded `raw_marker` and `marker_bbox`;
- `marker_ownership`: `separate` or `value_prefix`;
- exact `marker_separator` (`""` for separate markers);
- marker-free `body_text`;
- nonnegative `level`, positive sibling `ordinal`, and optional `parent_id`;
- item bbox, source method, confidence or unavailable reason, concerns, and
  exact incident relationship IDs.

For `separate`, `body_text` equals the predecessor nested-entry value and the
marker is not present in that value. For `value_prefix`, exact recomposition
must hold:

`raw_marker + marker_separator + body_text == predecessor value`.

The component nodes use `separate`; settlement uses `value_prefix` with one
ASCII space. No projector may strip, normalize, duplicate, or synthesize the
predecessor value.

Marker parsing uses exact Unicode scalar sequences; NFKC/confusable folding is
not evidence. V1 supports bounded common bullets, decimal markers, and
lower-alpha markers with `.`/`)` or balanced parentheses. Upper-alpha, Roman,
custom, unsupported, and confusable markers retain predecessor text.

## Group recognition

An existing Docling list group is eligible only when:

- it contains 2–256 same-page source items in canonical preorder;
- every item has one exact native marker candidate at its line start;
- every marker/item bbox is finite, positive, inside the page, and uniquely
  matched by vertical overlap and source text identity;
- indentation bands are within 2 pt internally and adjacent bands differ by
  at least 6 pt;
- levels begin at zero, never skip a level, and remain in `0..7` (the frozen
  maximum depth is eight levels);
- each level-positive node has exactly one nearest preceding level-minus-one
  parent; and
- ordered sibling sequences are contiguous with no duplicate or omitted
  ordinal.

A legal/text outline is eligible only when at least three separate primary
items:

- begin with exact, independently bounded markers from one compatible family;
- form a contiguous ordinal sequence at a common indentation band;
- remain on one page in accepted P03-US04 reading order;
- have unambiguous `value_prefix` ownership; and
- are separated only by bounded eligible interstitials.

Inline `(i)`–`(iv)`, decimal values, table cells, financial row labels,
headers, footers, running regions, code/formula items, malformed source,
broken sequences, ambiguous indentation, and a single marker-like paragraph
are never promoted.

The algorithm is deterministic and bounded: source candidates are sorted by
page, top, left, raw marker bytes, and source object identity; public candidates
are sorted only by accepted reading order. No language model, network service,
document-specific phrase, or unordered set iteration participates.

## Continuation and interstitial ownership

The only eligible v1 interstitial type is an existing `table` primary element.
A table may bridge two successive siblings only when it:

- lies strictly between them in accepted reading order;
- is same-page, finite, positive, and top-left page-space grounded;
- horizontally overlaps the union of the adjacent item boxes by at least 80%
  of its smaller width;
- is not an outline node, form semantic, form contributor, header, footer,
  heading, running region, or already claimed by another outline; and
- has one deterministic preceding sibling owner.

The `outline_next` edge records the ordered interstitial public element IDs.
Each eligible table also supplies one `outline_continuation_of` edge
from the interstitial element to the preceding outline node. A table never
becomes a node and retains its original top-level public identity and data.
Unassignable, cross-page, multiply owned, over-limit, or malformed content
breaks the candidate group rather than being guessed.

## Typed IR and relationships

`ElementRecord` gains strict optional `outline_group` and `outline_item`
descriptors. An outline group is one non-primary internal element with:

- policy and stable group IDs;
- one same-page anchor element;
- ordered unique member element IDs;
- bounded continuation element IDs; and
- the exact closed relationship-ID set.

Existing subordinate list-child elements and legal-clause primary elements
receive `outline_item`; source content is not mirrored into duplicate primary
elements.

The three new relationship types are:

- `outline_parent_of`: parent node → direct nested child;
- `outline_next`: previous sibling → next sibling; and
- `outline_continuation_of`: interstitial element → owning outline node.

Group → node uses existing `contains`. All four are acyclic. Validation
requires:

- one group per node and one node per source path;
- no parent at level zero and exactly one parent at positive levels;
- child level exactly parent level plus one;
- contiguous sibling ordinals starting at one;
- the exact `outline_next` chain for every sibling set;
- same-page endpoints, unique edge tuples, exact backlinks, and resolved
  evidence;
- no cycles, multiple parents, duplicate IDs, skipped levels, cross-group
  edges, or relationship surplus; and
- incident relationship cardinalities within the frozen table.

The incident table is inclusive and applies after the complete group graph is
known:

| Record | Exact/bounded incidence |
|---|---|
| group element | `contains` incoming 0, outgoing 2–256; total 2–256 |
| root item | `contains` incoming 1; parent incoming 0/outgoing 0–255; next incoming/outgoing 0–1 each; continuation incoming 0–64; total 1–322 |
| nested item | same, except parent incoming exactly 1; total 2–323 |
| table continuation | continuation outgoing exactly 1; story-incident total exactly 1 |

Those are defensive maxima; exact per-group cardinality is also recomputed from
the node tree. Group 1 is `11/4/8/0`, group 2 is `5/1/3/0`, and settlement is
`3/0/2/1` for `contains/parent/next/continuation` respectively. A node backlink
list is exactly the group-relationship order filtered to edges incident on its
element. The continuation backlink list contains its one continuation edge.

Internal relationship metadata is exact. `contains` and
`outline_parent_of` use `canonical_inert: true`, `outline_group_id`, and
`outline_policy`. `outline_next` adds ordered `intervening_element_ids`.
`outline_continuation_of` adds `interstitial_kind: "table"`. Public
descriptors flatten those metadata keys beside exact `id`, `type`,
`source_id`, `target_id`, and ordered `evidence_ids`; unknown keys fail.

Document IR remains version `1.0`; descriptors and enum values are additive
behind the flag. Flag-off serialized IR must remain byte-identical to the
configured predecessor with every non-US07 flag unchanged.

## Public additive contract

Only the group anchor gains:

- `layout_outline_structure_projected: true`;
- `outline_policy: "p03-outline-structure-v1"`;
- one strict `outline_group`;
- ordered strict `outline_items`;
- ordered strict `outline_continuations`; and
- the story's exact relationship descriptors appended after any predecessor
  descriptors.

`outline_group` has exactly: `id`, `element_id`, `page_id`, `sequence_kind`,
`marker_style`, `anchor_public_item_id`, `anchor_element_id`,
`anchor_public_path`, `group_bbox`, `member_item_ids`, `member_element_ids`,
`continuation_ids`, `continuation_element_ids`, `relationship_ids`,
`relationship_cardinality`, `canonical_block_id`,
`canonical_primary_element_id`, `canonical_contributor_element_ids`,
`canonical_relationship_ids`, `canonical_markdown_sha256`,
`canonical_text_sha256`, `source_method`, `confidence`, and `concern_codes`.

Each authoritative `outline_items` entry has exactly: `id`, `element_id`,
`source_public_item_id`, `source_public_path`, `source_bbox_id`,
`source_evidence_ids`, `source_object`, `sequence_kind`, `marker_style`,
`raw_marker`, `marker_bbox`, `marker_ownership`, `marker_separator`,
`body_text`, `predecessor_value_sha256`, `level`, `ordinal`, `parent_id`,
`marker_bbox_id`, `marker_evidence_id`, `source_method`, `confidence`,
`concern_codes`, `relationship_ids`, and `continuation_ids`.

Each `outline_continuations` entry has exactly: `id`, `element_id`,
`source_public_item_id`, `source_public_path`, `source_type`, `bbox_id`,
`bbox`, `source_evidence_ids`, `target_node_id`, `source_method`, `confidence`,
`concern_codes`, and `relationship_ids`.

The existing component nested list entries remain byte-identical, including
their legacy `marker` (currently the complete value), `level`, `value`, bbox,
and any ID. They are not the raw-marker authority and receive no US07 fields.
`outline_items` is the sole authoritative US07 node array. Settlement member
items and the continuation likewise stay byte-identical outside the anchor
sidecar. No projector replaces legacy `marker` with `raw_marker`.

Public relationship IDs hash policy, group, relationship type, and immutable
public endpoints; mutable text and geometry are excluded. Outline descriptors
use a closed key set and public sidecar size is measured over the complete
story-owned fields plus story-owned relationship descriptors.

Non-anchor member items and continuations stay byte-identical. Their ownership
is named from the anchor sidecar rather than by mutating every contributor.
The 512 KiB measurement is compact strict JSON over all five story-owned
anchor fields plus exactly the story relationship-descriptor slice from
`relationships`; unrelated predecessor descriptors are excluded. Malformed
sidecars never become presentation authority.

## Canonical Markdown and text

Before IR commit, US07 builds the currently configured predecessor canonical
presentation with every configured prior stage active, including US06 only
when forms are enabled. Every node and
continuation must resolve to exactly one included predecessor block. The
replacement transfers the complete content closure of every consumed block,
not merely the named member: captions, table cells, subordinate content, and
predecessor relationship IDs are retained automatically. Any missing,
multiply owned, already suppressed, or form-owned block/contributor rejects
the complete candidate.

The exact reviewed closures are:

| Group | Anchor block | Primary type/scope | Content contributors | Predecessor rels | Final rels |
|---|---|---|---:|---:|---:|
| component features | `pb-affd1cf290d1f2ac4895` | `list` / `body` | 12 | 11 | 34 |
| component headline features | `pb-d1d227e3b36e3b112d8f` | `list` / `body` | 6 | 5 | 14 |
| settlement clauses | `pb-e18051f5eef5bc054ce5` | `text` / `body` | 20 | 16 | 22 |

The settlement closure is, in predecessor block/page order, `a`, `b`, the
table, all 16 table-cell contributors, and `c`. The final relationship list is
the lexically sorted deduplicated union of every consumed predecessor
relationship and every story relationship. The non-primary outline group
element is a semantic endpoint, not a content contributor. The anchor retains
its predecessor block ID/type/scope; other consumed primary blocks use the
existing `consumed_by_relationship` omission with the anchor as suppressor.

`contract.py::render_outline_group` freezes every output byte:

- no block has outer whitespace; newlines are LF;
- root unordered syntax is `<ul data-outline-group="…"
  data-outline-policy="p03-outline-structure-v1">` on one line;
- ordered/legal roots use `<ol>` with attributes in exact order
  `data-outline-group`, `data-outline-policy`, optional `type`, then literal
  `start="1"`; decimal omits `type`, lower-alpha uses `type="a"`;
- v1 refuses a sibling set that does not begin at ordinal one;
- each `<li>` orders attributes as `data-outline-item`,
  `data-source-marker`, then ordered-only `value`; leaf tags close on their
  line, while an owner with a child/continuation closes on its own indented
  line;
- nested lists occur inside the owning `<li>` and their opening/closing tags
  use two spaces per child level; their items use two additional spaces;
- attribute values use HTML escaping with quotes; text nodes replace unsafe
  controls and escape only `&`, `<`, and `>` (`quote=false`), so source quotes
  are byte-preserved; and
- the accepted predecessor table Markdown is inserted byte-for-byte at column
  zero inside clause `b`'s open `<li>`; raw source HTML is never admitted.

Plain text emits `2 × level` spaces, the exact raw marker, one ASCII space,
and safe body text. Continuation text lines are the accepted table block text
prefixed by two spaces beyond their owner. The raw marker occurs once in text
and once only as Markdown metadata; browser list semantics supply the visible
HTML marker.

The frozen results are:

| Group | Markdown bytes / SHA-256 | Text bytes / SHA-256 |
|---|---|---|
| component features | 1,775 / `9f46d5dac065435c565a9e7f4b513fd621a0ae46bab47330d9ee9c8291d4c00e` | 679 / `8c9162860ca971aa0bdbdac2077062d884ba00d2198b29355afe1d4f8c3b8a47` |
| component headline features | 819 / `27075ecdf92053c9d6bdc284877298063edc1905f982ef94e1f343138c1596e3` | 257 / `cfec0c3353985a762b757acf2120ed112d6686e086ce5b83675334e2f14093a2` |
| settlement clauses | 3,120 / `0200934cea3005ead47a31a18fbd16fc954777ba0fdb9c2dae337ed5718d0841` | 2,256 / `22d3279000f21f444759b9530f360527bfbc1aac9220b64bb52df10921689912` |

Canonical full/body Markdown and text retain existing block ordering, blank
line joins, and exactly one terminal LF. Direct Markdown, frontend copy, and
download use that canonical presentation. Repeated projection is
byte-idempotent.

## Frontend contract

The frontend adds a bounded `outline-structure.ts` whole-document validator.
It accepts only the exact policy and key sets, closed marker/relationship
enums, unique IDs, exact cardinalities/backlinks, finite in-page bboxes,
resolved source paths, marker ownership recomposition, contiguous ordinals,
valid parent levels, and the backend's count/depth/byte limits. Exactly one
public anchor must bind to exactly one canonical block by block ID, primary
element ID, complete contributor array, and complete relationship array.
Canonical hashes must be bounded lowercase 64-hex fields. The backend dry run
recomputes them against Markdown/text bytes; the synchronous frontend does not
claim WebCrypto or duplicate SHA-256.

A valid sidecar renders recursive semantic `<ol>`/`<ul>` trees with child
lists and continuations inside the owning `<li>`. React text nodes, the
existing safe table component, and the existing P03-US05 text-run overlay
resolver are used; raw sidecar HTML is never rendered. Canonical `full.block_ids`
already claims/suppresses contributors exactly once, so the outline renderer
does not perform a second suppression pass. Malformed, excessive,
inconsistent, or unknown sidecars return `null` and display the authoritative
canonical block text without client-side hierarchy inference.

Normalization preserves additive fields. JSON source view, page selection,
physical reading order, copy, Markdown download, and bundle behavior remain
compatible. Backend and TypeScript caps/enums must be exact mirrors.

## P03-US06 coexistence and stage order

The stage order is:

1. table captions;
2. visual relationships;
3. source notes;
4. relationship order;
5. text-run semantics when enabled;
6. form/key-value semantics when enabled; and
7. outline structure.

US07 does not require the forms flag, but when both flags are enabled it runs
after US06 and excludes every element carrying form semantics and every exact
US06 contributor. It also rejects any complete predecessor canonical closure
that intersects a form-owned element or contributor. Component page 2/3
key-value groups therefore retain their accepted US06 replacement; only the
reviewed page-1 list groups are outline candidates. A node/continuation may
have only one semantic owner.

Terminal source alignment is one atomic reverse-strip/forward-replay sequence:

1. snapshot the complete pre-alignment public payload;
2. validate and strip only a complete US07 sidecar and its exact relationship
   slice against its bound canonical block;
3. when enabled, strictly strip complete US06 sidecars;
4. remove predecessor `canonical_presentation`;
5. call `round_trip_document` exactly once with the same immutable outline,
   form, text-run, raw-graph, and native-text evidence objects and every
   non-US07 setting unchanged;
6. replay layout stages in forward order, forms then outlines;
7. validate final IR, require the in-transaction outline canonical dry run,
   and build canonical presentation once; and
8. retain source extraction time once while summing the initial and terminal
   outline projection times (and applying the accepted equivalent US06 rule).

The outline stripper never edits legacy nested `marker`, `level`, `value`,
bbox, ID, or unrelated relationship order. Missing, partial, unknown, or
canonically inconsistent US07 fields are not stripped. If alignment selected
new text but safe stripping/re-entry is impossible, the complete alignment
attempt fails closed to the pre-alignment payload with one content-free
alignment diagnostic; no duplicate or partial sidecar is committed.

## Resource, security, and diagnostic limits

Production limits are:

| Resource | Limit | Overflow scope |
|---|---:|---|
| native source characters/page | 500,000 | page |
| native source characters/document | 2,000,000 | document |
| source words/page | 100,000 | page |
| source words/document | 500,000 | document |
| marker candidates/page | 2,048 | page |
| marker candidates/document | 10,000 | document |
| marker UTF-8 bytes | 64 | candidate |
| item/body UTF-8 bytes | 16 KiB | candidate |
| nesting depth | 8 levels (`0..7`) | group/page |
| nodes/group | 256 | group/page |
| groups/page | 256 | page |
| groups/document | 2,048 | document |
| nodes/page | 4,096 | page |
| nodes/document | 32,768 | document |
| interstitials/group | 64 | group/page |
| relationships/page | 16,384 | page |
| relationships/document | 65,536 | document |
| comparisons/page | 65,536 | page |
| complete public group JSON | 512 KiB | group/page |
| extraction report | 8 MiB | document |
| outline concerns/page | 64 | page |
| outline concerns/document | 256 | document |
| source extraction deadline | 2.0 s | document |
| projection deadline | 250 ms/page, 2.0 s/document | page/document |

Native source characters are the count of `pdfplumber` page character records;
source words are the complete ordered `extract_words()` records; document
counts are exact page sums. String caps use UTF-8 byte length. Public-group and
report caps use the strict compact JSON rule frozen above, and the public-group
measure includes the complete closed sidecar plus its exact story relationship
slice.

A page that crosses a page-scoped source, candidate, comparison, or geometry
limit is retained only as a non-projectable page-refusal record: it has no
markers and exactly one page concern. For character/word overflow, its public
counts are bounded sentinels `min(observed, page limit)`; the extractor still
charges the exact observed counts to its private document ledger before
continuing. Projection skips that page, emits the same concern with
`source_ref=page:<physical index>`, and may safely project unaffected pages.
Document-ledger overflow, report-byte overflow, or the extraction deadline
still refuses the complete report. This bounded sentinel rule applies only to
page-refusal records; ordinary retained pages continue to report exact counts.

Every loop is charged before work. Candidate association uses bounded indexed
page/line buckets and a linear hierarchy stack; no all-pairs node scan is
permitted. Comparisons are instrumented separately from timing. Source and
public strings are UTF-8 measured without logging their content.

Readiness materializes executable isolated measurement primitives at exact and
maximum+1 for all 22 integer counters and distinct injected-clock witnesses for
the three deadlines. These freeze units, inclusivity, and scope without
claiming they are already production projectors. Before Done, each primitive
must be rebound to a schema-valid source report, IR/public sidecar, or the real
production ledger/validator as applicable; shadowed topology/byte ceilings
retain direct validator exact/max+1 tests. Deadline tests use injected
monotonic clocks. Failure
diagnostics expose only policy code, counts, page/group IDs, caps, and exception
class—not marker/body text, raw PDF objects, paths, or URLs.

## Feature flag and rollback

The public setting is `parser.layout.outline_structure.enabled`; the runtime
environment variable is `PARSER_LAYOUT_OUTLINE_STRUCTURE_ENABLED`. It defaults
to `false` and requires:

- `PARSER_SHARED_IR_ENABLED=true`;
- `PARSER_SHARED_IR_NORMALIZATION_ENABLED=true`;
- `PARSER_CANONICAL_SERIALIZATION_ENABLED=true`; and
- `PARSER_LAYOUT_RELATIONSHIP_ORDER_ENABLED=true`.

It does not require text-run or forms flags. With the flag off there is zero
US07 source extraction, import, projection, processing summary, public/IR
field, relationship, concern, canonical, frontend, or warning work.

Projection starts from a deep copy of the untouched post-US06 IR and snapshots
each affected page before mutation. Each page materialization includes its
complete canonical-closure check and byte renderer. A page-local source,
candidate, geometry, group, relationship, serialization, canonical-custody, or
page-limit failure restores that page and emits one content-free page concern.
After all pages, strict `DocumentIR.model_validate` and a lazy
`build_canonical_presentation` dry run occur inside the same US07 transaction.
Source-report refusal, source hash/custody mismatch, document counters, report
bytes, document deadline, or final IR/canonical failure restores the complete
US07 predecessor and emits one content-free document concern. No partial
group, sidecar, or canonical replacement survives.

Rollback is one setting change:

`PARSER_LAYOUT_OUTLINE_STRUCTURE_ENABLED=false`.

This restores the exact configured predecessor with all non-US07 flags
unchanged: the accepted US06 output when forms are enabled, and the same
configured pipeline without US07 when forms are disabled.

## Readiness fixtures and controls

The deterministic registry is
`tests/fixtures/phase_03/outline_structure/synthetic.py`:

- 11 fixtures, including nine byte-stable one-page PDFs;
- 37 named capabilities;
- file SHA-256
  `42200360e918050a4b298bce5736481fdd7495460fca93eed243c103004ac83d`;
- registry semantic SHA-256
  `56d1ae95917de879b992030c7d8dddc4e03fada4e1b715974bdd4bde6a6e27c3`.

It covers nested unordered, numeric ordered, parenthesized-alpha source
recognition, legal table interruption, broken sequence, parenthesized prose, financial
rows, ambiguous indentation, HTML/Markdown injection, Unicode confusables,
duplicate/cyclic/multiple-parent/skipped-level/cross-page/malformed graphs,
every count/byte/depth/comparison/report boundary, deadlines, page/document
rollback, flag-off zero work, idempotence, terminal re-entry, and form
contributor exclusion. The taxonomy does not claim production implementation;
the executable readiness contract additionally validates real source reports,
IR bbox/evidence records, group-element membership, full predecessor canonical
closures, byte-exact rendering, closed public sidecars, strict stripping,
terminal timing/order, rollback state transitions, form-overlap refusal, all
22 resource measurement primitives, and three distinct deadlines. Pdfplumber
and pypdfium2 must accept/render every PDF fixture before the story enters In
Progress.

The real-corpus control slice is:

- target: component page 1 and settlement page 1;
- related projection positives: nested-unordered, ordered-numeric, and
  legal-table-interruption synthetics;
- source-recognition positive / projection refusal:
  `parenthesized-alpha-v1` retains all three exact native markers, but the
  current configured predecessor exposes them in one combined primary item.
  Projecting three nodes would violate the normative requirement for at least
  three separate primary items, unique source paths, and exact value-prefix
  recomposition, so production must retain that predecessor unchanged;
- non-target: `finance-10k` reviewed financial table plus the synthetic
  financial rows and parenthesized prose;
- ambiguous/negative: broken sequence, ambiguous indentation, confusable,
  marker injection with incompatible mixed predecessor ownership, malformed
  graph, and resource boundaries. Injection content must remain safely escaped
  in direct outline-rendering tests. When projection is refused, predecessor
  bytes remain authoritative and the frontend must retain its safe React/text
  rendering path; US07 does not reinterpret those bytes as raw HTML.

This control clarification was accepted during implementation on 2026-08-01
after executing the frozen PDF through the configured predecessor. It does not
change the fixture bytes or hashes and does not relax native marker extraction;
it resolves an inconsistency between the earlier shorthand list of “related
positives” and the stricter normative ownership rules above. No projector may
split one legacy primary item or invent duplicate public paths to satisfy a
fixture label.

The Finance real-corpus control must be executed with the outline flag on
before completion; it is not claimed by readiness alone.

## Verification and retained evidence

Dedicated paths are:

- `tests/stories/phase_03/test_p03_us07_outline_structure.py`;
- `tests/contract/test_p03_us07_outline_structure_contract.py`;
- `tests/performance/test_p03_us07_outline_performance.py`;
- `tests/benchmarks/outline_structure_metrics.py`;
- frontend outline validator/rendering/normalization/serialization tests; and
- retained-artifact custody tests.

Required assertions include exact real oracle output, graph/cardinality and
bbox/provenance validation, marker ownership/recomposition, safe canonical
Markdown/text, semantic nested DOM, zero false lists, all synthetics and
exact/max+1 limits, page/document rollback, flag-off zero work and byte parity,
idempotence, US06 coexistence, P03-US04 41/41 order, terminal re-entry, broad
Phase 01–03 regression, output sizes, latency/RSS/allocation, and zero hosted
use.

Isolated measurement uses two warmups and 20 measured
`time.perf_counter_ns()` samples. Inclusive p95 is
`sorted(samples)[ceil(0.95 × n) - 1]`. Tracemalloc runs separately with one
warmup, five reset samples, and maximum peak reporting. Gates are:

- component extraction p95 ≤250 ms;
- settlement extraction p95 ≤150 ms;
- projection p95 ≤50 ms/case;
- isolated peak allocation ≤64 MiB;
- report ≤8 MiB; and
- exact/max+1 projector ≤250 ms after construction.

Five fresh-process pairs keep P03-US01–US06 and all other settings identical;
only `PARSER_LAYOUT_OUTLINE_STRUCTURE_ENABLED` changes, and off/on order
alternates. For pair `i`, `d_i = max(0, enabled_i - disabled_i)`. The gate is
inclusive p95 of `d_i`; baseline is inclusive p95 of disabled samples.

Component requires overhead
`≤ min(0.05 × current predecessor p95, 0.528 s)` and settlement
`≤ min(0.05 × current predecessor p95, 0.324 s)`. Enabled maximum RSS may
not exceed disabled maximum by more than 64 MiB. `ru_maxrss` is bytes on Darwin
and KiB×1,024 on Linux. At least three enabled semantic outputs must be exact
after removing only volatile duration/US07 timing fields. Hosted
requests/tokens/cost remain `0/0/$0`.

Deterministic semantic comparison removes exactly these volatile timing paths
and no content or structural field: `processing.duration_ms`, the
`extraction_ms`, `projection_ms`, and `total_ms` members of
`processing.form_semantics`, and the same three members of
`processing.outline_structure`. Forms remain enabled identically in both
members of every pair so the configured US06 predecessor and coexistence cost
are measured rather than bypassed.

The final retained artifact will be
`tracker/phase-03-layout/evidence/P03-US07-outline-metrics.json`. It must bind
final code/config/frontend/test/policy paths, exact source/oracle/synthetic and
configured predecessor identities (including US06 when enabled),
dependencies/tools, controls, limits,
rollback, raw and semantic hashes, output sizes, deterministic results, and
zero hosted use.
