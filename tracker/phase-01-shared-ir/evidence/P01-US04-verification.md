# P01-US04 Verification Evidence

Date: 2026-07-29  
Status: Pass

## Scope and compatibility

- The backend remains authoritative for canonical presentation contract `1.0`
  under policy `canonical-presentation-v1`.
- The frontend validates a present contract strictly before API results enter
  workspace state, then renders, copies, and downloads the stored document/page
  views without reconstructing document meaning.
- An absent `canonical_presentation` alone selects the unchanged legacy
  `item.md`, then scalar-value fallback. A present malformed or unsupported
  contract fails closed and never falls through to legacy content.
- Public endpoint, legacy schema, and feature-flag rollback remain unchanged.

## Acceptance coverage

The supported-Node batch gate derives fresh `exclude_none=True` canonical
contracts from all 15 immutable Phase 0 cases and evaluates 33 payloads in one
process: 15 canonical, 15 flag-off legacy, one unknown-additive legacy, one
malformed-present, and one unsupported-version payload.

For every canonical document, the frontend:

- preserves the input and complete serialized JSON;
- returns the stored full-document Markdown byte for byte;
- returns every stored page Markdown view byte for byte;
- returns document/page semantic text in canonical order;
- retains all raw pages, metadata, processing data, warnings, future evidence,
  and the canonical contract exactly once in normalized JSON;
- resolves canonical pages by physical page identity rather than array
  position.

For every flag-off document, the frontend reproduces the frozen Phase 0
Markdown. Unknown additive item types retain their evidence and use documented
`md`-then-scalar fallback. Malformed-present and unsupported contracts fail
across reader, page lookup, document/page serialization, and normalization.

The workspace uses one validated canonical page for availability, display,
source, copy, and download. Only canonical `full.block_ids` render; omitted
blocks and legacy OCR/HTML cannot leak into the canonical view. Block text is
rendered as React text with preserved whitespace, not injected HTML.

## Differential validation

Independent review compared the TypeScript validator with the authoritative
Python model across all 15 real contracts and 239 coherent adversarial
field/type/reference/omission/view mutations. The final result was Pass with no
remaining blocker.

Review found and regression-pinned two edge cases:

1. relational omissions must reject an empty suppressor ID; and
2. outer-whitespace validation must follow Python `str.strip()` semantics,
   including stripping U+0085 while retaining U+FEFF.

After those corrections, every applicable mutation produced the same
accept/reject result in Python and TypeScript. Input immutability,
present-malformed fail-closed behavior, public/canonical page mismatch
rejection, exact stored views, JSON preservation, and absent-only fallback all
passed.

## Quality and performance

Measurements ran on macOS ARM64 with Node 24.18.0 after 20 full-corpus warmups
and 200 measured passes. Each path contains 3,000 individual observations;
percentiles use nearest rank.

| Measure | Individual p50 / p95 / max | Corpus p50 / p95 / max |
|---|---:|---:|
| Canonical Markdown serialization | 0.079791 / 0.409958 / 1.955292 ms | 1.856667 / 2.519374 / 3.525708 ms |
| Canonical normalization | 0.085208 / 0.443750 / 1.303083 ms | 2.041541 / 2.269792 / 4.101750 ms |

| Output/resource measure | Result |
|---|---:|
| Canonical contract, compact | 1,274,785 bytes |
| Canonical payload, compact | 3,833,763 bytes |
| Normalized canonical JSON, compact / pretty | 5,291,179 / 9,688,149 bytes |
| Normalized legacy JSON, compact / pretty | 4,148,192 / 8,275,794 bytes |
| Canonical normalization delta, compact / pretty | +27.5539% / +17.0661% |
| Controlled production bundle delta | +32,603 bytes / +0.6811% |
| Client / server bundle delta | +11,839 / +20,764 bytes |
| New canonical social asset | 689,676 bytes |
| Final production build tree | 5,504,531 bytes |

The controlled code-bundle comparison excludes the separately reported static
social asset. Adding only the larger new frontend-path p95 to the prior phase
total avoids double-counting:

`654.612 + 0.443750 = 655.055750 ms`

That is **1.402480%** of the Phase 0 parse p95 of 46,706.960 ms, below the 5%
Phase 1 ceiling.

## Test gates

- Cross-language P01-US04 parity on Node 24.18.0: 49 passed.
- Cross-language parity plus retained Phase 0 projection: 50 passed.
- Complete Phase 0–1 story/regression/contract gate: 536 passed.
- Frontend on Node 22.18.0: ESLint, TypeScript, five-stage production build,
  42/42 unit tests, and 1/1 built-output test passed.
- Complete backend: 804 passed, 10 documented opt-in integration/model skips,
  and one existing Starlette/httpx deprecation warning.
- Python compilation: Pass.
- Dependency integrity: Pass; `pip check` reports no broken requirements.
- Independent core differential review: Pass, 239 mutations and 15 real
  contracts, no blocker.
- Independent UI/API review: Pass, no blocker.

The in-app visual smoke could not run because no browser backend was available.
This does not replace or weaken the passing production build, source-level UI
tests, API-state tests, and independent UI review; the unavailable runtime is
recorded rather than reported as a visual pass.

## Source and hosting evidence

The exact validated frontend source is committed locally at
`07e035c8828d3976d35ec54a230a194f7d2cb48a`. The worktree is clean. Ignored
local environment and signed benchmark files were not staged.

The generated 1200×630 social card is `public/og-v2.png`, 689,676 bytes, SHA-256
`27076b56af5c85e7ade30e18f0f73726e7c77d9ca39842b40e736ed3782eb62e`.

Production publication was attempted through the required Sites workflow, but
the service returned `sites_access_disabled`: Sites is not enabled for this
workspace. No site project or source remote was created, so there was no safe
project ID, push target, saved version, or deployment to invent. Local
`.env.local` values were not copied. This external hosting limitation is not a
P01-US04 acceptance criterion and does not affect serializer parity.

## Security and rollback

Present canonical contracts are validated before reaching React state. Strict
field, type, reference, omission, scope, uniqueness, and stored-view checks
prevent mixed canonical/legacy rendering. React text rendering prevents raw
canonical Markdown or OCR from executing as HTML.

Set `PARSER_CANONICAL_SERIALIZATION_ENABLED=false` on the backend. The
canonical field is then absent and the documented legacy frontend path remains
available without an endpoint or schema downgrade.
