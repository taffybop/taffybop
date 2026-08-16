# P02 Spatial OCR Token Preservation Policy

Status: Accepted  
Date: 2026-07-30  
Applies to: P02-US06

## Context and source truth

OCR already produces exact token text, confidence, pass identity, and bboxes,
but the current item projection can deduplicate equal line strings without
considering geometry. That can hide spatially distinct chart labels and
repeated running text. Conversely, normal and sparse OCR passes can retain
overlapping readings of the same pixels as if they were independent primary
tokens.

The retained catastrophe baseline contains twelve source year tokens and
twelve source bboxes even though its cleaned text previously fused the decimal
labels. It also retains the exact rejected token `iH` at confidence `0.4437`,
with a finite positive bbox, in both the detected-image evidence and its shared
IR projection. The source says `iH`; this policy does not reinterpret it as
`1H`.

## Additive occurrence contract

When enabled, an OCR-backed item may add `ocr_token_occurrences` and
`ocr_occurrence_summary`. The occurrence array is evidence, not another
canonical child collection. It is excluded from canonical Markdown, canonical
plain text, legacy property presentation, and canonical contribution
deduplication.

Each bounded occurrence retains:

- `occurrence_id` and `line_occurrence_id`;
- exact source `text`;
- page-space `bbox` and, when present, exact `crop_pixel_bbox`;
- source confidence, OCR pass, and word index;
- `selected`, identifying the deterministic representative of an overlapping
  equivalent cluster;
- `primary_selected`, which is true only when the existing accepted OCR line
  contributes that occurrence to the item value;
- `short_alternative` and `retention_reason`; and
- `duplicate_of` on every non-selected overlapping equivalent.

The summary uses schema version `1.0` and records total, selected, duplicate,
grounded-short, invalid, oversized, and truncated counts. It also records a
fail-closed overflow state when an additive payload cannot be emitted within
the approved bound.

The occurrence projection itself never promotes text. Geometry-aware handling
may preserve two already-accepted equal OCR lines at distinct locations in an
enabled item value. A rejected or short alternative cannot enter the item
value, Markdown, plain text, or canonical block solely because this flag is
enabled.

## Stable identity

IDs are document-scoped SHA-256 values, not process-local or Python hash
values. The identity payload uses canonical JSON with sorted keys, compact
separators, ASCII escaping, and non-finite numbers rejected.

`line_occurrence_id` binds the policy/schema version, source-document identity,
page index, owner/region identity and bbox, source line bbox, OCR pass, and
line index. `occurrence_id` additionally binds exact token text, token bbox,
crop-pixel bbox when present, and word index. Implementations may prefix the
hex digest with a schema label, but the same retained evidence must produce
the same complete ID across runs and processes. Distinct page, owner, region,
line, token, or geometry identity must produce a distinct ID.

## Text equivalence and geometry

Comparison equality is limited to Unicode NFC plus whitespace normalization.
The retained/emitted source text is never normalized or rewritten. NFKC,
case-folding, transliteration, confusable repair, punctuation invention,
semantic correction, and language-model completion are forbidden.

Two candidates are duplicate equivalents only when all of these hold:

- their comparison text is equal;
- they belong to the same page and owner/region;
- both bboxes are finite and have positive width and height; and
- intersection area divided by each candidate's area is at least `0.80`.

Overlap-of-smaller alone is insufficient. Equal text at distant or merely
touching bboxes remains separately addressable, including repeated
headers/footers and repeated chart labels.

For each equivalent overlap cluster, the representative is chosen by this
ordered key:

1. an occurrence already contributing through the accepted merged OCR line;
2. another accepted normal OCR line before a rejected diagnostic line;
3. higher retained confidence, with missing confidence last;
4. standard OCR pass before sparse or other alternative passes;
5. lower retained line index, then lower word index; and
6. lexicographically lower stable occurrence ID.

The winner is `selected=true`. Every loser remains attributable with
`selected=false` and `duplicate_of` pointing to the winner. Cluster selection
does not convert a diagnostic into primary text.

## Grounded short alternatives

A short alternative may be retained only when:

- its exact text matches ASCII `[A-Za-z0-9]{1,3}`;
- its line was rejected only for low confidence;
- its retained token confidence is at least `0.65` times the configured
  primary OCR confidence threshold;
- its bbox is finite and positive, and at least `0.95` of its area lies inside
  a structurally classified `chart` or `diagram` content region; and
- it passes the same page, owner, identity, and resource checks as every other
  occurrence.

Generic images, pages, photographs, tables, forms, absent roles, distant role
labels, invalid geometry, and isolated low-confidence short noise do not
corroborate a short alternative. Chart/diagram containment proves only that
the hypothesis is worth retaining; it does not establish legend membership or
semantic meaning.

`iH` and `1H` are different hypotheses. The exact retained bytes, bbox, and
confidence remain available independently; neither value may be substituted
for the other. A grounded short alternative is always presentation-inert and
`primary_selected=false`.

## Resource and failure bounds

| Bound | Value |
|---|---:|
| Maximum retained occurrences per item | 2,048 |
| Maximum grounded short alternatives per item | 256 |
| Maximum token text per occurrence | 256 Unicode code points |
| Maximum serialized additive occurrence payload per item | 1 MiB |

Existing OCR input, TSV, pixel, word, and deadline limits remain authoritative
before this projection. Candidate traversal follows retained evidence order,
uses bounded geometry buckets, and must not perform an unbounded document-wide
all-pairs comparison.

Invalid or non-finite geometry is omitted from the additive projection and
counted; it is never selected or promoted. Oversized text is omitted rather
than truncated. Occurrence and short-alternative excess is deterministically
truncated at the declared boundary and reported in the summary and a bounded
parse concern while the original OCR diagnostic evidence remains untouched.
If the final additive payload still exceeds 1 MiB or fails validation, the
occurrence array is omitted for that item, the summary records fail-closed
overflow, and prior item/canonical bytes remain unchanged. No failure path
partially promotes, repairs, or deletes source text.

## Compatibility, flag, and rollback

`parser.ocr.spatial_token_preservation.enabled` /
`PARSER_OCR_SPATIAL_TOKEN_PRESERVATION_ENABLED` is default off. Enabling it
requires `parser.ocr.numeric_cleanup_v2.enabled`; it does not require text
reconciliation because direct images and image-only documents must retain
spatial OCR evidence too.

Every new argument defaults to false. Disabled pipeline and adapter callers
omit the new keyword so existing observer/monkeypatch call shapes, item
values, diagnostics, JSON, Markdown, text, and canonical contributions remain
byte-equivalent to the completed P02-US05 path. The two additive keys are
absent while disabled.

Disable spatial token preservation to restore the exact P02-US05 projection
and text-only line deduplication. Raw OCR tokens and existing diagnostic
evidence remain available on both paths.
