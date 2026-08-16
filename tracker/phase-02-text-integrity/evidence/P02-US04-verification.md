# P02-US04 Verification Evidence

Date: 2026-07-30  
Status: Pass

## Scope and compatibility

- Text reconciliation is enabled only by
  `PARSER_TEXT_RECONCILIATION_ENABLED=true`; it is off by default and requires
  shared IR, normalization, font audit, font recovery, and selective span OCR.
- Version `1.0` / `text-reconciliation-v1` uses only exact-source evidence,
  geometry, completeness, script support, mapping safety, confidence, and
  defined margins. It performs no language-model completion, autocorrection,
  transliteration, or Unicode compatibility repair.
- Every group ends `selected`, `unchanged`, or `unresolved`; unresolved groups
  preserve prior primary bytes and all alternatives.
- Flag-off invocation omits the reconciliation keyword and remains
  byte-equivalent to the finalized P02-US03 legacy, IR, and canonical path.
- Flag-on decisions are additive and attributable across element, evidence,
  `alternative_of` relationship, legacy diagnostic, concern, and report
  surfaces.

## Acceptance coverage

1. The two safe-font catastrophe prose runs remain authoritative and the exact
   target sentence occurs once in projected values, canonical text, and
   canonical Markdown.
2. Complete, high-confidence, source-independent OCR controls select only
   after exact upstream refusal; malformed, partial, neighbor-touching,
   low-confidence, mixed-script, or low-margin controls remain unresolved.
3. Multiple engines reading one PDF text layer or one pixel crop count as one
   lineage observation and cannot manufacture a margin.
4. Canonical output contains zero duplicate block identities and zero
   alternate contributions; every retained selection surface agrees.
5. Conflicts retain every bounded alternative and a reasoned terminal concern
   without semantic completion.

## Independent security and correctness review

The refreshed independent review approved the final production snapshot with
no residual blocker. It verified:

- strict PDF/page/owner/span/run/bbox/source-evidence identity;
- actual retained evidence rather than fabricated native or recovered IDs;
- exact audit, refusal, crop, affine, token, pass, attempt, cost, and
  relationship reconciliation;
- reciprocal geometry, owner ambiguity, replacement-range conflicts, and
  padded-neighbor refusal;
- same-lineage duplicate collapse and deterministic terminal ordering;
- shared aggregate group/candidate/evidence/report/deadline bounds;
- transactional failure and quarantine of partial or forged reconciliation
  state;
- full-report recomputation from retained evidence, including rejection of a
  forged self-hashed manifest; and
- byte-stable authenticated re-entry for both OCR controls and the real
  29-group catastrophe IR.

The separate metrics-runner review also approved the retained measurement
snapshot. It pinned the exact 2 prose, 24 chart, and 3 ownerless run sets,
owners, items, original/recovered candidate text, decision/evidence IDs,
statuses, and selection state; included reconciliation, IR, presentation, and
runner code in pre/post custody; rejected duplicate decisions; and required
15 exact re-entry cases plus the one authenticated-manifest catastrophe case.

## Corpus and performance evidence

The retained runner matched all 15 source SHA-256 identities to immutable
Phase 0 evidence and used two warmups plus ten measured samples. Audit,
recovery, selective routing, and source-IR preparation were outside the
isolated reconciliation timing. Actual corpus observations and deterministic
synthetic or test-only upstream controls are labeled separately.

| Measure | Result |
|---|---:|
| Exact source bindings / flag-off parity / flag-on round-trip parity | 15 / 15 / 15 |
| Healthy controls with unchanged canonical presentation | 14/14 |
| Catastrophe recovery / terminal groups | 29 / 29 |
| Catastrophe unchanged prose runs | 2 |
| Owner-linked unresolved chart runs | 24 |
| Ownerless unresolved / selected runs | 3 / 0 |
| Exact re-entry cases / authenticated-manifest re-entry cases | 15 / 1 |
| Evidence / reason / schema / alternative coverage | 100% / 100% / 100% / 100% |
| Canonical duplicates / alternate leaks / surface disagreements | 0 / 0 / 0 |
| Unretained decision evidence / semantic completions | 0 / 0 |
| Healthy reconciliation p50 / p95 / max overhead | 0.176132% / 0.609935% / 0.721712% |
| Conservative cumulative Phase 02 p95 ceiling | 3.093457% |
| Maximum isolated peak-RSS increment | 19,038,208 bytes |

The cumulative ceiling is an arithmetic reference across independently
measured components, not a paired full-parser percentile.

The approved corpus has no naturally unresolved production OCR-win fixture and
no reviewed typed registry for the historical false/duplicate OCR candidates.
The retained report states both limitations. Source-bound deterministic
controls cover those policy branches without being promoted to real-corpus
results.

Machine-readable inputs, decisions, re-entry, presentation, custody, timing,
RSS, environment, and source-binding evidence is retained in
[P02-US04-text-reconciliation-metrics.json](P02-US04-text-reconciliation-metrics.json),
SHA-256
`e877a82921b16a071afaade99d4d72fdf6ebfc9e4bb49260bb9c7c08205c1479`.

## Test gates

- Final focused story, adversarial, contract, regression, performance, and
  retained-artifact gate: **117 passed**.
- Complete Phase 0–2 story, contract, regression, and performance gate:
  **979 passed**.
- Complete backend suite: **1,056 passed, 10 documented opt-in skips**, and one
  existing Starlette/httpx deprecation warning.
- Python compilation: **Pass**.
- Dependency integrity: **Pass**; `pip check` reports no broken requirements.
- Retained JSON parsing, custody, and strict artifact assertions: **Pass**.
- Independent final production/security review: **Pass**.
- Independent final metrics/custody review: **Pass**.

The 10 skips are the existing real image-model, Docling/finance sample, and
shared-analysis integration gates, each requiring its documented opt-in
environment variable. No P02-US04 criterion depends on a skipped test.

## Dependency and rollback

P02-US03 is Done. No new Python package, hosted service, model, network
dependency, or runtime download was added.

Set `PARSER_TEXT_RECONCILIATION_ENABLED=false` to bypass reconciliation while
retaining P02-US01–US03 audit, recovery, and OCR diagnostics. The pipeline then
uses the exact prior call shape and P02-US03 projection/canonical behavior.
