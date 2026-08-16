# P01-US03 Verification Evidence

Date: 2026-07-29  
Status: Pass

## Scope and compatibility

- Canonical presentation contract: `1.0`,
  policy `canonical-presentation-v1`.
- Feature flag: `PARSER_CANONICAL_SERIALIZATION_ENABLED`, default `false`.
- Prerequisites: `PARSER_SHARED_IR_NORMALIZATION_ENABLED=true` and
  `PARSER_SHARED_IR_ENABLED=true`; invalid partial enablement fails settings
  validation.
- Public endpoint and legacy schema remain `POST /v1/parse` and `1.0`.
- Flag off: `canonical_presentation` is absent and the legacy JSON/Markdown
  path is unchanged.
- Flag on: one strict additive contract is built once from `DocumentIR`; the
  backend Markdown serializer returns the stored full-document view.

## Acceptance coverage

The canonical builder emits ordered page blocks plus document/page `full`,
`body`, `header`, and `footer` views. Across the frozen 15-case corpus it
produced 291 blocks: 274 included and 17 explicitly omitted. The included
blocks contain 3,009 contributing element IDs and all 3,009 are unique.

Coverage includes:

- stable anchor order and immutable alternative ranking, including chains,
  cycles, omitted targets, duplicate assertions, and shared claims;
- strict, non-coercing presentation models and strict stored-contract
  validation;
- caption precedence, allowed subordinate OCR, source notes, footnotes, and
  evidence-only assertions;
- recursive list, table, form, key-value, header, and footer reconstruction
  from only the descendants actually claimed by the block;
- nested visual precedence under every structured owner, with bridge identity
  and no flattened-value fallback;
- header/footer scope isolation, layoutless fragment reconstruction, and
  deterministic rejection of authoritative atomic furniture that also owns a
  visual without segmented provenance;
- positional table-cell identity, span-capable HTML retention, and contextual
  rejection of malformed spans or span-bearing non-HTML fallback;
- complete block-level audit of every represented non-`READING_BEFORE`
  relationship assertion; reading order remains authoritative from the page
  presentation anchors;
- explicit `unsupported_primary_ocr`, `empty_visual`, and
  `overlapping_visual_table` omissions.

All rendered nonempty views end in exactly one newline. Repeated builds,
strict JSON round trips, stored serialization, and randomized mixed-role graphs
are deterministic.

## Reviewed corpus differences

The immutable P00-US10 `20260729-03` corpus remains the legacy authority.
P01-US03 derives the IR and canonical contract at test time from its frozen v1
JSON because Phase 0 did not retain raw Docling graphs or serialized IR.

The reviewed manifest pins every complete IR, canonical contract,
Markdown/text artifact, block count, ordered omission, and disposition:
[P01-US03-reviewed-differences.json](P01-US03-reviewed-differences.json).
There are zero unreviewed differences.

- 10 reviewed flag-only changes: catastrophe-recap, clean-energy,
  clinical-study, component-datasheet, egov-survey, esg-metrics,
  health-report, insurance-acord, manufacturing-report, and uber-earnings.
  These are the intended canonical ownership, OCR/alternate suppression,
  overlap suppression, and explicit header/footer inclusion outcomes.
- 5 byte-stable positives: finance-10k, ny-timetable, postal-10k,
  purchase-agreement, and settlement-agreement.
- The catastrophe source note `Data: Aon Catastrophe Insight` is absent from
  upstream extraction and is not fabricated here. Its source recovery and
  ownership remain assigned to P03-US03.

The final concatenated compact canonical-contract payload, in frozen
`selected_case_ids` order, is 1,274,785 bytes with SHA-256
`90c82e8449dfa9509232f60f4e799077c4a3e223e195bc21fae67be87ead7a5e`.

## Real pipeline integration

The current installed extraction pipeline parsed
`benchmark-expertmodeldata/catastrophe-recap.pdf` twice with all three Phase 1
flags enabled:

| Measure | Result |
|---|---:|
| Parse durations | 9.824 s; 9.924 s |
| Pages / warnings | 1 / 0 |
| Blocks | 6 total; 5 included; 1 omitted |
| Contributing element IDs | 40/40 unique |
| Retained relationship assertions | 61 |
| Strict JSON round trip | Equal |
| Stored serializer / canonical full Markdown | Byte-equal |
| Canonical contract SHA-256 | `07e119c55d31f6abc3877a0867dbe088e88750d9b3af1cac0c6aec5631b3c373` both runs |
| Markdown SHA-256 | `15194c3cfc7fa4d0313f9e42c805d5549e7ee61f0d910a88fca9466c550da495` both runs |

The direct-image shared pipeline is covered by
`test_direct_image_stream_builds_one_flagged_canonical_presentation`: its
table, chart, and diagram blocks use the same contract, contribution IDs are
unique, and the stored serializer is byte-equal.

## Quality and performance

Measurements ran in a fresh process on macOS ARM64 with Python 3.13.5.
Twenty full-corpus warmups preceded 200 measured full-corpus passes. Each pass
processed all 15 cases in frozen order, yielding 3,000 individual observations
per path. Percentiles use the nearest-rank method.

| Measure | Individual p50 / p95 / max | Corpus p50 / p95 / max |
|---|---:|---:|
| Existing IR to canonical contract | 5.149 / 86.062 / 314.818 ms | 250.885 / 278.731 / 480.815 ms |
| Stored contract to Markdown | 0.458 / 1.858 / 47.040 ms | 10.227 / 18.692 / 55.171 ms |
| Legacy v1 to IR to canonical contract | 11.328 / 172.988 / 357.776 ms | 469.380 / 557.435 / 630.481 ms |

| Resource/output measure | Result |
|---|---:|
| Benchmark-process maximum RSS | 139.578 MiB |
| Frozen legacy Markdown | 116,260 bytes |
| Canonical Markdown | 111,382 bytes |
| Canonical semantic text | 56,801 bytes |
| Canonical contracts | 1,274,785 bytes |
| Phase 0 parse p95 | 46,706.960 ms |
| Canonical-build p95 / Phase 0 parse p95 | 0.1843% |
| Conservative P01-US01 + US02 + US03 p95 | 654.612 ms |
| Conservative cumulative Phase 1 overhead | 1.4015% |

The cumulative calculation adds the P01-US01 retained-corpus p95
(488.363 ms), the larger P01-US02 depth-stress p95 (80.187 ms), and this
story's individual canonical-build p95 (86.062 ms). It remains below the 5%
Phase 1 ceiling.

## Test gates

- Focused P01-US03 story and canonical regression: 209 passed.
- Reviewed-difference manifest regression: 18 passed.
- Combined focused and reviewed gate: 227 passed.
- Complete backend: 755 passed, 10 documented opt-in integration/model skips,
  and one existing Starlette/httpx deprecation warning.
- Python compilation: pass.
- Dependency integrity: pass; `pip check` reports no broken requirements.
- Frontend on Node 22.18.0 / npm 10.9.3: TypeScript pass, ESLint pass,
  production build pass, 27/27 unit tests and 1/1 built-output test pass.

## Independent review

Pass with no remaining production blockers. The final reviewer independently
replayed the complete focused suite and frozen corpus, a 72-case nested-visual
matrix, a 96-case nested-attachment matrix, 300 randomized mixed-role and
mixed-relationship graphs, and an earlier 500-case alternative-SCC sweep.
Every run preserved determinism, strict revalidation, unique claims, and
complete non-ordering relationship audit coverage.

## Security and rollback

Canonical construction is local and deterministic. It does not dereference
links, fetch relationship targets, or copy unresolved raw reference values into
output. The additive contract retains only normalized evidence already in
scope.

Set `PARSER_CANONICAL_SERIALIZATION_ENABLED=false` to remove the additive
contract and restore the unchanged legacy serializer. Its prerequisite flags
can remain enabled for the internal IR, or the complete shared-IR path can be
disabled independently.
