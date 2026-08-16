# P04-US01 Source-Bound Recovery Amendment

Status: Draft; implementation and final independent review pending  
Date: 2026-08-04  
Parent policy: `p04-table-evidence-v1`  
Sidecar version: `1.1`  
Scope: P04-US01 only

## Decision

The accepted P04-US01 objective requires the reviewed postal `FERS` boundary
row and source-supported header ownership to remain inside the canonical
table. Production Docling does not expose the missing boundary row or a direct
reference for pdfplumber word observations. Treating recovered words as
Docling cells, or inventing `recovered-*` references, is prohibited.

Version `1.1` therefore adds one closed pdfplumber `table_word_set` source
variant while retaining the existing Docling source variant unchanged. The
word-set payload preserves the exact bounded text, top-left point bbox, source
font name, derived bold fact, structural target, role, and content custody
needed for deterministic replay. Its `raw_ref` is explicitly null rather than
fabricated.

Header recovery must retain both the candidate header words and the regular
comparison-body words. Bottom-row recovery must retain every emitted column's
words and the immutable original Docling grid. Replay independently verifies
word normalization, typography, row cadence, same-line geometry, table bounds,
column assignment, cell text/bbox, grid topology, representations, and every
identity/content/link. Any ambiguity or unavailable support preserves the
exact flag-off predecessor.

## Boundary

This is evidence for the already selected Docling candidate only. It does not
enable candidate collection, cross-engine reconciliation, ownership gating,
chart/form classification, continuation scoring, or multi-page merging.
`reconciliation`, `gate`, and `continuation` remain null. P04-US02, P04-US04,
P04-US03, and all Phase 05 stories remain Proposed.

## Required approval evidence

Acceptance requires backend, API/OpenAPI, serializer, frontend, adversarial,
resource/deadline, real-postal, default-off, and prior-phase tests on final
identities. Review must confirm zero invented references, exact source/evidence
reachability, bounded word support, exact rollback, and no later-story calls.
This amendment becomes accepted only with final P04-US01 production/security
and metrics/custody approval.
