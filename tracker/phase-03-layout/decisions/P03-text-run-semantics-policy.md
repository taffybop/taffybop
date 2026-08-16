# P03 Text-Run and Redline Semantics Policy

Status: Accepted for P03-US05 implementation  
Date: 2026-07-31  
Scope: Source-visible text style, horizontal-rule association, redline
semantics, and non-destructive source/redline/active projections after
P03-US04

## Decision

P03-US05 is a default-off, local-only semantic overlay on the accepted shared
IR and P03-US04 presentation order. It records sparse source-grounded text runs
and vector rules, then projects them onto an existing text-bearing scalar slot
only when geometry and a unique monotonic text alignment agree. A slot is the
owner's scalar `value`, a table cell's `text`, or a bounded nested item's
`value`/`text`; the target path is explicit and validated. It never invents
text, changes an element or child bbox, infers legal intent from color, or
treats a horizontal rule by itself as proof of insertion or replacement.

The source/redline view is authoritative and remains the default. The optional
active-text view is explicitly derived and removes only runs proven
`deleted`; it keeps `unknown`, placeholder, inserted, replacement, and
unchanged text visible. Every omission is disclosed by stable run ID. No API
or frontend path silently selects active text.

The current PDF adapter may establish deletion from an unambiguous
same-color midline rule. It may establish underline and placeholder evidence
but cannot establish insertion or replacement. Native tracked-change metadata
from a future Office adapter may use the same IR states only after a separate
adapter-specific evidence policy. The source-proven inserted/replacement count
for the P03-US05 PDF denominator is therefore exactly zero.

## Contract placement and compatibility

Public `ParseResult.schema_version` remains `1.0`.
`canonical_presentation` remains the strict, independently versioned
`canonical-presentation-v1` contract; no keys are added to its blocks or
views. With P03-US05 enabled, its Markdown is derived from the element's
redline-preserving `md`, while its semantic `text` remains the complete
source-visible scalar. This is a content projection permitted behind the
P03-US05 flag, not a schema mutation.

Run semantics are additive fields on the owning public content item and typed
records in the IR. The public fields are:

- `text_run_policy: "p03-text-run-semantics-v1"`;
- `text_runs`, ordered by canonical target-path tuple, half-open code-point
  interval, and stable ID;
- `text_rules`, ordered by page-space bbox and stable ID;
- for scalar-value overlays, `redline_markdown`, identical to the enabled
  item's `md`, `active_text`, `active_text_omitted_run_ids`, and
  `active_text_policy: "omit-proven-deletions-v1"`.

Each public `text_runs` entry has exactly:

- `id`, internal `element_id`, allowlisted `target_path`, `text`,
  `source_text`, `start`, `end`, and optional `change_group_id`;
- `bbox: {x, y, width, height, unit: "pt"}`;
- `font_name`, `font_size`, `bold`, `italic`, and
  `color: {space, components}`;
- `change_state`, `decorations`, `placeholder`, ordered `rule_ids`;
- `evidence_method`, `semantic_derivation`, `extraction_policy_id`, and
  `association_policy_id`.

Each public `text_rules` entry has exactly `id`, `bbox` in the same complete
shape, `source_object_kind`, `source_object_index`, `color`, `width`,
`thickness`, `evidence_method`, and `extraction_policy_id`. Public records
never contain a dangling bbox/evidence reference. `text_rules` is exactly the
deduplicated ordered union of rules linked by that item's `text_runs`: no
unrelated page rules and no missing linked rules. Every public run's
`element_id` equals its owning internal element, and its `target_path` resolves
inside that element's own public legacy item. Stable IDs include source
SHA-256, page/element/target identity, interval, and source object identity;
display text alone is never an identity input.

An enabled element with no accepted semantic run receives none of these
fields. Table/nested style overlays retain their target paths and normative
JSON without pretending the owner has one scalar active-text projection. An
enabled unsupported document may expose only a bounded, content-free IR
concern; it does not receive fabricated empty run arrays. Flag-off output
contains no P03-US05 fields, records, extraction work, or concerns.

## Typed IR model

`DocumentIR` gains strict `text_runs` and `text_rules` collections, and each
`ElementRecord` gains an ordered `text_run_ids` list. These are empty by
default so the updated validator can ingest existing IR 1.0 producers. This is
forward ingestion by the new internal validator, not a claim that older
strict, extra-forbid internal validators can ingest new US05 records. Internal
IR is not the public compatibility boundary.

Each `TextRuleRecord` contains:

- stable `id`, source SHA-256, `page_id`, and page-space `bbox_id`;
- source object kind and zero-based source object index;
- normalized color space/components plus a bounded validated raw color value;
- finite width/thickness;
- evidence method `vector`; and
- the source extraction policy ID.

Each `TextRunRecord` contains:

- stable `id`, source SHA-256, `page_id`, owning `element_id`, allowlisted
  `target_path`, target-text SHA-256, and `change_group_id` when applicable;
- `text`, `source_text`, and half-open Unicode code-point `start`/`end`
  offsets into the existing target scalar;
- page-space `bbox_id`, finite font size, source font name, `bold`, `italic`,
  normalized color, and ordered source character indexes;
- orthogonal `change_state` (`deleted`, `inserted`, `replacement`, `unknown`,
  or `unchanged`), ordered `decorations` (`strikethrough`, `underline`), and
  `placeholder` boolean;
- ordered linked `rule_ids` and evidence IDs;
- evidence method and an allowlisted semantic derivation; and
- the extraction and association policy IDs.

The IR validator requires globally unique record IDs, resolvable same-page
owners/bboxes/evidence/rules, matching source SHA-256 and target digest, source
character indexes in increasing order, exact
`resolved_target[start:end] == text`,
`0 <= start < end <= len(resolved_target)`, and ordered non-overlapping run
intervals per `(element_id, target_path)`. The only target paths are
`["value"]`, `["cells", nonnegative_index, "text"]`, and
`["items", nonnegative_index, "value"|"text"]`; the referenced public child
must exist, have a finite same-page bbox, and contain a string. Adjacent style
runs may share one `change_group_id`. A logical change group may link one or
more adjacent runs to one or more rules; the confidentiality banner is the
reviewed many-to-many case.

Public JSON is a deterministic projection of these typed records. JSON is
normative for font, color, style, geometry, provenance, rule links, and
orthogonal semantic fields. Markdown is intentionally lossy.

## Source inventory and segmentation

The native PDF reference extractor is the project-pinned `pdfplumber 0.11.10`
over the original immutable PDF bytes. It records source page and object
indexes before sorting. Page-space uses top-left coordinates in PDF points:
`[x0, top, x1, bottom]` is stored as `x`, `y`, `width=x1-x0`,
`height=bottom-top`.

For this policy, a `source line` is a deterministic baseline cluster, not
pdfplumber's higher-level text-line guess. A page is eligible only when its
declared rotation is `0 mod 360` and every participating character has an
upright, finite, positive, axis-aligned text matrix (`abs(b) <= 1e-6`,
`abs(c) <= 1e-6`, `a > 0`, `d > 0`) and a finite in-page positive bbox.
Unsupported rotation/matrices retain no classified runs and use
`text_run_transform_unavailable`.

For each eligible character, top-left baseline is
`page_height - matrix[5]`. Characters are visited by stable source object
index and looked up in half-open `2.0 pt` baseline buckets keyed by
`floor(baseline / 2.0)`. All buckets intersecting the character's maximum
eligible baseline range are queried. If more than eight line clusters remain
eligible before tie-breaking, the page is ambiguous and fails closed; at most
eight existing line candidates may be inspected. A character joins a line
only when both:

- absolute distance from the line's current median baseline is inclusively at
  most `max(0.75 pt, 0.10 * max(character_font_size,
  line_median_font_size))`; and
- overlap with the line's maintained current vertical interval
  `[minimum accepted top, maximum accepted bottom]`, divided by the smaller
  of the character height and that interval height, is inclusively at least
  `0.50`.

If several lines qualify, choose smallest baseline distance, then greatest
vertical-overlap ratio, then smallest first source-character index. Otherwise
create a new line. After clustering, line order is `(minimum top, minimum x0,
first source index)` and character order inside a line is `(x0, source
index)`. A line's medians are recomputed from its accepted finite values.
Threshold equality joins; the smallest representable value above either
boundary splits. Dedicated tests pin both boundaries, the multi-font
confidentiality baseline, same-baseline postal columns, superscript
separation, tie-breaking, missing matrices, and 90/180/270-degree rotation.

Characters retain native source indexes and are grouped in the frozen
line/character order above, only within one physical page and one source line.
A run splits at a line boundary, font-name change, font-size difference
greater than `0.01 pt`, bold/italic change, color change, semantic-state
change, a forward horizontal gap greater than
`max(2.0 pt, 0.5 * font_size)`, an x-coordinate backtrack greater than
`1.0 pt`, or a 16 KiB text boundary. This spatial split keeps the postal
glossary's same-style left and right cells distinct. Internal whitespace is
retained. Boundary whitespace is retained only when it uniquely maps to the
same public target and, for a decorated group, its glyph satisfies the frozen
rule-overlap gate. Otherwise only that boundary whitespace is trimmed before
the run bbox/offset is finalized. A whitespace-only source candidate is not a
semantic run and is dropped without a concern; it remains accounted for in
the bounded source-character inventory. This handles source trailing spaces
where the normalized public target deliberately ends at the last visible
non-space glyph. Font-name tokens containing `bold`, `black`, or `demi` are
bold; tokens containing `italic` or `oblique` are italic. The raw name is
always retained so these conservative booleans do not replace source evidence.

The public overlay is sparse: a run is retained when it has a change state,
decoration, placeholder evidence, non-black color, bold, italic, or explicit
native tracked-change evidence. Ordinary black regular prose remains in the
owning scalar and is not expanded into redundant per-character JSON.

Before sparse filtering and the run-level overlap gate, a same-page,
same-color rule in an accepted vertical band may refine a maximal style run at
source-glyph boundaries. The refinement selects the maximal contiguous
non-empty glyph subsequence whose non-whitespace glyph centers lie within the
rule's horizontal interval expanded by `0.25 pt`. Boundary whitespace is
included only when its own glyph overlap is at least `80%`; otherwise it stays
with the undecorated prefix/suffix. The original style metadata and source
character indexes remain exact on every split. Adjacent refined style pieces
are evaluated as one logical geometry group, then retained as separate typed
style runs with one `change_group_id`.

This rule-driven refinement is necessary for ordinary inline underlines such
as `Exhibit A`, which is otherwise a small substring of a much longer
same-font line. It cannot create a semantic match by itself: the refined
logical group must still pass every color, vertical, coverage, uniqueness, and
overhang gate below. Refinement that selects disjoint glyph islands, crosses a
target-slot boundary, or has competing rules is ambiguous and fails closed.

Source-to-target matching first uses same-page target-bbox containment with a
`2.0 pt` finite margin, then a monotonic comparison view that applies Unicode
NFKC, maps curly quote/dash variants to their ASCII comparison equivalents,
and collapses whitespace. Raw source and public strings are never rewritten by
that comparison. The pinned PDF/public-adapter boundary has one narrow
source-curly fallback: a source curly double quote may also compare with the
adapter's generic ASCII apostrophe, while already-straight ASCII single and
double quotes remain distinct. Strict and fallback matches are unioned; if
they resolve to different targets or intervals, alignment is ambiguous.
Table-cell bboxes therefore separate the postal glossary's two same-line
columns before text matching. A same-element scalar/child pair with
byte-identical text and bbox is one Docling structural alias and canonicalizes
to the explicit child path; non-identical competing owners/children remain
ambiguous. The match must resolve to one allowlisted target and one interval;
the stored `text` is always the exact public target slice and `source_text` is
the exact source-glyph string. Competing owners/children, repeated intervals,
non-monotonic alignment, or missing scalar text fail closed.

## Rule inventory and bounded association

A candidate horizontal rule is a native PDF line or filled rectangle with
finite geometry, width at least `2.0 pt`, thickness at most `1.5 pt`, and
aspect ratio at least `3:1`. Rules retain their original object kind/index;
they are not routed through the table extractor and are never discarded
because they resemble a table rule.

Two finite colors match only when they have the same normalized color space
and each normalized component differs by at most `1/255`. Missing,
pattern-based, or incompatible colors are `unknown` and cannot prove a
change state.

A rule can associate with a source run only when:

1. page identity and coordinate unit agree;
2. horizontal overlap is at least `2.0 pt` and at least `80%` of the run's
   glyph width;
3. colors match under the rule above; and
4. the normalized rule-center position
   `(rule_center_y - run_top) / run_height` is inclusively within
   `[0.35, 0.70]` for strikethrough or `[0.75, 1.10]` for underline; and
5. for the complete adjacent logical geometry group covered by that rule,
   horizontal rule overhang beyond the group's glyph union is no more than
   `max(4.0 pt, 0.20 * group_width)` in total.

Threshold endpoints are inclusive. Synthetic tests pin values just below, at,
and just above every threshold. A rule may cover adjacent style runs in one
logical group, and one logical group may use adjacent rule segments. If a rule
would select non-adjacent groups, competing owners, both vertical bands, or
more than 64 runs, the affected group remains unclassified and receives a
sanitized ambiguity concern.

`change_state=deleted` requires at least one uniquely associated same-color
midline rule; `strikethrough` is recorded independently. Underline alone
records only `underline`. A run of 3 through 128 literal underscores with an
accepted same-color underline records `placeholder=true` and
`change_state=unknown`. Color alone, underline alone, brackets, whitespace,
or proximity to another changed run cannot prove inserted or replacement
state. Boundary touching and overlap below the frozen threshold are not
associations.

## Source, redline, active, and frontend projections

The owning scalar `value` remains the complete source-visible source/redline
default. Redline Markdown is generated for scalar-value overlays from that
value and accepted non-overlapping intervals:

- deleted text is encoded as `~~escaped text~~`;
- underlined non-deleted text is encoded as
  `<u>HTML-escaped text</u>`; and
- all other text is Markdown-escaped plain text.

When a run is both deleted and underlined, deletion is the only Markdown
wrapper and JSON retains both decorations. Bold, italic, font, and color remain
normative JSON evidence and do not create ambiguous nested Markdown. Literal
backslashes, Markdown metacharacters, underscores, and HTML delimiters are
escaped; source text can never inject markup.

`active_text` removes the union of proven-deleted scalar-value intervals only.
It preserves the predecessor bytes outside those intervals and records the
exact omitted run IDs in source order. Unknown or ambiguous evidence remains
visible. Table/nested target paths remain independently addressable normative
JSON and are not flattened into an owner-level active string. Repeated
projection is byte-identical and does not double-wrap markup.

Scalar redline Markdown preserves the predecessor's type envelope. For a
heading, the exact validated `#{1,6} ` prefix remains and only its scalar body
is decorated, except for a complete one-run vector deletion that is also
proved to be a compact top-right revision banner by source-page geometry. That
bounded banner is ordinary redline text; a fully struck mid-page, broad, or
left-aligned heading retains its heading envelope. Plain text/header/footer
scalars preserve their existing outer envelope. Table, list, code, formula,
HTML, or any envelope that cannot be losslessly isolated receives normative
run JSON but no owner-level `md` rewrite.

The frontend validates the additive run shape and renders source-visible
semantics through React text nodes using `<del>` and `<u>` elements. It never
uses `dangerouslySetInnerHTML`, never infers semantics from color/geometry,
and never makes active text the default. A run overlay may be applied to
`CanonicalBlock.text` only when the block's
`contributing_element_ids == [run.element_id]`, all runs target `["value"]`,
the matched public item is unique, and `block.text` is byte-identical to that
item's scalar value. Otherwise the canonical rendered path displays the
unchanged authoritative `block.text` and exposes run semantics through JSON
and source/redline Markdown; it never guesses offsets across a combined
contributor block. Rendered output, normalized JSON, copy, download, and
canonical Markdown must preserve backend-authoritative run/order state.

## Fixed reviewed denominator

The immutable primary source is
`benchmark-expertmodeldata/purchase-agreement.pdf`, 152,828 bytes, SHA-256
`00a8eec6c3ade84be7f9016c8c27547eab4a1802746bc146b00af71216ccfd14`.
Physical page 1 is `612 x 792 pt`, rotation 0, and under the pinned inventory
contains 3,338 characters, 13 filled rectangles, and no line, curve, image, or
annotation objects. The six logical deleted spans are:

1. `Draft of 6/1/20`;
2. `This is a draft document. Certain updates will be needed prior to
   finalizing this.`;
3. `In particular, bracketed items with “[ ]” indicate a known open/non-final
   item.`;
4. `This is Confidential to The City of Johnstown`;
5. `June`; and
6. `23`.

They require exactly six logical deleted groups, seven exact unique
`(change_group_id, rule_id)` red strike associations, and nine exact
`(text_run_id, rule_id)` red links. The confidentiality span is split across
two adjacent rule rectangles and multiple source styles: its first rectangle
links the adjacent `This is `, bold `Confidential`, and ` to ` runs as one
group, while its second links the `The City of Johnstown` run.

The blue denominator is exactly two runs and four underline-rule
associations: `EXECUTION VERSION` with two blue rules and exactly seven
underscores (`_______`) with two blue rules. The former is active
double-underlined text; the latter is a placeholder with unknown change state.
Neither is inserted or deleted.

The exact same-page false-deletion controls are `EXECUTION VERSION`,
`Background`, and `Exhibit A`, all of which must have
`change_state != deleted`. The last two retain ordinary black underline
evidence. The red rule over `June` grazes the separate black opening bracket
by about `0.0105 pt`; the bracket must not associate. The red rule after `23`
only boundary-touches the following placeholder; it must not associate.

The scored metrics are:

- repair submetric: 3/3 known expert omissions (`Draft of 6/1/20`, `June`,
  `23`);
- complete deletion: 6/6 logical groups, 7/7 unique
  `(change_group_id, rule_id)` strike associations, and 9/9 exact
  `(text_run_id, rule_id)` links;
- blue evidence: 2/2 runs and 4/4 exact underline associations;
- false deletion: 0/3 on the named same-page controls and zero on every frozen
  synthetic/table-rule negative;
- style/provenance: every scored run retains exact text/slice offsets, bbox,
  font/size/bold/italic/color, raw rule IDs/bboxes, evidence method, and
  derivation;
- state: zero source-proven inserted/replacement PDF runs;
- order: exact seven-entry source sequence `Draft` -> first warning ->
  bracketed warning -> confidentiality warning -> `EXECUTION VERSION` ->
  `ASSET PURCHASE AGREEMENT` -> opening paragraph;
- predecessor order: purchase P03-US04 3/3 and full P03-US04 41/41 remain
  exact; and
- deterministic JSON/Markdown, active-view omission disclosure, and
  idempotence are 100%.

The benchmark case report's `511 words` is not a US05 metric. It is not
reproduced by pinned pdfplumber, which returns 489 under its tokenizer.
Character, rule, run, and association inventories above are the normative
method.

## Mandatory controls and fixtures

The P00-US09 `GAP-REDLINE-001` four-role matrix is mandatory:

- target: `p00-us06:purchase-agreement:expert-row-01`;
- related positive: `p00-us08:postal-10k:expert-row-03`;
- non-target regression: `p00-us06:finance-10k:expert-row-01`; and
- negative/ambiguous claim:
  `p00-us06:purchase-agreement:expert-row-05`.

The purchase row-05 expert flattening `[June 23_______]` is rejected as an
oracle, while its physical `June`, `23`, and underscore region is required
positive source evidence. Postal page 1 must retain exactly four italic source
spans at public table-cell target paths `["cells",20,"text"]`,
`["cells",21,"text"]`, `["cells",66,"text"]`, and
`["cells",67,"text"]`: `CARES Act`, its expanded name, `Exchange Act`, and its
expanded name. It is a style control, not a rule-association control. Its
immutable PDF is 83,589 bytes, SHA-256
`72b984cde38a5dc8e13949c3699eb371eb26e14cdd92480091fe3f10f2857e74`.
Finance page 1 must retain company/title/units text, order, and bold/style
evidence without any false deletion. Its immutable PDF is 87,105 bytes,
SHA-256
`e924db5e2dbe8845997093d550b3dcdea5560b5c4a75957b6ef084f556149086`.
Finance cannot be replaced by a plain-legal fixture.

Story-local synthetic fixtures are immutable generated dictionaries with
these IDs and exact roles:

- `synthetic:p03-us05:plain-legal-v1`: black regular prose, no rules;
- `synthetic:p03-us05:table-rule-v1`: rule crossing a cell boundary with no
  same-color midline text;
- `synthetic:p03-us05:decorative-rule-v1`: horizontal separator near but not
  in either accepted vertical band;
- `synthetic:p03-us05:ambiguous-overlap-v1`: one rule competing across
  non-adjacent groups;
- `synthetic:p03-us05:markup-injection-v1`: Markdown and HTML metacharacters;
- `synthetic:p03-us05:thresholds-v1`: just-below/at/just-above geometry and
  color thresholds;
- `synthetic:p03-us05:transforms-v1`: finite raw-to-page transforms plus
  missing/cross-unit variants; and
- `synthetic:p03-us05:limits-v1`: exact-max and max-plus-one inputs.

The synthetic source payload and expected digest are retained in final
evidence. Settlement/plain legal corpus cases are supplementary and cannot
replace the mandatory quartet or named synthetics.

## Bounds, diagnostics, failure, and security

Before source association, enforce:

- at most 4,096 retained runs per page and 10,000 per document;
- at most 4,096 candidate horizontal rules per page and 10,000 per document;
- at most 8,192 text-bearing target slots per page and 65,536 per document;
- at most 8 spatially eligible target slots per source run and 65,536 total
  source-run-to-target comparisons per page;
- at most 64 associated rules per run and 64 runs per rule;
- at most 65,536 association candidates per page;
- at most 500,000 inspected source characters per document;
- at most 1 MiB inspected target text per page and 8 MiB per document;
- at most 16 KiB source/public text per run;
- at most 8 MiB serialized US05 report data per document;
- at most 256 UTF-8 bytes per font name;
- color space exactly `gray`, `rgb`, `cmyk`, or `unknown`, with respectively
  1, 3, 4, or 0 finite normalized components in `[0,1]`; raw color retains at
  most four finite numeric components or one fixed `unknown` marker;
- at most 16 detailed US05 concerns per page, 256 per document, and 512 total,
  followed by one sanitized aggregate concern; and
- a 2 second local US05 extraction/association deadline within the document's
  existing deadline.

Rules, runs, and target slots are indexed by page, vertical band, and
horizontal interval before any text comparison. Candidate target slots are
then ranked by containment/overlap and stable path; only the frozen maximum
may enter monotonic text alignment. Association is
`O((R + V + T) log(R + V + T) + C)` time and `O(R + V + T + C)` memory,
where `C` is capped rule and target overlap. No all-pairs run/rule,
run/target, or text search is permitted. Exact maximum inputs must complete;
maximum-plus-one restores the affected predecessor page without partial
records or pairwise work and emits the corresponding content-free limit
concern.

Allowed detailed concern codes are:

- `text_run_source_unsupported`;
- `text_run_source_invalid`;
- `text_run_source_limit`;
- `text_run_rule_limit`;
- `text_run_alignment_limit`;
- `text_run_alignment_ambiguous`;
- `text_run_rule_ambiguous`;
- `text_run_transform_unavailable`;
- `text_run_projection_failed_closed`; and
- `text_run_concerns_truncated`.

Diagnostics contain only fixed codes/messages, bounded counts/limits, page
identity, policy ID, and an allowlisted exception type. They never contain
document text, glyphs, font names, colors, URLs, source bytes, raw references,
or rule metadata.

Extraction and projection are page-transactional. Invalid geometry, ambiguous
ownership, limit overflow, mapping failure, validation failure, or unexpected
exceptions restore the exact affected P03-US04 predecessor page and its IR
records, then add only a bounded sanitized concern. A document-level source
failure restores the exact predecessor document. The complete candidate
`DocumentIR` is validated inside the rollback boundary before commit.

## Configuration, composition, raster scope, and rollback

`PARSER_LAYOUT_TEXT_RUN_SEMANTICS_ENABLED` maps to
`Settings.layout_text_run_semantics_enabled`, defaults to `false`, and requires
both shared IR normalization and
`PARSER_LAYOUT_RELATIONSHIP_ORDER_ENABLED=true`. It runs after P03-US04 and is
included in ordinary and terminal source-alignment re-entry checks.

When the flag is false, the PDF source extractor is not called and API,
Markdown, IR, canonical output, diagnostics, extractor-call count, and
performance are the exact P03-US04 predecessor. This resolves the earlier
contradiction with “retain raw diagnostics”: new rule/run diagnostics exist
only for enabled processing. Disabling the single flag is the exact rollback.

Native PDFs with character and vector objects are the exact semantic target.
Direct raster images and image-only PDFs preserve visible predecessor text,
emit no false deletion, and may report only
`text_run_source_unsupported`; they are not required to reproduce native font
names, colors, vector-rule IDs, or change states. “Equivalent raster/PDF
presentation” means visible-text and ordering parity plus an explicit
unavailable/unknown semantic status, not fabricated evidence. OCR-based
redline detection and Office tracked-change adapters are separate future
scope.

## Verification and evidence custody

Dedicated paths are:

- `tests/stories/phase_03/test_p03_us05_redline_runs.py`;
- `tests/stories/phase_03/test_p03_us05_adversarial.py`;
- `tests/stories/phase_03/test_p03_us05_algorithm_hardening.py`;
- `tests/contract/test_p03_us05_text_run_contract.py`;
- `tests/contract/test_p03_us05_target_path_order_interop.py`;
- `tests/fixtures/p03_us05_target_path_order.json`;
- `tests/regression/phase_03/test_p03_us04_real_reading_order.py` as the
  sealed 41-pair predecessor oracle;
- `tests/regression/phase_03/test_p03_us05_real_redline_runs.py`;
- `tests/performance/test_p03_us05_text_run_performance.py`;
- `tests/performance/test_p03_us05_retained_metrics_artifact.py`;
- `tests/benchmarks/text_run_semantics_metrics.py`; and
- `frontend/tests/p03-us05-redline-runs.test.mts`.

Final parser latency uses five alternating fresh-process purchase pairs with
P03-US01 through P03-US04 enabled and only P03-US05 toggled. Inclusive clipped
p95 overhead must be at most both 5% of the current paired predecessor and
`0.309 seconds`. The retained `6.18 s / 1,401.0 MiB` purchase number is labeled
the M0 reference, never represented as the paired predecessor distribution.
Five fresh-process Uber pairs record the memory guard.

After two warmups and 20 samples, source extraction p95 is at most `150 ms`
with peak traced allocation below `64 MiB`; association/projection p95 is at
most `50 ms` with peak traced allocation below `32 MiB`. The exact maximum
boundary is at most `250 ms`; maximum-plus-one must fail closed. Hosted model,
network, and hosted parser usage are exactly zero.

The retained artifact is
`tracker/phase-03-layout/evidence/P03-US05-text-run-metrics.json`. It binds raw
and semantic SHA-256, final implementation/test/frontend hashes, immutable
source size/SHA records, dependency locks, local tool identity, the mandatory
control matrix, synthetic fixture digests, exact denominators, flag-off
extractor count, idempotence, performance samples/methods, output sizes, and
zero hosted usage.
