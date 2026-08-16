# P02-US04 Completion Report

Status: Done  
Story: Reconcile native, font, and OCR candidates  
Points: 5  
Started: 2026-07-30  
Completed: 2026-07-30

## Definition of Ready

| Requirement | Result |
|---|---|
| Scope and non-scope explicit | Pass — deterministic evidence/geometry reconciliation only; no language-model completion or P02-US05/US06 cleanup/dedup rules |
| Points at most 5 | Pass — 5 |
| Dependencies Done | Pass — P02-US03 is Done with retained final-code metrics and independent review |
| Acceptance measurable | Pass — font/OCR wins, dependent-source rejection, one canonical overlap, and terminal low-margin conflict outcomes |
| Dedicated tests identified | Pass — ranking/overlap units, story integration, negative script/partial-overlap cases, contract/flag-off, fixture, regression, and performance gates |
| Fixtures available and authorized | Pass — approved immutable corpus plus deterministic font-repair, OCR, native, geometry, and mixed-script controls |
| API/schema impact documented | Pass — default-off behavioral selection with additive reason/alternative/concern evidence and compatible v1 flag-off projection |
| Feature flag identified | Pass — `parser.text_reconciliation.enabled` with shared-IR, font-recovery, and selective-OCR dependencies |
| Rollback defined | Pass — disable reconciliation to project the prior native text while retaining diagnostics |
| Quality/performance specified | Pass — exact target, zero canonical duplicates/semantic completions, 100% grounded selections/conflicts, and cumulative healthy p95 at most 10% |

Definition-of-Ready result: **10/10 Pass**. P02-US04 is the sole story in
progress.

## Implementation

The parser now builds bounded native, safe-font, and selective-OCR candidate
groups directly from retained shared-IR evidence. Candidate identity is bound
to the exact PDF, page, owner, span or font run, bbox, source evidence,
lineage, and upstream terminal state. Fabricated, dangling, replayed,
cross-page, contradictory, incomplete, or geometrically ambiguous provenance
fails closed before mutation.

The strict `1.0` / `text-reconciliation-v1` policy scores only attributable
source evidence. Healthy native text stays authoritative; complete safe-font
evidence is deterministic; OCR can win only with an exact upstream refusal,
complete crop/pass/token/cost evidence, supported script, reciprocal geometry,
confidence at least 0.90, and a margin of at least 0.10. Same-lineage engines
do not add votes. No language plausibility, model output, normalization repair,
or semantic completion has selection authority.

Every considered group ends as `selected`, `unchanged`, or `unresolved`.
Selections update one bounded owner range transactionally while retaining all
alternatives. Unresolved groups preserve prior primary bytes. Element,
evidence, `alternative_of` relationship, legacy diagnostic, concern, and
report surfaces carry one consistent decision. A source-bound complete
manifest authenticates re-entry by recomputing the full report from retained
evidence; coherent re-entry is byte-stable, while partial or forged
self-consistent markers are quarantined without changing source evidence.

Grouping, lineage indexing, application, serialization, and re-entry share
document-wide group/candidate/evidence/report/deadline bounds. The feature is
off by default and is invoked without a new pipeline keyword when disabled, so
the P02-US03 call shape and output remain exact.

## Acceptance result

1. Deterministic font evidence: **Pass — the two catastrophe prose runs already
   selected by safe font recovery remain authoritative with
   `deterministic_font_evidence`; the exact target sentence occurs once in
   projected, canonical text, and canonical Markdown output**.
2. Independent OCR selection: **Pass — complete high-confidence rendered-pixel
   controls win only when the exact native/font span is unsafe and refused;
   incomplete, padded-neighbor, mixed-script, low-confidence, or low-margin
   OCR remains unresolved**.
3. Source independence: **Pass — native/layout views of one PDF text layer and
   standard/sparse OCR views of one crop collapse to one lineage observation;
   duplicate engines and nodes add no votes**.
4. Canonical overlap: **Pass — retained metrics report zero canonical duplicate
   blocks, zero alternate leaks, and zero selection-surface disagreements**.
5. Conservative conflict handling: **Pass — all low-margin, owner-conflicting,
   partial-overlap, malformed, or unsupported cases preserve every bounded
   alternative and terminate unresolved without semantic repair**.

## Verification and metrics

The final focused story/adversarial/contract/regression/performance/retained
gate passed 117 tests. The complete Phase 0–2 story, contract, regression, and
performance gate passed 979 tests. The complete backend passed 1,056 tests
with 10 documented opt-in skips and one existing Starlette/httpx deprecation
warning. Compilation, dependency integrity, strict retained-artifact
validation, default-off parity, canonical parity, and real-corpus re-entry all
passed.

The retained final-code artifact covers 15 exact source hashes with two
warmups and ten measured samples. All 14 healthy controls remained
presentation-identical with no reconciliation groups. The real catastrophe
case produced 29 source-bound terminal groups: 2 already-primary prose runs
were unchanged, 24 owner-linked chart runs were unresolved, and 3 ownerless
runs were unresolved; no ownerless candidate was selected. Evidence, reason,
schema, and alternative coverage were each 100%, while canonical duplicates,
alternate leaks, surface disagreements, unretained decision evidence, and
semantic completions were all zero.

Healthy isolated reconciliation p50/p95/max overhead was
0.176132%/0.609935%/0.721712%. The cumulative conservative Phase 02 healthy
p95 ceiling is 3.093457%, below 10%; it is an arithmetic reference, not a
paired full-parser percentile. Maximum isolated peak-RSS increment was
19,038,208 bytes.

The approved corpus has no naturally unresolved production OCR-win fixture and
no reviewed typed registry for the historical false/duplicate OCR candidates.
Those claims are therefore covered by deterministic source-bound controls and
reported separately, not presented as real-corpus wins. The independent
code/security review and a separate independent metrics-runner/custody review
both approved the final snapshots with no material blocker. Complete evidence
is in
[P02-US04-verification.md](../evidence/P02-US04-verification.md).

## Definition of Done

| Requirement | Result |
|---|---|
| Implementation and acceptance complete | Pass — 5/5 criteria |
| Dedicated story tests pass | Pass — 117 focused tests |
| Phase 0–2 and impacted regressions pass | Pass — 979 combined gate and 1,056 full backend |
| API/schema compatibility passes | Pass — default-off exact P02-US03 call/output parity; additive flag-on diagnostics |
| Unrelated fixtures have no unexplained regression | Pass — 14/14 healthy controls and all canonical presentations unchanged |
| Quality/performance recorded | Pass — final-code 2-warmup × 10-sample artifact retained |
| Tracker/configuration documentation current | Pass |
| Feature flag and rollback verified | Pass — default off with validated shared-IR/audit/recovery/selective-OCR dependencies |
| Completion report and independent review complete | Pass — production/security and metrics/custody reviews approved |
| No concurrent next story | Pass — P02-US05 remained Proposed through closure |

Definition-of-Done result: **10/10 Pass**. P02-US04 is Done.
