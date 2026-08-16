# P02-US06 Completion Report

Status: Done  
Story: Preserve spatial repetition and short tokens  
Points: 3  
Started: 2026-07-30  
Completed: 2026-07-30

## Definition of Ready

| Requirement | Result |
|---|---|
| Scope and non-scope explicit | Pass — overlap-aware occurrence retention and chart/diagram-grounded short alternatives only; no OCR correction, `iH`-to-`1H` substitution, legend association, or chart interpretation |
| Points at most 5 | Pass — 3 |
| Dependencies Done | Pass — P02-US04 evidence reconciliation and P02-US05 numeric-safe cleanup are Done |
| Acceptance measurable | Pass — 12/12 distinct year bboxes addressable, one selected representative per overlapping equivalent cluster with loser diagnostics, exact short hypotheses retained with bbox/confidence, distant repeats preserved, and zero unsupported short canonical noise |
| Dedicated tests identified | Pass — story integration, occurrence/schema contract, retained/regression/adversarial controls, default-off parity, output-size, resource-bound, and performance evidence gates |
| Fixtures available and authorized | Pass — immutable catastrophe baseline with twelve source year bboxes and exact rejected `iH` evidence, plus deterministic overlapping-pass, distant-repeat, chart/diagram, photo, malformed-geometry, and bound controls |
| API/schema impact documented | Pass — default-off additive `ocr_token_occurrences` and `ocr_occurrence_summary`; occurrence evidence is presentation-inert and existing canonical fields remain authoritative |
| Feature flag identified | Pass — `parser.ocr.spatial_token_preservation.enabled` / `PARSER_OCR_SPATIAL_TOKEN_PRESERVATION_ENABLED`, default off and dependent on numeric cleanup v2 |
| Rollback defined | Pass — disable spatial preservation to omit its keyword and additive keys and restore the exact completed P02-US05 projection/call shapes |
| Quality/performance specified | Pass — 12/12 addressable positions, zero selected overlapping duplicates, grounded short alternatives with zero canonical noise, bounded JSON/RSS/latency, and cumulative healthy p95 at most 10% |

Definition-of-Ready result: **10/10 Pass**. P02-US06 was the sole story in
progress during implementation. Its accepted identity, equivalence, geometry, selection,
short-alternative, resource, compatibility, and rollback rules are in
[P02-spatial-token-preservation-policy.md](../decisions/P02-spatial-token-preservation-policy.md).

## Implementation

The new bounded spatial-token service projects OCR line/token evidence into
stable SHA-256 document/page/owner/geometry occurrence IDs. Exact text is
compared only after NFC and whitespace normalization. Equivalent candidates
collapse only when reciprocal overlap is at least 0.80; distant equal text
remains distinct. Inclusive overlap and owner-containment thresholds use a
deterministic binary-float tolerance.

Rejected low-confidence one-to-three-character ASCII alphanumeric hypotheses
are retained only for chart/diagram content regions when raw text, token
confidence, confidence floor, rejection reason, and at least 0.95 owner
containment all agree. This path never changes `iH` to `1H`, never selects a
quality-rejected candidate over an accepted one, and never contributes short
alternatives to canonical presentation.

Occurrence count, source-token count, short-alternative count, token text, and
serialized JSON are bounded. Invalid geometry/units and overflow fail closed.
The optional flag is propagated through embedded-image, rendered-region,
direct-raster, and selective-span adapters. Disabled call shapes and outputs
remain exact.

## Acceptance result

1. Twelve positions: **Pass — 12/12 exact year text/bbox/confidence records
   have distinct IDs and selected-primary state**.
2. Overlapping equivalents: **Pass — one selected winner, one attributable
   diagnostic, and zero duplicate primary occurrences**.
3. Short hypotheses: **Pass — exact retained `iH` plus two grounded synthetic
   alternatives retain bbox/confidence and remain non-primary**.
4. Distant repetition: **Pass — two equal line values and four selected tokens
   remain spatially distinct**.
5. Canonical safety: **Pass — zero unsupported short canonical tokens and zero
   promotions across four negative classes**.

## Verification and metrics

The final focused gate passed 56 tests. The complete Phase 0–2 story, contract,
regression, and performance gate passed 1,159 tests. The complete backend
passed 1,236 tests with 10 documented opt-in skips and one existing
Starlette/httpx deprecation warning. Compilation and dependency integrity
passed.

The final artifact used two warmups and ten measured samples and binds the
accepted policy, exact catastrophe source/output and twelve-year/`iH` records,
the retained P02-US05 ceiling, production/configuration/documentation, runner,
and all primary tests. It recorded a healthy p95 of 0.731292 ms, 0.001564%
additive overhead, and a cumulative conservative Phase 02 ceiling of
3.095326%. The target adds 6,453 bytes, maximum isolated peak-RSS increment is
1,032,192 bytes, semantic output is 23,613 bytes, and hosted requests, tokens,
and cost are zero.

Both independent reviewers approved the final snapshot after all production,
boundary, resource, custody, and runner findings were fixed and retested.
Complete evidence is in
[P02-US06-verification.md](../evidence/P02-US06-verification.md).

## Definition of Done

| Requirement | Result |
|---|---|
| Implementation and acceptance complete | Pass — 5/5 criteria |
| Dedicated story tests pass | Pass — 56 focused tests |
| Phase 0–2 and impacted regressions pass | Pass — 1,159 combined gate and 1,236 full backend |
| API/schema compatibility passes | Pass — additive presentation-inert fields and exact disabled call/output path |
| Unrelated fixtures have no unexplained regression | Pass — US03/US04/US05 and OCR/image/shared-pipeline suites pass |
| Quality/performance recorded | Pass — final-code 2-warmup × 10-sample artifact retained |
| Tracker/configuration documentation current | Pass |
| Feature flag and rollback verified | Pass — default off, numeric-v2 dependency enforced |
| Completion report and independent review complete | Pass — production/security and metrics/custody reviewers approved |
| No concurrent next story | Pass — no Phase 03 story started; Phase 02 exit validation follows |

Definition-of-Done result: **10/10 Pass**. P02-US06 is Done. At this story
checkpoint, all Phase 02 stories were Done and the separate reviewed
word-boundary/symbol exit gate was still pending. That gate subsequently passed;
see [P02-phase-exit-verification.md](../evidence/P02-phase-exit-verification.md).
