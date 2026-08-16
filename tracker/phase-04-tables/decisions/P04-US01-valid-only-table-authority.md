# P04-US01 Valid-Only Table Authority Clarification

Status: Draft; implementation and independent review pending  
Date: 2026-08-04  
Parent policy: `p04-table-evidence-v1`  
Scope: P04-US01 only

## Clarification

The parent policy's statement that marked `cells` are authoritative applies
only when `table_evidence.status` is exactly `valid` and the complete closed
sidecar, grid, representations, and custody hashes validate. A marker with
`status` equal to `unresolved` or `structural_failure` is diagnostic evidence,
not an authoritative semantic grid.

For either non-valid status, backend replay and frontend rendering retain or
fall back to the escaped predecessor table projection. They must not infer a
replacement grid from partial cells, rows, HTML, Markdown, CSV, geometry,
repetition, or alternatives. Unknown status values or malformed marked data
fail the affected overlay closed and also use the predecessor projection.

The predecessor snapshot is the complete page-local table projection captured
immediately before the first P04-US01 mutation of that candidate. A well-formed
`unresolved` or `structural_failure` sidecar may remain publicly visible as a
bounded diagnostic while that snapshot stays authoritative. An unknown,
malformed, oversized, inconsistent, or custody-invalid sidecar is not a valid
diagnostic contract: rollback removes the marker and restores the snapshot
without exposing partial Phase 04 data.

This clarification resolves no ambiguous source evidence and authorizes no
cross-engine selection, candidate ownership decision, or continued-table
merge. Those remain P04-US02, P04-US04, and P04-US03 responsibilities in the
approved dependency order. Default-off byte identity, transactional rollback,
the public schema, and every parent-policy resource, deadline, custody,
security, and compatibility limit remain unchanged.

## Required verification

Completion evidence must demonstrate all of the following:

- a valid, fully verified marker renders and serializes only its canonical
  semantic grid;
- unresolved, structural-failure, unknown-status, malformed, and hash-mismatch
  markers preserve the exact predecessor projection;
- well-formed non-valid diagnostics remain bounded and closed, while malformed
  or custody-invalid overlays are removed in full;
- no non-valid marker becomes input to text replacement or later-story logic;
- no previously computed text-run overlay can replace authoritative cell text
  at backend replay or frontend render time; and
- backend and frontend use the same valid-only authority rule.

This draft becomes accepted only after independent production/security and
compatibility/custody review on final P04-US01 code and tests.
