# P02 Text Reconciliation Policy

Status: Accepted  
Date: 2026-07-30  
Applies to: P02-US04 through P02-US06

## Context

P02-US02 can derive deterministic text from a narrowly safe embedded-font
program. P02-US03 can retain OCR candidates from pixels only when font recovery
explicitly refuses a span. P02-US04 selects one representation only when those
source, geometry, completeness, script, and confidence contracts justify it.
It does not correct language, complete text, or globally deduplicate equal
strings.

## Identity and source binding

- Reconciliation uses strict version `1.0` reports and policy ID
  `text-reconciliation-v1`.
- The document IR, audit, recovery, selective-OCR input, and reconciliation
  report must bind to the same exact PDF SHA-256.
- Every group and candidate has a stable unique identity scoped by source PDF,
  page, owner, span/run, bbox, and source evidence identity.
- A decision retains owner/page/source bbox, candidate and evidence IDs,
  lineage family, component eligibility/score, reason, and every bounded
  alternative. Dangling, duplicate, cross-page, replayed, or contradictory
  provenance fails closed before mutation.
- A selected string is byte-for-byte one retained candidate value. Unicode NFC
  may be used only for comparison; it is never emitted as a repair.

## Independence and authority

Independence is source lineage, not engine or method count:

| Lineage family | Examples treated as one observation |
|---|---|
| `pdf_text_layer` | native extraction, PDFMiner, Docling/layout/vector views of the same text layer, and `source=mixed` |
| `embedded_font_program` | the bounded cmap/hmtx/glyph reconstruction authorized by P02-US02 |
| `rendered_pixels` | both Tesseract PSM 3 and PSM 11 readings of one P02-US03 crop |

Duplicate IR nodes, legacy summaries, passes, or engines in one family do not
add votes. MODEL, DERIVED, generated captions, dictionaries, language
plausibility, and outside facts have no text-selection authority.

A healthy native span remains authoritative. One complete P02-US02 safe-font
reconstruction outranks unsafe native/OCR evidence. OCR may win only when:

- audit/recovery explicitly mark the exact span unsafe and refused;
- the source crop, affine, cost, pass, candidate, and token evidence are
  complete and transform-valid;
- retained token count equals declared word count and no relevant
  candidate/token truncation or malformed-output concern exists;
- confidence is at least `0.90`;
- candidate and target have at least `0.80` reciprocal area overlap;
- its script is independently supported; and
- its score clears the runner-up by at least `0.10`.

Tesseract confidence is engine evidence, not a probability. Missing confidence
is ineligible. Stable IDs order audit traces only and never break a semantic
tie. Text-equivalent observations are collapsed by normalized comparison and
lineage before margins are computed.

## Geometry and replacement safety

- All geometry must be finite, positive, same-page top-left page points through
  finite invertible transforms.
- Candidate/target eligibility requires intersection divided by each box area
  to be at least `0.80`; overlap-of-smaller alone is insufficient.
- Whole-owner replacement additionally requires at least `0.90` reciprocal
  overlap between owner and target.
- Otherwise, replacement requires one exact, uniquely located source substring
  or retained ordered token/glyph alignment. Owner ties, partial overlap, a
  candidate touching multiple owners, multiple spans touching one replacement
  range, or padded-crop neighbor text remain unresolved.
- Reconciliation is scoped by geometry and identity. Equal text at distinct
  bboxes is never globally suppressed.

## Unicode and script policy

- Comparison may normalize to NFC and normalize whitespace only for equality.
  No NFKC, transliteration, confusable substitution, autocorrection, case
  restoration, punctuation invention, or semantic completion is allowed.
- Unsafe Unicode controls and unassigned/private/surrogate/noncharacter
  scalars are ineligible, matching the P02-US02 safety boundary.
- Common and Inherited scalars attach to a supported base script. A new or
  mixed strong script without independent safe context or configured OCR
  language support remains unresolved. Unknown expected script means no
  script-based guess.

## Terminal decisions and mutation

Every considered group has exactly one terminal outcome:

- `selected`: a complete eligible alternative wins with a documented rule and
  margin;
- `unchanged`: the existing healthy or already-safe deterministic primary is
  authoritative; or
- `unresolved`: no candidate clears every gate and margin.

Unresolved decisions leave prior primary/canonical bytes unchanged and add one
bounded concern. All alternatives remain attributable. A selected alternative,
its relationship, evidence, legacy diagnostic, and decision record must agree
on selection. Exactly one representation enters primary value/Markdown and the
canonical block; the duplicate alternate presentation path is suppressed by
identity without deleting evidence or changing unrelated order.

## Resource and failure bounds

| Bound | Value |
|---|---:|
| Maximum groups per document | 512 |
| Maximum candidates per group | 16 |
| Maximum total candidates | 4,096 |
| Maximum evidence references per candidate | 64 |
| Maximum candidate text | 4,096 Unicode code points |
| Maximum retained concerns | 512 |
| Maximum serialized reconciliation report | 8 MiB |
| Aggregate reconciliation deadline | 2 seconds |

Grouping must use page/owner/span identity or a bounded spatial index, not an
unbounded all-pairs scan. Bounds and deadlines are checked inside loops.
Invalid input, exhaustion, or final report-validation failure is transactional:
no partial primary/canonical mutation occurs, prior evidence remains, and one
bounded fail-soft concern is retained. Output order is deterministic.

## Compatibility, flag, and rollback

`parser.text_reconciliation.enabled` /
`PARSER_TEXT_RECONCILIATION_ENABLED` is default off and requires:

- `PARSER_SHARED_IR_ENABLED=true`;
- `PARSER_SHARED_IR_NORMALIZATION_ENABLED=true`;
- `PARSER_TEXT_INTEGRITY_FONT_AUDIT_ENABLED=true`;
- `PARSER_TEXT_INTEGRITY_FONT_RECOVERY_ENABLED=true`; and
- `PARSER_TEXT_INTEGRITY_SELECTIVE_SPAN_OCR_ENABLED=true`.

Flag-off output is byte-equivalent to the finalized P02-US03 path, including
existing safe-font recovery and inert selective alternatives. Flag-on
unresolved output preserves prior primary bytes except additive diagnostics.
Disable reconciliation to restore the P02-US03 selection behavior while
retaining audit, recovery, and OCR alternatives.
