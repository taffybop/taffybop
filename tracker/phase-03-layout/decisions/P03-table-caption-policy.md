# P03 External Table-Caption Policy

Status: Accepted  
Date: 2026-07-31  
Applies to: P03-US01 external table-caption projection

## Decision

An external table caption may enter the public compatibility view only when a
retained raw `caption_of` graph edge and compatible external page geometry
agree. The projector is deterministic, source-only, default off, additive, and
fail closed. It never synthesizes caption text, changes table cells, or deletes
raw IR evidence.

The rollout control is
`PARSER_LAYOUT_TABLE_CAPTIONS_ENABLED=false` by default. It requires shared IR
normalization. Setting it to `false` is the complete P03-US01 rollback and
restores the predecessor JSON and Markdown projection exactly.

## Promotion contract

A candidate is promoted only when all of the following hold:

1. The relationship target is a presented table with a retained public
   projection.
2. Caption text is a non-empty string.
3. At least one native, OCR, vector, embedded, or recovered source-evidence
   method supports the caption. Generated and derived-only candidates are
   rejected.
4. Caption and table boxes resolve to the same page coordinate system and unit.
5. Both boxes have positive finite area.
6. Horizontal overlap is at least 0.20, internal overlap is at most 0.20, and
   the external vertical gap is at most 72 points.

All usable same-page raw provenance boxes are transformed and unioned for the
caption. Retained element boxes are a fallback only when no usable raw
provenance box exists.

An accepted caption is one distinct `caption` item immediately before its
table. It retains source text, Markdown, bbox, source, confidence, and stable
public identity. The caption carries a scalar `caption_of`; the table carries
`caption_ids`, an additive caption list in `caption_of`, and a typed
relationship descriptor. Stable relationship IDs are SHA-256-derived from the
public caption and table IDs.

## Ambiguity and duplicates

Equivalent source occurrences use reciprocal intersection over the smaller box
at a threshold of 0.80. Bounded connected components, rather than greedy
representatives, make overlap chains deterministic and independent of source
collection order.

- Equivalent routes to one table project once; duplicate routes remain
  diagnostic evidence with a concern.
- Distinct externally grounded captions for one table remain separate, retain
  declared relationship order, and emit a multiple-caption concern.
- One physical caption component referenced by multiple tables remains
  evidence-only with a shared-caption concern, including small extractor
  jitter and conflicting OCR/native text at the same region.
- Dangling, shared, internal, empty, generated, non-text, malformed, distant,
  and unsupported candidates never enter primary output.

## Resource and security bounds

- At most 64 caption references are processed for one table.
- At most 128 same-normalized-text candidates are compared on one page.
- At most 512 total caption candidates are compared on one page.
- Overflow rejects the complete affected candidate set, retains raw evidence,
  and emits one bounded concern. Diagnostics contain counts, limits, page
  identity, and a normalized-text SHA-256 where applicable; they do not expose
  the raw caption text.
- Geometry and evidence indexes are built once per projection, and page
  presentation order is rebuilt once per changed page.

No external service, model call, network request, token, hosted cost, package,
or runtime download is introduced.

## Serialization and frontend policy

Schema version `1.0` remains unchanged and additive fields are preserved by the
existing extra-field contract. Canonical text and Markdown include an accepted
caption exactly once before the table. The frontend renders explicit escaped
caption items and preserves their full relationship evidence in normalized
complete-document JSON. It does not infer relationships or move caption text
into table markup.

Visual/chart captions, source notes, footnotes, text-run styling, and broader
reading-order policy remain owned by P03-US02 through P03-US05.
