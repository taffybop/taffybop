# Phase 02 Exit Verification Evidence

Date: 2026-07-30  
Status: Pass  
Phase: Text Integrity — 6/6 stories, 25/25 points

## Retained artifact

The frozen machine-readable result is
[P02-source-text-alignment-metrics.json](P02-source-text-alignment-metrics.json).

| Identity | Value |
|---|---|
| Artifact size | 439,414 bytes |
| Artifact SHA-256 | `6fdd74cb7adece95ae4a67cc98d1d02e3ca071f9166d4c8c26150768114dbacb` |
| Semantic payload size | 418,996 bytes |
| Semantic payload SHA-256 | `fcc2bf63c145347f8a7a40876dd60247e684e2d3616860b479f74c7d8240b558` |
| Protocol | 2 warmups + 10 measured samples per healthy case |
| Full-parser custody | 15 enabled + 15 predecessor workers; 15/15 pairs |
| Hosted requests / tokens / cost | 0 / 0 / $0 |

The artifact binds 67 exact run inputs, including every application Python
module, configuration, pipeline, production source-alignment service, accepted
policy, corpus registry and rights records, all 15 source PDFs, all 15 immutable
P00-US10 outputs, the core regression, and the focused contract, story,
adversarial, performance, and regression tests. Pre/post input and corpus
identities match. The retained-artifact test is deliberately excluded from that
set to avoid self-referential custody and instead freezes the completed artifact
by exact byte size and SHA-256.

## Exit acceptance

| Gate | Result |
|---|---|
| Component cases | Pass — 15/15 |
| Affected component targets | Pass — 5/5 |
| Enabled/predecessor full-parser pairs | Pass — 15/15 |
| Non-target selected cases | Pass — 0 |
| Non-target changed cases | Pass — 0 |
| Flag-off exact predecessor projections | Pass — 15/15 |
| Approved owner drift | Pass — 15/15 |
| Paired control canonical-text parity | Pass — all |
| Paired control Markdown parity | Pass — all |
| Paired control public-result parity | Pass — all |
| Finance zero-rewrite control | Pass — 0 selections, pages unchanged |

The enabled full-parser target screen passed catastrophe-recap plus all five
affected source-alignment cases:

| Case | Selected owners | Target |
|---|---:|---|
| catastrophe-recap | 0 | Existing exact catastrophe sentence remains present |
| clinical-study | 5 | Reviewed diacritics, word boundaries, quotation, and numeric minus |
| esg-metrics | 5 | Reviewed notes 3–7 and damaged word/symbol forms |
| postal-10k | 2 | Reviewed source-supported acronym/text owners |
| purchase-agreement | 1 | Reviewed opening/date boundary |
| settlement-agreement | 1 | Reviewed `Look-Back` form |

All other enabled cases selected zero owners. Every accepted mutation stayed
within the policy's approved owner, field, removal, and table-cell boundaries.

## Performance and resources

| Measure | Result |
|---|---:|
| Worst healthy case | `ny-timetable` |
| Worst healthy component p95 / max | 400.882292 / 400.882292 ms |
| Source-alignment additive p95 | 0.857318845% |
| Retained P02-US06 ceiling | 3.095326201% |
| Conservative cumulative Phase 02 ceiling | 3.952645047% |
| Phase ceiling | ≤ 10% — Pass |
| Maximum process high-water RSS increment | 0 bytes |

The cumulative value is an arithmetic ceiling over independently measured
components, not an observed paired full-parser percentile. With ten measured
observations, nearest-rank p95 is the observed maximum. The zero RSS increment
means that these measurements did not raise the process's existing lifetime
high-water mark; it does not assert zero allocation or zero memory use. The
artifact retains the validated distribution statistics and arithmetic, not the
ten raw timing observations, so those percentile inputs cannot be replayed
independently from the retained JSON.

## Compatibility, dependency, and rollback

- `PARSER_TEXT_INTEGRITY_SOURCE_ALIGNMENT_ENABLED` is off by default.
- The disabled path makes zero source-alignment calls and retains the exact
  completed P02-US06 projection.
- Setting the flag to `false` is the one-flag rollback.
- Accepted changes are source-bound and transactional; ambiguity, exhausted
  bounds, malformed evidence, report overflow, and deadline exhaustion fail
  closed without partial mutation.
- No package, OCR engine, language asset, model, hosted service, network
  dependency, or runtime download was added for phase-exit closure.

## Test gates

- Focused Phase 02 exit gate: **112 passed**.
- Frozen retained-artifact contract: **3 passed**.
- Complete backend: **1,351 passed, 10 documented opt-in skips, 1 existing
  warning in 69.22 seconds**.
- Node 22.18 frontend `npm run check`: **Pass — lint, typecheck, production
  build, 42 unit tests, and 1 bundle test**.

No Phase 03 story was started during exit closure. All eight Phase 03 stories
remain Proposed.

## Limitations

The phase-exit proof is deliberately limited to the accepted policy, named
reviewed source-text defects, approved owners, immutable 15-case native-PDF
corpus, and bounded source evidence. It does not claim language-model
completion, general spelling correction, arbitrary font repair, scanned-only or
Office-format parity, layout/table/chart completion, a paired full-parser
performance percentile, or zero memory consumption. Those later capabilities
remain governed by their Proposed Phase 03–08 stories and fixture gates.
