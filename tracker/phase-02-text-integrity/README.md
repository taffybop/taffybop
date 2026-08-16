# Phase 02 — Text Integrity

Status: Complete — 6/6 stories and 25/25 points Done; exit criteria Pass  
Outcome: Damaged native text is detected, safely repaired, selectively re-read,
or explicitly flagged with alternatives and provenance

## Entry criteria

- Phase 01 evidence and confidence contracts are complete.
- Font fixture policy and dependency/license decision are recorded.

## Exit criteria

- Malformed font maps are detected without rewriting healthy fonts.
- Safe identity-mapped text recovers deterministically.
- Unicode, combining marks, superscripts, semantic hyphens, quotation/currency
  symbols, and word boundaries survive without language-model completion.
- Unresolved spans, not whole healthy pages, escalate to OCR.
- Native/font/OCR candidates reconcile by evidence and geometry.
- False or duplicate OCR from charts, diagrams, forms, tables, photographs, and
  rendered page repairs is excluded from primary text while retained as
  attributable diagnostic evidence.
- Numeric cleanup and dedup preserve spatially distinct labels.

## Stories

1. [P02-US01](stories/P02-US01.md) — Detect malformed PDF font mappings
2. [P02-US02](stories/P02-US02.md) — Recover safe identity-mapped font text
3. [P02-US03](stories/P02-US03.md) — Escalate unresolved spans to selective OCR
4. [P02-US04](stories/P02-US04.md) — Reconcile native, font, and OCR candidates
5. [P02-US05](stories/P02-US05.md) — Make OCR token cleanup numeric-safe
6. [P02-US06](stories/P02-US06.md) — Preserve spatial repetition and short tokens

## Phase exit

The final source-bound alignment screen closed the reviewed word-boundary and
symbol targets on 2026-07-30. All 15 enabled/predecessor full-parser pairs
passed; the five affected component targets passed with 5 clinical, 5 ESG, 2
postal, 1 purchase-agreement, and 1 settlement-agreement selections. The
catastrophe exact target also passed, while non-target selection and page-change
counts remained zero.

The retained 2-warmup × 10-sample artifact is
[P02-source-text-alignment-metrics.json](evidence/P02-source-text-alignment-metrics.json),
SHA-256
`6fdd74cb7adece95ae4a67cc98d1d02e3ca071f9166d4c8c26150768114dbacb`.
See [phase-exit verification](evidence/P02-phase-exit-verification.md) and the
[completion report](reports/P02-phase-exit-completion.md).

`PARSER_TEXT_INTEGRITY_SOURCE_ALIGNMENT_ENABLED` remains off by default.
Setting it to `false` is the single-flag rollback to the exact completed
P02-US06 path. No Phase 03 story has started; all eight remain Proposed.
