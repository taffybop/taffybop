# P03 Form, Control, and Key-Value Semantics Policy

Status: Accepted  
Date: 2026-07-31  
Scope: Source-visible static form groups, empty value regions, controls, and
aligned key-value relationships after P03-US05

## Decision

P03-US06 is a default-off, local-only semantic overlay on the accepted shared
IR and P03-US04 relationship order. It records source-grounded form groups,
fields, labels, value regions, controls, and key-value pairs without changing
the legacy public item's identity or discarding a legacy table candidate.
JSON is normative. Canonical Markdown/text selects only the three
oracle-allowlisted component key-value groups whose complete reviewed regions
replace flat source contributions atomically. ACORD form overlays are
canonical-inert in US06.

The overlay never fills a field, guesses a signature, turns nearby `N / A`
text into a selected state, treats an empty `/AcroForm` catalog entry as an
interactive form, or converts the mixed ACORD coverage grid into a form-only
table. Empty means a positively bounded source-visible region whose interior
has no trusted entered content. Missing evidence alone never means empty.

P03-US06 does not recover the coverage table's row/column topology. The
coverage table remains available in legacy public JSON for Phase 04. Its
source-grounded controls are a linked form overlay with a targeted
form/table-ownership concern. This story does not suppress or claim to repair
that table.

## Scope and exclusions

In scope:

- static form groups and bounded empty value regions;
- source-visible checkbox/radio-like or unresolved choice controls;
- explicit states `checked`, `unchecked`, `ambiguous`, and
  `not_applicable`;
- aligned, borderless key-value groups whose source items and order are
  unique;
- typed IR ownership and semantic relationships;
- additive public JSON, canonical fallback, frontend rendering, copy,
  download, diagnostics, limits, and exact rollback.

Out of scope:

- filling, signing, or mutating a source form;
- signature, handwriting, or signer identity;
- insurance-domain rules or inferred policy meaning;
- Phase 04 coverage-table recovery or suppression;
- OCR-only control recognition without a separately reviewed source fixture;
- direct-image and image-only-PDF parity until the conditional M5 twins exist;
- calibrating rule-derived confidence as probability.

## Immutable source custody

The reviewed source inputs are:

| Case | Bytes | SHA-256 |
|---|---:|---|
| `insurance-acord.pdf` | 17,086 | `85571deac2362e67829587656d915df1b4d1683f9df62f3b77971743a963cfd4` |
| `component-datasheet.pdf` | 329,199 | `5fc8143f33d156d914b0f139177344be6ad2b0a8d2906413424d6dda93fe36a4` |

ACORD is one 612×792 pt native page with 2,843 source character objects, 125 line
objects, 20 rectangle objects, one image, five pdfplumber table candidates,
and zero page annotations/widgets. Its catalog contains `/AcroForm` with an
empty `Fields` array. Empty canonical fields plus zero widget annotations mean
`static`, not `interactive`. The corpus manifest's native extracted-text count
is 3,000 characters; it is a different measure from source character objects.

Component is three 595.28×841.89 pt pages. Physical page 2 / printed page 7
has 263 lines, two rectangles, 374 curves, and four `/Link` annotations;
physical page 3 / printed page 11 has two lines and no rectangles, curves, or
annotations. `/Link` annotations are never form widgets.

The source and derived annotations are authorized by the accepted Phase 00
source-rights policy. Runtime processing remains local and makes zero hosted
requests.

## Fixed reviewed oracle

The machine-readable oracle is
`tests/fixtures/phase_03/form_semantics/oracle.py`. Coordinates below are
top-left PDF points.

### ACORD groups, labels, and empty fields

The reviewed denominator is six source-grounded logical form groups:

1. `date`, `[507.6,24,86.4,24]`, containing only `date`;
2. `parties-and-insurers`, `[18,120,576,120]`, containing producer, insured,
   contact, and the 12 insurer fields;
3. unresolved `coverages`, `[18,240,576,324]`, containing certificate and
   revision fields plus all 24 controls and overlapping the preserved table;
4. `description-of-operations`, `[18,564,576,84]`;
5. `certificate-holder`, `[18,660,288,84]`; and
6. `cancellation`, `[306,660,288,84]`.

`DATE` is not grouped with certificate/revision: the page has no shared
source-visible container between `y=24` and `y=240`. Coverage is unresolved
only because its semantic overlay overlaps a preserved table; its accepted
fields and individual control states remain available in JSON.

ACORD has 22 field/group label nodes, 20 additional control-label nodes, 24
logical empty fields, and 24 controls. The exact label denominator is therefore
42. It has 30 label-to-field, three label-to-group, and 20 label-to-control
edges: 53 `label_of` relationships in total.

The 24 fields are:

- `DATE (MM/DD/YYYY)`: one field in `[507.6,24,86.4,24]`;
- `PRODUCER` and `INSURED`: two fields in `[18,120,288,60]` and
  `[18,180,288,60]`;
- `CONTACT NAME`, `PHONE`, `FAX`, and `E-MAIL ADDRESS`: four fields in the
  reviewed top-right cells;
- insurer A–F name and NAIC regions: 12 fields, with name cells
  `[306,y,234,12]` and NAIC cells `[540,y,54,12]` for
  `y ∈ {168,180,192,204,216,228}`;
- `CERTIFICATE NUMBER` and `REVISION NUMBER`: two inline empty regions
  `[255.924,240,168.876,12]` and `[506.935,240,87.065,12]`;
- description, certificate holder, and authorized representative: three
  fields in `[18,564,576,84]`, `[18,660,288,84]`, and
  `[306,708,288,36]`.

There are 19 field-bearing label/header nodes and three group-only headings:
`INSURER(S) AFFORDING COVERAGE`, `COVERAGES`, and `CANCELLATION`. Eighteen
ordinary fields have one label edge. Each of the six NAIC fields has two
label edges—its insurer-row label and the `NAIC #` header—giving 30 total
label-to-field relationships. The three group-only nodes point to their groups.
Twenty distinct control-label nodes point to the 20 labeled controls; four
ambiguous controls intentionally have no label edge.

A field bbox is its enclosing source cell or reviewed implicit inline region.
Its value-region element uses the same canonical bbox ID and lists the field's
owned label IDs in `excluded_label_ids`. Empty-state validation subtracts
exactly those label character indexes before checking for entered source
characters. It does not invent a trimmed blank rectangle inside a source cell.
Each ACORD field and value-region element must share one bbox record without
sharing semantic identity.

The two certificate-number regions are aligned implicit blanks rather than
four-sided ruled cells. They remain accepted only with
`form_value_boundary_implicit`. Their region coordinates come from the exact
label end, next source label, page boundary, and enclosing band; the policy
does not pretend a source rule exists.

All 24 values are JSON `null` with `value_state: "empty"`. The authorized
representative region is explicitly empty. `[signature]`, a signer name, or
any other placeholder is forbidden.

Coordinates and dimensions are normalized to top-left page points and rounded
to three decimal places after transforms. The two inline blanks above are the
three-decimal forms of source-derived
`[255.924,240,168.876,12]` and
`[506.9352,240,87.0648,12]`.

Coverage policy/date/limit cells are excluded from this field denominator and
remain Phase 04 table evidence.

### ACORD controls

The source has exactly 24 visible empty 14.4×12 pt outlines:

- 12 native rectangle objects;
- 12 closed shapes assembled from native line objects after exact geometry
  deduplication and rejection of the overlapping phantom sub-cell.

Nineteen uniquely labeled controls are `unchecked`. Five are `ambiguous`: four
unlabeled outlines and the single Y/N response cell, whose one empty box
cannot identify a selected yes/no choice. The checked denominator is zero.

The fixed control origins are:

```text
CGL:
(36,312) Commercial General Liability
(50.4,324) Claims-Made
(115.2,324) Occur
(36,336) unlabeled
(36,348) unlabeled
(36,372) Policy
(79.2,372) Project
(122.4,372) Loc

Automobile:
(36,396) Any Auto
(36,408) All Owned Autos
(104.4,408) Scheduled Autos
(36,420) Hired Autos
(104.4,420) Non-Owned Autos
(36,432) unlabeled
(104.4,432) unlabeled

Umbrella/Excess:
(36,444) Umbrella Liab
(115.2,444) Occur
(36,456) Excess Liab
(115.2,456) Claims-Made
(36,468) Ded
(72,468) Retention

Workers:
(424.8,480) WC Statutory Limits
(482.4,480) Other
(158.4,498) Y/N response cell
```

All 24 interiors contain zero source characters and no visible mark.
`unchecked` requires a uniquely owned control label plus that empty interior.
An unlabeled outline is retained as ambiguous instead of disappearing.

Control-label text normally preserves the exact visible slice. The only
authorized line-flattening repairs join `PRO-` + `JECT` as `PROJECT`,
`WC STATU-` + `TORY LIMITS` as `WC STATUTORY LIMITS`, and `OTH-` + `ER` as
`OTHER`. These repairs require consecutive same-column source words on the
reviewed lines, remove only a discretionary line-end hyphen, and retain every
raw word and half-open source-character range. Abbreviations such as `LIAB`
remain abbreviated.

Expert Markdown contains 21 `[ ]` tokens because it omits the four unlabeled
outlines and incorrectly promotes printed `N / A` in the `ADDL INSR` column:
`21 - 1 + 4 = 24`. Printed `N / A` is ordinary table text and never a control
or active not-applicable state.

### Datasheet key-value pairs

The reviewed denominator is 16/16 ordered pairs in three groups.

Physical page 2 / printed page 7:

```text
GPIO29 -> IP Used in ADC mode (ADC3) to measure VSYS/3
GPIO25 -> OP Connected to user LED
GPIO24 -> IP VBUS sense - high if VBUS is present, else low
GPIO23 -> OP Controls the on-board SMPS Power Save pin (Section 4.4)

PIN40 -> VBUS
PIN39 -> VSYS
PIN37 -> 3V3_EN
PIN36 -> 3V3
PIN35 -> ADC_VREF
PIN33 -> AGND
PIN30 -> RUN
```

The GPIO union is `[125,471.013,264.384,63.176]`, with key/value anchors at
`x=125/172.624`. The pin union is `[125,563.365,80.536,118.352]`, with
anchors at `x=125/167.304`.

Physical page 3 / printed page 11:

```text
Operating Temp Max -> 85°C (including self-heating)
Operating Temp Min -> -20°C
VBUS -> 5V ± 10%.
VSYS Min -> 1.8V
VSYS Max -> 5.5V
```

The union is `[125,142.96,195.912,81.568]`, with anchors at
`x=125/220.408`. Every group has an 18.392 pt row cadence. Output preserves
the exact predecessor strings, including `_`, `/`, `±`, `°C`, parentheses,
the minus sign, and the final period in `10%.`.

## Public additive contract

`ParseResult.schema_version` remains `1.0`. Existing public item `id`, `type`,
`value`, `md`, `rows`, `cells`, `fields`, `links`, bbox, source, confidence,
and other legacy fields remain unchanged. P03-US06 does not redefine Docling's
existing `fields`, `cells`, or `links`.

Only the oracle-selected legacy group anchor receives:

- `layout_forms_projected: true`;
- `form_policy: "p03-form-semantics-v1"`;
- one strict `form_group`;
- bounded `form_fields`;
- bounded `form_labels`;
- bounded `form_value_regions`;
- bounded `form_controls`;
- bounded `form_key_value_pairs`;
- deterministic form relationship descriptors merged into `relationships`.

When present, top-level semantic arrays have exact cardinalities:
`form_fields` 1–128, `form_labels` 1–256, `form_value_regions` 1–128,
`form_controls` 1–256, and `form_key_value_pairs` 1–32. An empty class is
omitted. The one group plus all present arrays form one complete, closed
sidecar; records from another group are never mixed onto the anchor.

All sidecar models are strict (`extra="forbid"`). A bbox has exactly numeric
`x`, `y`, `width`, `height`, and `unit: "pt"`; values must be finite and
dimensions positive. A source-object reference is one of:

- `{kind: "character_range", start, end}` with strict nonnegative integers and
  half-open `start < end`;
- `{kind: "line" | "rect", index}` with a strict nonnegative source index;
- `{kind: "field" | "widget" | "annotation", object_ref_digest}` with a
  lowercase SHA-256 digest.

Every record has required `id`, `element_id`, `page_index`, `bbox`,
`evidence_methods`, `source_objects`, `confidence_dimensions`,
`concern_codes`, and `relationship_ids`. Every ID, key, concern code, and
source-item ID is a nonempty string of at most 256 UTF-8 bytes. Lists are
unique and already in canonical order. Common-list cardinalities are
`evidence_methods` 1–5, `source_objects` 1–64, and `concern_codes` 0–13. A
relationship descriptor's `evidence_ids` has 0–64 IDs. Role-specific
`relationship_ids` cardinalities are group 1–2,816, field 4–323, label 2–257,
value region exactly 2, control 2–3, and key-value pair exactly 5. Every
record's list is exactly the canonically sorted set of descriptors incident
to its semantic `element_id`. A group's `anchor_relationship_ids` has 0–1
descriptor, used only when its legacy anchor is the target of that group's
single `form_overlay_of` edge. Every descriptor ID therefore has exactly two
endpoint backlinks; `form_overlay_of` uses the source group's
`relationship_ids` and target group's `anchor_relationship_ids`. Record
specific required fields are:

| Record | Exact additional keys |
|---|---|
| `form_group` | `group_key`, `status`, `interactivity`, `canonical_mode`, `anchor_public_item_id`, `anchor_element_id`, `anchor_relationship_ids`, `contributor_public_item_ids`, `contributor_element_ids`, `field_ids`, `label_ids`, `value_region_ids`, `control_ids`, `key_value_pair_ids` |
| `form_fields[]` | `group_id`, `field_key`, `label_ids`, `value_region_id`, `control_ids`, `value`, `value_state` |
| `form_labels[]` | `group_id`, `label_role`, `text`, `raw_text`, `label_of_ids`, `key_of_ids` |
| `form_value_regions[]` | `group_id`, `owner_id`, `excluded_label_ids`, `value`, `value_state` |
| `form_controls[]` | `group_id`, `owner_field_id`, `label_id`, `control_type`, `state`, `origin` |
| `form_key_value_pairs[]` | `group_id`, `pair_key`, `key_label_id`, `value_region_id`, `key`, `value`, `value_state`, `key_source_item_id`, `value_source_item_id` |

`page_index` is a strict integer at least one. `evidence_methods` is ordered
from the closed enum `native`, `vector`, `embedded`, `recovered`, `derived`.
Group arrays have these exact maxima: `field_ids` 128, `label_ids` 256,
`value_region_ids` 128, `control_ids` 256, and `key_value_pair_ids` 32; each
may be empty, but at least one of `field_ids`, `control_ids`, or
`key_value_pair_ids` is nonempty. A group never mixes key-value pairs with
fields or controls. Its value-region IDs equal exactly the value regions owned
by its fields or pairs. A field has 1–64 `label_ids` and 0–256 `control_ids`.
A value region has 0–64 `excluded_label_ids`; field-owned regions require at
least one and present pair regions require exactly zero.

`label_role` is exactly one of `field`, `group`, `control`, or `key`.
Field labels have 1–256 `label_of_ids`; group and control labels have exactly
one. All three have an empty `key_of_ids`. Key labels have an empty
`label_of_ids` and exactly one `key_of_ids` entry. `text`, `raw_text`, `key`,
and present `value` are nonempty, non-whitespace strings of at most 16 KiB
UTF-8.

`canonical_mode` is `inert` or `replace`.
`contributor_public_item_ids` and `contributor_element_ids` each contain
1–64 unique IDs, have equal lengths, are pairwise mappings in source order,
and contain `anchor_public_item_id` and `anchor_element_id` exactly once at
the same array index. Every contributor resolves to the group's physical
page. The group
`element_id` is a dedicated, non-presented semantic element and must differ
from `anchor_element_id` and every contributor element ID in both modes. The
sidecar is attached only to the legacy public item named by
`anchor_public_item_id`; that item's canonical primary is
`anchor_element_id`. `replace` claims the complete ordered contributor set
atomically. `inert` records the same exact custody set but claims none of it
for canonical suppression.

State/type/status/interactivity values are the closed enums defined below. A
field/value-region `value` is `str | null`; a pair's value is nonempty `str`
in US06. Null is legal only for `empty`, `ambiguous`, or `not_applicable`.
`present` requires an exact nonempty string; every other state requires
`null`.

`owner_field_id` and `label_id` are nullable only for a source-grounded
group-owned or unlabeled control. `raw_text` equals `text` except for one of
the three reviewed discretionary line-hyphen repairs. Every other scalar and
array is required. A US06 relationship descriptor has exactly `id`, `type`,
`source_id`, `target_id`, `evidence_ids`, and `canonical_inert`; endpoint IDs
are bounded as above and use the same names as internal `RelationshipRecord`.
Its `id`, type, endpoints, and evidence IDs equal the underlying
`RelationshipRecord` exactly. Its type is one of the five new types plus
`contains`. Semantic `_of`
descriptors require
`canonical_inert: true`; `contains` is also canonical-inert for these semantic
overlays. Predecessor descriptors of other relationship types remain
unchanged in the merged public array.

Absent top-level record classes are omitted rather than emitted as misleading
empty arrays. Arrays present on an anchor must be nonempty. The group record's
ID lists are always present, including valid empty lists, so its complete
cardinality is explicit. The strict public models, limits, and canonical sort
keys live in `app/services/form_semantics.py`; no generic unbounded mapping is
accepted.

Group anchors sort by `(page, top, left, source index, id)`. Within an anchor,
fields and controls sort by `(top, left, source index, id)`, labels by
`(top, left, first character index, id)`, value regions by their owner's
order, and pairs by `(top, left, key source index, id)`. Relationship
descriptors sort by source record order, relationship-type enum order, target
record order, then ID.

Public `confidence` remains `float | null`. The additive
`confidence_dimensions` object has exactly `geometry`, `role`,
`transcription`, and `state`. Each dimension is exactly one of
`{"score": <finite number in [0,1]>}` or
`{"unavailable_reason": <allowlisted literal>}`. The unavailable-reason
allowlist is `not_calibrated`, `not_applicable`,
`source_state_unavailable`, and `transcription_not_applicable`. Rule-derived
role/state values use `not_calibrated`; they are never presented as calibrated
probabilities.

Field/value states are `empty`, `present`, `ambiguous`, or `not_applicable`.
Control types are `checkbox` or `radio`; unresolved square-choice geometry
uses `checkbox` plus `state: "ambiguous"` and a concern instead of inventing a
new interactive behavior. Control origin is `static_vector` or
`interactive_widget`. Group status is `resolved` or `unresolved`.
Interactivity is `none`, `static`, `interactive`, `mixed`, or `unknown` and is
stored on `form_group`.

A `present` value must exactly match trusted source-visible text inside its
value-region bbox. An `empty` public value is `null`; empty string is not a
value. `not_applicable` requires an explicit source-selected state. Adjacent
printed text is insufficient.

Stable IDs include source SHA-256, physical page, semantic role, page-space
bbox, source-object identity, and owner identity. Text alone is never an
identity input.

## Typed IR graph

Every group, field, label, value region, control, and key-value pair is an
actual new `ElementRecord` with a strict typed form-semantic descriptor.
Every semantic element ID is disjoint from every predecessor/contributor
element ID. Existing source elements are referenced as label/value evidence
but are never repurposed as semantic nodes; geometry-only empty regions and
vector controls likewise receive new subordinate elements with their own bbox
and evidence.

`ElementRecord` adds optional
`form_semantics: FormSemanticDescriptor | None`, excluded from serialized IR
when absent. `FormSemanticDescriptor` is a strict discriminated union on
`role`: `group`, `field`, `label`, `value_region`, `control`, or
`key_value_pair`. Every variant has exactly
`policy_id: "p03-form-semantics-v1"`, `role`, `record_id`,
`group_element_id`, and `public_anchor_element_id`, followed by only the
variant fields in this table:

| Role | Exact additional descriptor fields |
|---|---|
| `group` | `group_key`, `status`, `interactivity`, `canonical_mode`, `anchor_public_item_id`, `anchor_relationship_ids`, `contributor_public_item_ids`, `contributor_element_ids` |
| `field` | `field_key`, `label_element_ids`, `value_region_element_id`, `control_element_ids`, `value`, `value_state` |
| `label` | `label_role`, `text`, `raw_text`, `label_of_element_ids`, `key_of_element_ids` |
| `value_region` | `owner_element_id`, `excluded_label_element_ids`, `value`, `value_state` |
| `control` | `owner_field_element_id`, `label_element_id`, `control_type`, `state`, `origin` |
| `key_value_pair` | `pair_key`, `key_label_element_id`, `value_region_element_id`, `key`, `value`, `value_state`, `key_source_item_id`, `value_source_item_id`, `key_source_element_id`, `value_source_element_id` |

All descriptor IDs, keys, source-item IDs, and strings use the same byte
bounds and enums as their public counterparts. Descriptor arrays have the same
cardinalities as the corresponding public arrays. Nullable
`owner_field_element_id` and `label_element_id` follow the public control
rule. Group descriptors satisfy
`group_element_id == ElementRecord.id`; every other variant's
`group_element_id` resolves to its one structural group owner. For all
variants, `public_anchor_element_id` equals the enclosing group's
`anchor_element_id`. Pair source element IDs resolve one-to-one with the
source-item IDs. A label's element value equals `text`; a field and its value
region have identical value/state; a pair and its value region have identical
present value/state. `ElementRecord.value` equals the descriptor `value` for
field, value-region, and pair roles. A pair's source element IDs are
predecessor evidence nodes and differ from its semantic key-label and
value-region element IDs. Descriptor ownership/target arrays equal the
validated incident `RelationshipRecord` endpoints exactly. Extra fields are
forbidden.

`RelationshipType` adds:

- `label_of`: label → field, control, or group;
- `value_of`: value region → field or key-value pair;
- `control_of`: control → grounded group or field;
- `key_of`: key label → key-value pair; and
- `form_overlay_of`: form group → preserved mixed table.

Every new US06 `RelationshipRecord` stores exactly
`metadata={"canonical_inert": true}`; the public descriptor's
`canonical_inert` is the exact projection of that typed invariant. No generic
metadata key can override it. A `form_overlay_of` target is exactly its source
group descriptor's `public_anchor_element_id` / public
`form_group.anchor_element_id`. Its relationship ID occurs once in the
semantic group's `relationship_ids` and once in that same public group's
`anchor_relationship_ids`. `anchor_relationship_ids` indexes only US06 edges
that use the non-semantic legacy anchor endpoint; it does not collect unrelated
predecessor edges incident to that anchor.

Every semantic node has exactly one structural parent. For ACORD, ownership
uses `contains` from group → field/label/control and field → value region.
Labels are group-owned, so one insurer-row label and the `NAIC #` header can
fan out through `label_of` without acquiring multiple structural parents. For
component, group → pair and pair → key label/value region. Semantic `_of`
edges do not independently duplicate canonical content. The new
ownership/semantic edges are same-page, acyclic, and canonical-audited.
`contains` is semantic ownership, not a claim of strict rectangle containment:
a source group heading may occupy the immediately preceding header band, at
most 12 pt above its owned group bbox.

The ACORD oracle therefore has 114 `contains`, 53 `label_of`, 24 `value_of`,
24 `control_of`, and one `form_overlay_of` edge: 216 total. Component has 48
`contains`, 16 `key_of`, and 16 `value_of` edges: 80 total.

The IR validator requires:

- globally unique graph IDs;
- same-source, same-page owners, bboxes, and evidence;
- exact role-compatible relationship endpoints;
- one owning group for every promoted record;
- exactly one structural `contains` parent for every non-group semantic node;
- exactly one value region per ordinary field or key-value pair;
- exact `null`/text and state invariants;
- checked/unchecked evidence compatible with control origin;
- uniqueness by `(role, owner, source identity, bbox)`; different roles may
  legitimately share one bbox record;
- deterministic group/field/control/pair order; and
- complete public-to-internal endpoint resolution.

Any new optional typed IR field is absent from serialized predecessor IR when
unused. All sealed Phase 01 flag-off serialized IR hashes and sizes must remain
exact.

## Source extraction and interactivity

The pinned source reader is local `pdfplumber 0.11.10` and
`pdfminer.six 20260107`. No new dependency is introduced.

The extractor resolves the bounded catalog `/AcroForm/Fields` tree and page
annotations, including inherited field type/state and widget kids. It ignores
`/Link` annotations. Outcomes are:

- `none`: no validated interactive field/widget and no validated static-form
  evidence;
- `static`: validated static-form evidence and no interactive field/widget;
- `interactive`: at least one validated field/widget;
- `mixed`: both validated widgets and static form evidence;
- `unknown`: malformed, cyclic, over-limit, or unresolved field/widget
  evidence.

Page state uses only evidence owned by that page. Document state is `unknown`
if any page/tree is unknown, otherwise `mixed` when static and interactive
evidence coexist, `interactive`, `static`, or `none` in that precedence. An
empty `/AcroForm` dictionary does not make an ordinary page static or
interactive; ACORD is `static` only because its reviewed vector form evidence
is validated. `unknown` fails the form stage closed for the affected page and
does not promote static controls.

Interactive resolution follows these exact rules:

- inherited `/FT`, `/Ff`, `/V`, and `/T` resolve from child to parent with a
  visited-reference cycle check;
- only `/FT /Btn` is a control; `Ff & (1 << 16)` pushbuttons are excluded,
  `Ff & (1 << 15)` is radio, and remaining buttons are checkbox;
- widget `/AS` and the resolved field `/V` use `/Off` as unchecked;
- non-`/Off` state is checked only when it is a key in resolved `/AP/N`, or
  when the appearance dictionary is absent but widget and field select the
  same bounded PDF name;
- parent/widget disagreement, missing inherited type, unresolved appearance,
  duplicate export names, or an orphan widget is retained as `ambiguous` with
  `unknown` interactivity for that page;
- a selected appearance/export name case-insensitively equal to `N/A`, `NA`,
  or `not_applicable` is `not_applicable`; adjacent printed text never is.

All geometry is finite top-left PDF points. Rotation, transforms, crop/media
boxes, and source object indexes are retained. Unsupported transforms fail the
page closed.

Geometry is transformed first, rounded to 0.001 pt, and compared inclusively.
An input segment is axis-aligned when its orthogonal delta is at most 0.15 pt;
endpoints within 0.15 pt snap to the lowest coordinate, then lowest source
index. Candidate static controls require width and height each in `[6,24]` pt,
aspect ratio in `[0.65,1.55]`, closure gap at most 0.15 pt, and at least 95%
coverage of every edge. A native rectangle uses the same thresholds.

Line-built boxes use horizontal/vertical coordinate buckets and only adjacent
eligible x/y boundaries; the implementation never enumerates unrestricted
segment quadruples. Every bucket lookup, candidate-edge coverage check, label
comparison, and interior-object check consumes one comparison charge. Exact
rounded geometry deduplicates candidates while retaining every contributing
source index.

When adjacent boxes reuse the same top and bottom source strokes, a uniquely
labeled candidate wins; an unlabeled strict companion partition is rejected
as a phantom. Otherwise candidates tie-break by more exact edge coverage, more
independent source boundaries, shorter label distance, top/left geometry, then
source index. A tie through all evidence fields is ambiguous and is not
promoted. These rules reject the ACORD `(36,324,14.4,12)` phantom while
retaining its reviewed `(50.4,324,14.4,12)` labeled neighbor.

`unchecked` requires a closed outline, verified empty interior, unique form
ownership, and one unique label. `checked` requires explicit widget state or a
separately tested interior mark. The interior is the bbox inset by 1 pt.
`unchecked` has zero non-boundary vector ink, filled area, source characters,
or widget state in that inset. A static check mark requires two through four
non-boundary segments, combined length at least 35% of the interior diagonal,
ink spanning at least 35% of both interior dimensions, and filled coverage at
most 50%. A larger filled region is an icon negative. Filled icons, open
shapes, ambiguous overlap, competing labels, unavailable evidence, and
unresolved choice meaning are `ambiguous` or remain evidence-only.

A label candidate begins from 0.5 through 96 pt to the right of a control,
overlaps its vertical span or starts within 4 pt below it, and belongs to the
same group. Lowest horizontal distance wins; candidates within 0.5 pt after
distance and baseline comparison are ambiguous. An unlabeled control is
retained only inside a validated form group where at least three labeled
controls share its width/height within 0.15 pt and the nearest row/column pitch
is at most 24 pt. This retains the four reviewed ACORD unlabeled outlines and
rejects isolated decorative squares.

Empty fields require a visible ruled region or a bounded aligned blank whose
boundary basis is explicit. A label without such a region is unresolved, not
empty. A ruled field contains its label or has a label at most 12 pt above its
top edge. A reviewed implicit inline blank requires label/value tops within
1.25 pt, height in `[6,24]` pt, width at least 24 pt, and a right boundary from
the next label or enclosing group. A region with at least two internal
horizontal and two internal vertical rules remains table-owned and is not
promoted as an empty field. Dense mixed grids remain table evidence; repeated
small controls may be linked as a separate overlay.

## Key-value association

Key-value projection uses current source-grounded public elements after
P03-US04 order. Eligible rows have:

- exactly two consecutive native/recovered scalar text elements;
- finite same-page bboxes and trusted evidence;
- top coordinates within 1.25 pt and heights within 2 pt;
- gap defined as `value.left - key.right`, inclusively
  `2 pt ≤ gap ≤ min(160 pt, 0.35 × page width)`;
- stable key/value x anchors within 2 pt across the group;
- successive row cadence from 4 through 30 pt;
- at least three rows;
- explicit raw key-value graph evidence or consistent group-wide role/style
  contrast; US06 native inference requires bold-left/regular-right;
- no table/list/header/footer membership, ruled-grid ownership, competing
  match, or cross-page continuation.

Component's bold-left/regular-right source style is retained as evidence but
does not rewrite text. At least three rows, exact source order, stable columns,
and no competing owner are mandatory. Same-style two-column prose and
borderless tables are negatives. All endpoints above are inclusive. A
candidate tying another through row count, anchor variance, gap variance,
source order, and source index is rejected rather than arbitrarily selected.
Matching may normalize only for comparison; public key/value strings are exact
predecessor slices.

Groups and pairs sort by `(page, top, left, source index, stable id)`.

## Canonical and Markdown behavior

`canonical-presentation-v1` remains exact-key and schema version `1.0`.
No keys are added to canonical blocks or views.

Canonical replacement is allowlisted by the oracle. The anchor is the exact
listed public/internal predecessor item; the contributor set must match both
the exact ordered public IDs and their exact one-to-one internal element IDs,
plus same-page bboxes. Every contributor is claimed once. A missing, extra,
changed, duplicate, pairwise-ID mismatch, or already claimed contributor keeps
the complete predecessor canonical output and emits one bounded concern.

All six ACORD groups are additive JSON-only and canonical-inert in US06. This
is mandatory, not optional. In particular, the coverage table remains
canonical as its predecessor table; the control overlay is linked through
`form_overlay_of` but appends no duplicate label or control fallback to
canonical Markdown/text. Phase 04 retains ownership of table
recovery/suppression. The accepted ACORD predecessor body/full Markdown/text
byte sizes and hashes are frozen in the oracle.

The three component groups are the only real-corpus atomic canonical
replacements. Their anchors are `p2-i8`, `p2-i17`, and `p3-i4`; contributor
sets are the exact alternating items recorded by the oracle. Internally those
anchors are typed `key_value`; all other contributors become
`consumed_by_relationship`. The legacy public text items remain unchanged in
JSON.

A new sidecar-aware renderer handles validated `form_semantics`; the existing
legacy `fields` renderer is not used. Let `L` be the escaped field labels in
`label_ids` order joined by the explicit derived separator ` · `, and let `D`
be the escaped control label or the derived literal `Unlabeled checkbox` /
`Unlabeled radio`. Records use LF separators with no leading/trailing blank
line. Exact presentation grammar is:

- key-value Markdown: `- **<escaped key>:** <escaped value>`;
- key-value text: `<key>: <value>`;
- one pair per line, no synthetic group heading;
- empty field Markdown is
  `- **<L>:** *(empty source-visible field)*`, and text is
  `<L>: [empty source-visible field]`;
- present field Markdown is `- **<L>:** <escaped exact value>`, and text is
  `<L>: <exact value>`;
- ambiguous field Markdown is
  `- **<L>:** *(value ambiguous; no value emitted)*`, and text is
  `<L>: [value ambiguous; no value emitted]`;
- not-applicable field Markdown is
  `- **<L>:** *(not applicable in source)*`, and text is
  `<L>: [not applicable in source]`;
- proven unchecked checkbox Markdown is `- [ ] <D>` and checked checkbox
  Markdown is `- [x] <D>`;
- an ambiguous checkbox is
  `- **<D>:** state ambiguous`; a
  not-applicable checkbox is
  `- **<D>:** not applicable`;
- radio controls never use task-list syntax. Checked, unchecked, ambiguous,
  and not-applicable radio Markdown are respectively
  `- **<D>:** selected radio option`,
  `- **<D>:** unselected radio option`,
  `- **<D>:** state ambiguous`, and
  `- **<D>:** not applicable`;
- checkbox text is `<D>: <checked|unchecked|ambiguous|not applicable>`;
  radio text is `<D>: <selected|unselected|ambiguous|not applicable>`;
- a source-visible group heading, when one exists in an allowlisted canonical
  synthetic, is Markdown `### <escaped heading>` and plain text
  `<heading>` before its records.

All source text and control characters are escaped. No path uses raw untrusted
HTML, live form inputs, `[signature]`, or a guessed value. The joiner and
bracketed/italicized state phrases are explicit derived presentation, never
source values. The exact component Markdown/text and SHA-256 values are frozen
in the oracle.

## Frontend behavior

The frontend adds a bounded strict `form-semantics` validator. Specialized
rendering is allowed only when exactly one public anchor's
`form_group.anchor_element_id` matches the canonical block primary ID and every
sidecar ID, bbox, state, cardinality, and relationship endpoint validates.

Key-values and fields render with `<dl>`. Static controls render in a labeled
read-only list with textual state, never clickable `<input>` elements. The
coverage sidecar appears after its retained table as an explicitly labeled
static-control panel; it does not alter copy/Markdown output. Empty fields
display an explicit non-value state. No path uses `dangerouslySetInnerHTML`.

Malformed, duplicate, oversized, or inconsistent form metadata fails closed
to authoritative canonical block text. Backend canonical output remains the
source for copy and Markdown download. JSON download preserves the additive
sidecar. Original-preview/page-result navigation continues to use physical
page and source bbox.

## Resource, security, and diagnostic limits

Frozen limits:

| Resource | Limit |
|---|---:|
| Source characters | 500,000/document |
| Source words | 16,384/page; 100,000/document |
| Vector objects | 16,384/page; 262,144/document |
| Curve points | 512/object; 65,536/page; 500,000/document |
| Annotations/widgets | 2,048/page; 10,000/document |
| AcroForm field nodes | 10,000/document |
| AcroForm field depth | 32 `/Kids` edges |
| AcroForm kids | 256/node |
| AcroForm dictionary entries | 256/object |
| AcroForm distinct visited references | 32,768/document |
| AcroForm resolution steps | 65,536/document |
| AcroForm name payload | 256 UTF-8 bytes/name |
| AcroForm string payload | 16 KiB/string |
| AcroForm accounted object bytes | 256 KiB/object |
| AcroForm accounted tree bytes | 8 MiB/tree |
| Candidate shapes | 4,096/page |
| Candidate groups | 256/page; 2,048/document |
| Fields | 128/group; 2,048/page; 10,000/document |
| Controls | 256/group; 2,048/page; 10,000/document |
| Key-value pairs | 32/group; 2,048/page; 10,000/document |
| Labels/value regions | 256/128 per group; bounded by semantic page/document caps |
| Source identities | 64/semantic record |
| Semantic records | 8,192/page; 32,768/document |
| Relationships | 32,768/page; 65,536/document |
| Geometry/association comparisons | 65,536/page |
| Text | 16 KiB/record; 1 MiB inspected presentation/page; 8 MiB/document |
| Public group JSON | 256 KiB/group |
| Retained report | 8 MiB |
| Detailed concerns | 13/group; 256/page; 1,024/document, then one aggregate |
| Extraction/projector deadline | 2.0 s each |

Source-character count is the number of pdfplumber character records; source
word count is the number of `extract_words` records. All declared text sizes
are UTF-8 bytes, and public group/report sizes are compact sorted-key JSON
bytes. Vector count is the sum of pdfplumber line, rectangle, curve, and edge
objects before copying. Curve-point count is the number of source path
commands. Comparison count includes every bucket probe and candidate
predicate. Public group size is measured before page commit.

The role-specific group caps preserve the 256 KiB boundary with complete
public sidecars. Minimal valid exact witnesses measure 259,952 bytes for 256
controls, 260,530 bytes for 128 fields plus their 128 value regions, 247,413
bytes for 256 labels, and 93,075 bytes for 32 key-value pairs. A production-
shaped 32-pair witness with 64 distinct contributors measures 95,105 bytes;
pair 33 requires 66 contributors and is refused. Field/value 129 and label
272 exceed 256 KiB. Page/document aggregate and 64-contributor limits remain
unchanged.

AcroForm preflight visits catalog `/AcroForm` and `/Fields` in source-array
order, then page `/Annots` in page/annotation order. It follows only
`/Fields`, `/Kids`, `/Parent`, `/FT`, `/Ff`, `/V`, `/T`, widget `/Subtype`,
`/Rect`, `/AS`, `/AP`, and `/AP/N`. Every reached object's direct content is
inspected for entry/byte caps, but unrelated references and appearance-stream
bodies are never dereferenced. A field node is each unique dictionary reached
as a `/Fields` or `/Kids` member, plus each unique `/Widget` annotation absent
from that tree, counted once by indirect identity. Reappearance under a second
structural parent is malformed. Root field depth is zero and each `/Kids` edge
adds one, so depth 32 permits 33 nodes on a path. Kids count is raw array
cardinality before deduplication or resolution.

AcroForm byte accounting uses the local `AFOB-v1` decoded-object size, not a
PDF file-span size. Its exact costs are: null/boolean one byte; integer ASCII
decimal bytes; finite real `format(value, ".17g")` ASCII bytes; name one slash
byte plus UTF-8 payload; string two delimiter bytes plus raw post-parse,
post-decryption payload; indirect reference four delimiter/space bytes plus
the decimal object/generation digits; array two delimiter bytes plus item
count plus each direct child cost; and dictionary two delimiter bytes plus
entry count plus each key-name/value cost in sorted name-byte order. A stream
costs its dictionary plus its encoded raw-stream byte count. Direct children
recurse; an indirect reference contributes only its reference-token cost
locally. Nonfinite numbers and unavailable encodings fail closed.

The 256 KiB object limit applies to every first-resolved indirect object and
each direct root before descent. The 8 MiB tree total is the sum of local
`AFOB-v1` sizes for every unique resolved indirect object plus each direct
root occurrence. Shared target bodies count once; every reference token stays
charged to its owner. Checks occur incrementally before copying or decoding.
`/AP/N` stream values remain opaque and are not decoded.

`visited references` and `resolution steps` are separate counters. A distinct
`(object number, generation)` identity consumes one visited-reference charge
on its first resolution attempt, including a dangling identity. Every
semantically required dereference occurrence consumes one resolution step
before cache or cycle checks, so repeats, shared references, cycles, and
dangling references each charge again. Cache hits never erase a step.

Cycle checks are directional: an active repeat in `/Kids` descent, `/Parent`
inheritance, or indirect-reference resolution is cyclic. During downward
traversal, an ordinary reciprocal child `/Parent` pointer is identity-checked
but not recursively followed, so a valid Kids↔Parent link is not a false
cycle. Shared scalar/appearance objects are legal and cached; shared
field/widget nodes are malformed. Page-annotation and field-tree occurrences
unify by identity. A malformed/cyclic tree, unavailable required raw bytes, or
cap breach stops that traversal and marks interactivity unknown with only
bounded diagnostics.

Every resource-table counter and explicitly named page/document aggregate has
an isolated production exact-maximum and maximum-plus-one witness. Exact
maximum succeeds when every nondependent counter is below its limit; maximum
plus one fails at the declared scope. Structurally dependent counters may
meet together (for example, one field owns one value region), and validation
uses table order before page/document aggregate caps. Strict-model list
maxima outside this resource table are defensive schema ceilings: their
accept/reject boundaries are tested directly, but topology or the stricter
256 KiB public-group cap may prevent a full materialized graph from reaching
them. This distinction applies to backlink, evidence-method, relationship-
evidence, and nested fan-out lists; it never relaxes a resource-table counter.
Preflight occurs before copying or Cartesian association. Spatial buckets and
endpoint indexes bound geometry work. The mandatory predecessor page limit is
the configured `Settings.max_pages` (default 100).

The semantic caps are deliberately lower than the relationship caps. The
isolated exact-8,192/page and exact-32,768/document semantic fixtures retain
valid single ownership and semantic edges below 32,768/page and
65,536/document relationships. Conversely, the relationship exact-maximum
fixtures use bounded label/key fan-out while remaining below the semantic
caps. The 32,768 distinct-reference maximum also remains strictly below the
65,536 resolution-step maximum, so both AcroForm counters can be exercised in
isolation.

Allowed concern codes:

- `form_source_evidence_unavailable`;
- `form_source_limit`;
- `form_interactivity_unknown`;
- `form_transform_unavailable`;
- `form_candidate_limit`;
- `form_relationship_limit`;
- `form_geometry_ambiguous`;
- `form_value_boundary_implicit`;
- `form_value_state_ambiguous`;
- `form_control_state_ambiguous`;
- `form_table_ownership_ambiguous`;
- `form_projection_failed_closed`; and
- `form_concerns_truncated`.

Diagnostics contain only fixed messages, bounded counts/limits, page identity,
hashed IDs, and allowlisted exception type. They never contain document text,
URLs, raw metadata, credentials, or filesystem paths.

Extraction or source-report refusal fails the complete US06 stage closed.
Projection overflow or validation failure rolls back the affected page
atomically. A document-global limit rolls back the stage. Idempotent replay
adds no duplicate records, relationships, fields, controls, Markdown, or
concerns.

## Feature flag, ordering, and rollback

The runtime flag is `PARSER_LAYOUT_FORMS_ENABLED`, corresponding to
`parser.layout.forms.enabled`. It defaults to `false` and requires:

- shared IR;
- shared IR normalization;
- canonical serialization; and
- P03-US04 relationship order.

US06 runs after the US05 projection when both are enabled, but it does not
require the US05 flag. Form evidence is extracted only for enabled local PDF
processing and is threaded through the ordinary shared-IR pass and terminal
source-alignment re-entry.

Disabling only the US06 flag performs zero form extractor/projector work and
returns the exact same configured pipeline with
`layout_forms_enabled=false`. When US05 is enabled that is the P03-US05
predecessor; when it is disabled, US06 does not add a dependency or silently
enable it. There are no US06 fields, elements, relationships, canonical
changes, processing metadata, warnings, or concerns.

Malformed page-local source evidence or projection failure restores that
page's elements, bboxes, evidence, relationships, region/page memberships,
presentation IDs, public sidecars, and canonical blocks atomically. A malformed
document-wide AcroForm tree, source/report custody failure, deadline, or
document aggregate limit restores the complete stage predecessor. Sanitized
diagnostics are added only after restoration.

## Verification and retained evidence

Required gates include:

- environment/dependency/default-off and zero-invocation tests;
- strict IR, public shape, serializer, canonical, and endpoint contracts;
- exact ACORD 6-group, 42-label, 24-field, 53 label-edge, and 24-control
  oracle, including all bboxes/source identities and the 216 relationship
  graph;
- exact 19 unchecked / 5 ambiguous / 0 checked states;
- exact component 4 + 7 + 5 = 16 ordered pairs;
- zero fabricated values and exact blank signature;
- decorative square, filled icon, open box, overlap, unboxed `N / A`,
  label-only, duplicate geometry, competing grid/table, real `/Link`,
  technical drawing, finance table, and Markdown-injection controls;
- named checked/unchecked static checkbox, selected/unselected radio,
  pushbutton exclusion, active not-applicable, present/ambiguous value,
  inherited widget, mixed static/interactive, orphan widget, cyclic/deep
  AcroForm, endpoint/closure/aspect/label/mark threshold, shared-edge phantom,
  rotated/cropped/invalid transform, key-value min/max gap,
  anchor/cadence/tie, two-row, borderless-table, and cross-page synthetics;
- every resource-table exact/max+1 limit, every defensive schema boundary,
  deadline, rollback, failure injection, concern truncation, and idempotence;
- Phase 01 serialized-IR exactness and P03-US01–US05 cumulative regression;
- frontend normalization, rendering, source view, copy/download, lint,
  typecheck, production build, unit, and bundle tests;
- real ACORD/component off/on output size, wall time, RSS, and deterministic
  semantic parity.

Isolated gates:

- ACORD extraction p95 ≤150 ms;
- component extraction p95 ≤300 ms;
- projection p95 ≤50 ms;
- peak isolated allocation ≤64 MiB;
- exact/max+1 bounded projector ≤250 ms;
- report ≤8 MiB.

Isolated latency uses two warmups followed by 20 measured
`time.perf_counter_ns()` samples with tracing disabled. Inclusive p95 is
`sorted(samples)[ceil(0.95 * n) - 1]`. Allocation is measured separately with
`tracemalloc`: one warmup, five samples, reset between samples, and the maximum
peak is reported. The 250 ms boundary gate times one isolated exact-maximum and
one maximum-plus-one refusal after construction.

Five fresh-process pairs keep P03-US01–US05 and every other setting identical;
only `PARSER_LAYOUT_FORMS_ENABLED` changes, and off/on execution order
alternates. For pair `i`, `d_i = max(0, enabled_i - disabled_i)`. Paired
overhead is the inclusive p95 of `d_i`; baseline is the inclusive p95 of the
five disabled samples. ACORD requires overhead
`≤ min(0.05 × baseline, 0.453 s)` and component
`≤ min(0.05 × baseline, 0.528 s)`.

Enabled maximum RSS may not exceed disabled maximum by more than 64 MiB.
`ru_maxrss` is bytes on Darwin and multiplied by 1,024 on Linux. Three enabled
semantic outputs must match after removing exactly
`processing.duration_ms`,
`processing.form_semantics.extraction_ms`,
`processing.form_semantics.projection_ms`, and
`processing.form_semantics.total_ms`; no semantic field is stripped. Hosted
requests/tokens/cost remain `0/0/$0`.

The final artifact is
`tracker/phase-03-layout/evidence/P03-US06-form-metrics.json`. It binds final
code/config/frontend/test/policy paths, exact source and oracle identities,
local dependencies/tools, controls, boundary fixtures, rollback, output
sizes, raw and semantic SHA-256, and zero hosted use.
