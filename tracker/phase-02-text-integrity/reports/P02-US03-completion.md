# P02-US03 Completion Report

Status: Done  
Story: Escalate unresolved spans to selective OCR  
Points: 5  
Started: 2026-07-30  
Completed: 2026-07-30

## Definition of Ready

| Requirement | Result |
|---|---|
| Scope and non-scope explicit | Pass — refused span routing/evidence only; no candidate selection, whole-page VLM, or new OCR engine |
| Points at most 5 | Pass — 5 |
| Dependencies Done | Pass — P02-US02 is Done with completion, rollback, final-code metrics, and independent review |
| Acceptance measurable | Pass — terminal outcome per unresolved span, zero healthy-neighbor renders, complete crop/pass/cost evidence, bounded soft failures, and cross-input contract parity |
| Dedicated tests identified | Pass — crop/transform/budget units, story integration, negative, contract/flag-off, fixture, regression, and performance gates |
| Fixtures available and authorized | Pass — approved corpus plus deterministic P02 unsafe-font variants and synthetic raster/geometry controls |
| API/schema impact documented | Pass — default-off additive diagnostics only; primary/canonical text unchanged until P02-US04 |
| Feature flag identified | Pass — `parser.text_integrity.selective_span_ocr.enabled` with shared-IR/audit/recovery dependencies |
| Rollback defined | Pass — disable selective OCR while retaining audit, recovery, and native evidence |
| Quality/performance specified | Pass — 100% terminal routing, zero healthy-neighbor renders, complete evidence, fixed resource bounds, and cumulative healthy p95 at most 10% |

Definition-of-Ready result: **10/10 Pass**. P02-US03 is the sole story in
progress. The accepted engine, language, license, crop, pixel, area, deadline,
evidence, compatibility, and failure policy is
[P02-selective-span-ocr-policy.md](../decisions/P02-selective-span-ocr-policy.md).

## Implementation

The parser now routes only exact-PDF-bound audited runs whose font recovery
ended in an explicit, semantically consistent refusal. Contradictory
recovered/refused records, conflicting refusals, object-identity mismatches,
and refusal page-scope mismatches fail closed before any render.

Each authorized source bbox receives a three-point clipped crop at the accepted
5 px/pt (360 DPI) target. Exact quantized PDFium dimensions are checked before
allocation, and the realized crop, affine transform, DPI, pixel count, area,
deadline, Tesseract version/language, pass status, candidate, token, confidence,
and cost are retained. Crop/document pixel, target, area, output, IPC, and time
bounds fail softly without replacing native evidence.

The shared OCR contract now carries typed line/token/pass evidence for direct
images, raster pages, and rendered PDF regions. Strict raster geometry and
exact affine behavior are private to selective requests, preserving flag-off
legacy behavior. Selective candidates are attached as unselected,
presentation-inert alternatives; canonical JSON, text, and Markdown remain
unchanged until P02-US04.

## Acceptance result

1. Bounded unresolved-span rendering: **Pass — all 4 audited catastrophe
   target runs produced 4 bounded real PDFium/Tesseract crops; no broad page
   render occurred**.
2. Healthy neighbors excluded: **Pass — 25 same-page healthy spans and all 14
   healthy corpus controls produced zero selective renders**.
3. Complete evidence and cost: **Pass — 4/4 real candidates and 4/4 tokens
   retained unique IDs, bboxes, exact transforms, DPI, pixels, pass status,
   confidence, engine/language, elapsed time, and cost**.
4. Bounded soft failures: **Pass — pre-allocation, realized area/pixel,
   deadline, timeout, unavailable engine, malformed output, transform, IPC, and
   provenance failures are terminal concerns that retain native evidence**.
5. Shared OCR evidence contract: **Pass — direct raster and rendered-PDF OCR
   share typed line/token/pass evidence while legacy projections remain
   compatible**.

## Verification and metrics

The final focused story/contract/regression/performance gate passed 62 tests.
The complete Phase 0–2 story, contract, regression, and performance gate passed
862 tests. The complete backend passed 939 tests with 10 documented opt-in
skips and one existing Starlette/httpx deprecation warning. Compilation,
dependency integrity, retained JSON validation, and flag-off/canonical parity
passed.

The final-code artifact covers 15 exact source hashes with 2 warmups and 10
samples per scenario. Its catastrophe source is the actual corpus PDF with a
deterministic test-only recovery-refusal variant; it is not a naturally
unresolved production report. It retained 100% terminal coverage, 14/14
render-free healthy controls, zero renders for 25 healthy target-page
neighbors, and one real 4-crop PDFium/Tesseract series with 4 candidates and 4
tokens. Real isolated OCR p50/p95/max was
1758.404/2140.842/2140.842 ms; healthy selective-planning p50/p95/max was
0.085/2.842/2.946 ms. The conservative audit + recovery + selective healthy
p95 ceiling is 2.483522%, below 10%; it is not a paired full-parser percentile.

The independent security/correctness re-review approved the final code with no
blocking or major findings. Complete evidence is in
[P02-US03-verification.md](../evidence/P02-US03-verification.md).

## Definition of Done

| Requirement | Result |
|---|---|
| Implementation and acceptance complete | Pass — 5/5 criteria |
| Dedicated story tests pass | Pass — 62 focused tests |
| Phase 0–2 and impacted regressions pass | Pass — 862 combined gate and 939 full backend |
| API/schema compatibility passes | Pass — default-off, additive private evidence, exact legacy/canonical parity |
| Unrelated fixtures have no unexplained regression | Pass — 14/14 healthy corpus controls and 25 healthy neighbors remained render-free |
| Quality/performance recorded | Pass — final-code deterministic and real-engine metrics retained |
| Tracker/configuration documentation current | Pass |
| Feature flag and rollback verified | Pass — default off with validated audit/recovery/visual dependencies |
| Completion report and independent review complete | Pass — final review approved |
| No concurrent next story | Pass — P02-US04 remained Proposed through closure |

Definition-of-Done result: **10/10 Pass**. P02-US03 is Done.
