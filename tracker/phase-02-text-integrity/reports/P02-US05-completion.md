# P02-US05 Completion Report

Status: Done  
Story: Make OCR token cleanup numeric-safe  
Points: 2  
Started: 2026-07-30  
Completed: 2026-07-30

## Definition of Ready

| Requirement | Result |
|---|---|
| Scope and non-scope explicit | Pass — contextual split-hex cleanup only; no spatial deduplication, recognition correction, chart structure, or token-evidence rewrite |
| Points at most 5 | Pass — 2 |
| Dependencies Done | Pass — P00-US03 and all previously executed Phase 02 stories are Done |
| Acceptance measurable | Pass — 12 decimal labels retained, no 48-digit join, exact approved digest joins, numeric non-target parity, and exact flag-off baseline |
| Dedicated tests identified | Pass — story units/integration, configuration/schema contract, retained/regression controls, and bounded performance/evidence gates |
| Fixtures available and authorized | Pass — immutable catastrophe baseline plus deterministic sequential-year, finance/legal numeric, and labeled digest controls |
| API/schema impact documented | Pass — no field change; default-off behavioral cleanup with unchanged raw token/bbox/confidence evidence |
| Feature flag identified | Pass — `parser.ocr.numeric_cleanup_v2.enabled` / `PARSER_OCR_NUMERIC_CLEANUP_V2_ENABLED`, default off with no dependencies |
| Rollback defined | Pass — disable v2 to invoke the untouched permissive legacy helper and exact prior call shapes |
| Quality/performance specified | Pass — zero decimal false joins, 12/12 observed labels, 100% approved digest joins, bounded cleanup/output/RSS, and cumulative healthy p95 at most 10% |

Definition-of-Ready result: **10/10 Pass**. P02-US05 is the sole story in
progress. The accepted context, length, token-preservation, bound,
compatibility, and rollback rules are in
[P02-numeric-cleanup-policy.md](../decisions/P02-numeric-cleanup-policy.md).

## Implementation

The permissive legacy split-hex helper remains unchanged and is still the
default-off path. The new bounded numeric-safe helper considers only one
complete maximal run of 2–64 uppercase ASCII `[A-F0-9]{2,}` fragments totaling
at most 128 characters. It requires at least one `A`–`F`, an immediately
adjacent ASCII MD5/SHA/hash/checksum/digest/fingerprint label, and an exact
standard digest length. Decimal-only, unlabeled, generic-ID, lowercase,
punctuated, distant-context, partial-length, or Unicode-confusable input is
left tokenized.

Cleanup inspects at most 65,536 normalized line characters and 4,096 tokens.
Any line, fragment-count, or candidate-size excess returns the normalized line
without a join; it never truncates, joins a prefix, or falls back to the
permissive helper. The implementation is linear and concatenates a candidate
once after eligibility passes.

The default-false argument is propagated through embedded PDF image, rendered
PDF region, direct raster, selective span, standard-pass, sparse-pass, and
pass-reconciliation paths. Disabled pipeline and adapter boundaries omit the
new keyword entirely. Only `OCRLine.text` changes when enabled; source
`OCRToken` text, bbox, crop bbox, confidence, pass, index, and word count remain
exact.

## Acceptance result

1. Twelve chart labels: **Pass — the retained `2015 2020 2025` ×4 target and
   the synthetic `2010`–`2021` control each remain twelve ordered tokens**.
2. No 48-digit year join: **Pass — zero enabled-path occurrences; the exact
   legacy fused bytes remain available only with the flag off**.
3. Genuine split-hex compatibility: **Pass — 35/35 explicit MD5/SHA and
   generic digest-label/standard-length controls join exactly**.
4. Numeric non-target safety: **Pass — 16/16 date, time, money, percentage,
   pagination, list, decimal-digest, and ambiguous identifier controls remain
   unchanged**.
5. Flag-off baseline: **Pass — exact retained catastrophe and sequential-year
   legacy joins, observer call shapes, OCR schemas, and US03/US04 interactions
   remain compatible**.

## Verification and metrics

The final focused story/contract/regression/independent-adversarial/performance/
retained-artifact gate passed 124 tests. The complete Phase 0–2 story,
contract, regression, and performance gate passed 1,103 tests. The complete
backend passed 1,180 tests with 10 documented opt-in skips and one existing
Starlette/httpx deprecation warning. Compilation and dependency integrity
passed.

The final artifact used two warmups and ten samples. It binds the exact retained
catastrophe output/source/bbox/word-count evidence, the finalized P02-US04
ceiling, the accepted policy, production/configuration/documentation code, and
all primary and independent tests with pre/post custody. It recorded 12/12
observed and 12/12 sequential year tokens, zero enabled-path decimal false
joins, 35/35 approved digest joins, 16/16 numeric controls, and 4/4
resource-bound fail-closed cases.

Healthy cleanup p50/p95/max was
0.132667/0.142625/0.142625 ms, equal to
0.000305% additive p95 against the P00-US10 reference. The cumulative
conservative Phase 02 p95 ceiling is 3.093762%, below 10%; it is an arithmetic
reference, not a paired full-parser percentile. Maximum isolated peak-RSS
increment was 98,304 bytes, semantic output was 15,671 bytes, and hosted model
requests/tokens/cost were all zero.

Independent review found and closed two blockers before approval: Unicode
labels whose full Unicode uppercasing folded into allowlisted ASCII, and a
metrics runner reading the finalized US04 ceiling from the wrong JSON level.
The reviewer approved the frozen production and final runner/custody snapshots
with no remaining code, security, API, schema, or call-shape blocker. Complete
evidence is in
[P02-US05-verification.md](../evidence/P02-US05-verification.md).

## Definition of Done

| Requirement | Result |
|---|---|
| Implementation and acceptance complete | Pass — 5/5 criteria |
| Dedicated story tests pass | Pass — 124 focused tests |
| Phase 0–2 and impacted regressions pass | Pass — 1,103 combined gate and 1,180 full backend |
| API/schema compatibility passes | Pass — unchanged public OCR diagnostics and exact default-off call/output path |
| Unrelated fixtures have no unexplained regression | Pass — US03/US04 interaction and OCR/image/shared-pipeline suites pass |
| Quality/performance recorded | Pass — final-code 2-warmup × 10-sample artifact retained |
| Tracker/configuration documentation current | Pass |
| Feature flag and rollback verified | Pass — independent default-off flag with untouched legacy helper |
| Completion report and independent review complete | Pass — production/security and metrics/custody reviews approved |
| No concurrent next story | Pass — P02-US06 remained Proposed through closure |

Definition-of-Done result: **10/10 Pass**. P02-US05 is Done.
