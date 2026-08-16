# Roadmap and Ordered Backlog

Status: Phases 0–3 complete; LAT-US01 and LAT-US02 administratively Done with recorded deferrals; LAT-US03–LAT-US08 paused; Phases 04–08 resumed for release-first planning  
Execution policy: deliver core production functionality in dependency order under the [release-first policy](release-first-phases-04-08.md); this documentation update does not start implementation

Historical latency policy (2026-08-08): the
[`LlamaParse latency reference v1`](benchmarks/llamaparse-15/latency-reference-v1.md)
was the strict latency benchmark for unfinished Phases 04–08. Under the
2026-08-10 release-first policy it is deferred to post-release hardening. The
initial one-sample rows are planning ceilings only; story/phase closure uses at
least five interleaved samples per applicable case and requires candidate p50
and nearest-rank p95 to be no greater than paired LlamaParse values without
quality or reliability loss. Previous local latency benchmarks are retired
from acceptance; all non-latency gates remain mandatory.

## Phase summary

| Phase | Outcome | Stories | Points | Exit gate |
|---|---|---:|---:|---|
| 00 — Baseline | Reproducible truth, metrics, and current-system baseline | 10 | 44 | Reviewed 15-case truth and immutable semantic baseline reports are reproducible |
| 01 — Shared IR | Versioned evidence/relationship IR and one canonical presentation path | 4 | 20 | JSON/Markdown/text derive consistently from the IR without breaking v1 clients |
| 02 — Text Integrity | Detect, repair, or explicitly flag damaged native text | 6 | 25 | Pass — 6/6 stories, 15/15 enabled/predecessor pairs, 5/5 affected targets, and 0 non-target changes |
| 03 — Layout | Preserve captions, forms, redlines, outlines, page identity, and relationship-aware order | 8 | 38 | Complete — 8/8 stories, 38/38 points; P03-US08 exception-bound |
| 04 — Tables | Evidence-preserving table selection and structure without fabricated spans or unsafe merges | 4 | 20 | Representative span, reconciliation, gate, continuation/refusal, compatibility, and rollback flows pass |
| 05 — Charts & Diagrams | Source-grounded vector, raster, and diagram structure with safe fallback | 10 | 48 | Supported representative vector/raster/diagram flows serialize safely; unsupported content falls back |
| 06 — Visual Models | Optional, policy-controlled model escalation | 6 | 30 | Grounded test-double output merges additively; every disabled/denied/error path falls back |
| 07 — Cross-format | Shared behavior across images, Office files, and future adapters | 9 | 43 | Minimal DOCX/PPTX/XLSX flows pass bounded intake, native-first output, compatibility, and rollback |
| 08 — Production Hardening | Measured, reversible, observable production release controls | 12 | 58 | Basic flags, telemetry, policy, manifest, functional smoke gate, runbook, and rollback smoke pass |
| Latency — Improvement | Cross-cutting latency attribution and optimization without quality or reliability loss | 8 | 36 | Paused; remaining validation and optimization move to post-release hardening |

The [phase-latency](phase-latency/README.md) workstream is paused after the
requester-directed LAT-US02 closure. P04-US01 may resume first; later Phases
04–08 remain incomplete and use the release-first completion standard.
The canonical portfolio is 77 stories and 362 points.

LAT-US01's [r34 completion record](phase-latency/reports/LAT-US01-non-rss-closure-r34.md)
and [scoped owner exception](phase-latency/decisions/LAT-US01-r34-scoped-owner-exception.md)
record Done status only for the exact retained r34 bytes. The local HWM failure
remains a failure. LAT-US02 separately passed fresh 10/10 readiness on
2026-08-10 and is the sole In Progress story; LAT-US03–LAT-US08 remain
Proposed. Its [blocked handoff](phase-latency/reports/LAT-US02-blocked-handoff.md)
records Major `LAT-US02-METRIC-CPU-001`, zero campaign/hosted use, and the
unsatisfied LAT-US02 → LAT-US03 dependency.

## Complete ordered backlog

| Order | Story | Points | Depends on |
|---:|---|---:|---|
| 1 | [P00-US01 — Define benchmark manifest and metric contracts](phase-00-baseline/stories/P00-US01.md) | 3 | — |
| 2 | [P00-US02 — Register catastrophe source truth and evidence](phase-00-baseline/stories/P00-US02.md) | 5 | P00-US01 |
| 3 | [P00-US03 — Capture baseline outputs and phase regression report](phase-00-baseline/stories/P00-US03.md) | 5 | P00-US02 |
| 4 | [P00-US04 — Register the portable 15-case corpus](phase-00-baseline/stories/P00-US04.md) | 3 | P00-US01, P00-US02 |
| 5 | [P00-US05 — Define reviewed-claim and inclusion-mask contracts](phase-00-baseline/stories/P00-US05.md) | 3 | P00-US04 |
| 6 | [P00-US06 — Register reviewed claims batch A](phase-00-baseline/stories/P00-US06.md) | 5 | P00-US05 |
| 7 | [P00-US07 — Register reviewed claims batch B](phase-00-baseline/stories/P00-US07.md) | 5 | P00-US06 |
| 8 | [P00-US08 — Register reviewed claims batch C](phase-00-baseline/stories/P00-US08.md) | 5 | P00-US07 |
| 9 | [P00-US09 — Register benchmark control roles](phase-00-baseline/stories/P00-US09.md) | 5 | P00-US08 |
| 10 | [P00-US10 — Run immutable corpus baselines and semantic comparisons](phase-00-baseline/stories/P00-US10.md) | 5 | P00-US03, P00-US09 |
| 11 | [P01-US01 — Introduce versioned evidence and relationship IR](phase-01-shared-ir/stories/P01-US01.md) | 5 | P00-US10 |
| 12 | [P01-US02 — Normalize elements without flattening evidence](phase-01-shared-ir/stories/P01-US02.md) | 5 | P01-US01 |
| 13 | [P01-US03 — Generate canonical presentation blocks](phase-01-shared-ir/stories/P01-US03.md) | 5 | P01-US02 |
| 14 | [P01-US04 — Enforce backend/frontend serialization parity](phase-01-shared-ir/stories/P01-US04.md) | 5 | P01-US03 |
| 15 | [P02-US01 — Detect malformed PDF font mappings](phase-02-text-integrity/stories/P02-US01.md) | 5 | P01-US02 |
| 16 | [P02-US02 — Recover safe identity-mapped font text](phase-02-text-integrity/stories/P02-US02.md) | 5 | P02-US01 |
| 17 | [P02-US03 — Escalate unresolved spans to selective OCR](phase-02-text-integrity/stories/P02-US03.md) | 5 | P02-US02 |
| 18 | [P02-US04 — Reconcile native, font, and OCR candidates](phase-02-text-integrity/stories/P02-US04.md) | 5 | P02-US03 |
| 19 | [P02-US05 — Make OCR token cleanup numeric-safe](phase-02-text-integrity/stories/P02-US05.md) | 2 | P00-US03 |
| 20 | [P02-US06 — Preserve spatial repetition and short tokens](phase-02-text-integrity/stories/P02-US06.md) | 3 | P02-US04, P02-US05 |
| 21 | [P03-US01 — Preserve external table captions](phase-03-layout/stories/P03-US01.md) | 3 | P01-US02 |
| 22 | [P03-US02 — Separate visual captions from internal children](phase-03-layout/stories/P03-US02.md) | 5 | P01-US02 |
| 23 | [P03-US03 — Associate source notes and footnotes](phase-03-layout/stories/P03-US03.md) | 5 | P03-US01, P03-US02 |
| 24 | [P03-US04 — Resolve relationship-aware reading order and bboxes](phase-03-layout/stories/P03-US04.md) | 5 | P03-US03, P01-US03 |
| 25 | [P03-US05 — Preserve source-visible redline and text-run semantics](phase-03-layout/stories/P03-US05.md) | 5 | P01-US02, P03-US04 |
| 26 | [P03-US06 — Extract form controls and key-value relationships](phase-03-layout/stories/P03-US06.md) | 5 | P01-US02, P03-US04 |
| 27 | [P03-US07 — Preserve list and legal-clause hierarchy](phase-03-layout/stories/P03-US07.md) | 5 | P01-US02, P03-US04 |
| 28 | [P03-US08 — Separate running regions and printed page identity](phase-03-layout/stories/P03-US08.md) | 5 | P01-US03, P03-US04 |
| 29 | [LAT-US01 — Establish exact stage attribution and benchmark harness](phase-latency/stories/LAT-US01.md) | 5 | P00-US10, P01-US04, P02-US06, P03-US08 |
| 30 | [LAT-US02 — Prewarm and safely reuse parser workers](phase-latency/stories/LAT-US02.md) | 3 | LAT-US01 |
| 31 | [LAT-US03 — Reuse immutable document evidence within a request](phase-latency/stories/LAT-US03.md) | 5 | LAT-US02 |
| 32 | [LAT-US04 — Execute independent page and OCR work concurrently](phase-latency/stories/LAT-US04.md) | 5 | LAT-US03 |
| 33 | [LAT-US05 — Reduce redundant output materialization](phase-latency/stories/LAT-US05.md) | 3 | LAT-US04 |
| 34 | [LAT-US06 — Route optional work only from sufficient source evidence](phase-latency/stories/LAT-US06.md) | 5 | LAT-US05 |
| 35 | [LAT-US07 — Bound parser concurrency and queue latency](phase-latency/stories/LAT-US07.md) | 5 | LAT-US06 |
| 36 | [LAT-US08 — Qualify final latency candidate and rollback](phase-latency/stories/LAT-US08.md) | 5 | LAT-US07 |
| 37 | [P04-US01 — Preserve explicit table cells and span fidelity](phase-04-tables/stories/P04-US01.md) | 5 | P03-US01 |
| 38 | [P04-US02 — Reconcile Docling and vector table evidence](phase-04-tables/stories/P04-US02.md) | 5 | P04-US01, P02-US04 |
| 39 | [P04-US04 — Gate table candidates and reject visual impostors](phase-04-tables/stories/P04-US04.md) | 5 | P04-US02, P03-US06 |
| 40 | [P04-US03 — Handle continued and multi-page tables safely](phase-04-tables/stories/P04-US03.md) | 5 | P04-US02, P04-US04, P03-US04 |
| 41 | [P05-US01 — Define chart/diagram schema and fallback](phase-05-charts-diagrams/stories/P05-US01.md) | 5 | P01-US02, P03-US04 |
| 42 | [P05-US02 — Inventory vector marks, panels, and transforms](phase-05-charts-diagrams/stories/P05-US02.md) | 5 | P05-US01 |
| 43 | [P05-US03 — Calibrate axes and associate legends and series](phase-05-charts-diagrams/stories/P05-US03.md) | 5 | P05-US02, P02-US06 |
| 44 | [P05-US04 — Measure vector values with provenance and tolerance](phase-05-charts-diagrams/stories/P05-US04.md) | 5 | P05-US03 |
| 45 | [P05-US05 — Validate and serialize structured charts safely](phase-05-charts-diagrams/stories/P05-US05.md) | 5 | P05-US04, P01-US04 |
| 46 | [P05-US06 — Extract raster chart labels, axes, and legends](phase-05-charts-diagrams/stories/P05-US06.md) | 5 | P05-US01, P02-US06 |
| 47 | [P05-US07 — Measure supported raster bar marks](phase-05-charts-diagrams/stories/P05-US07.md) | 5 | P05-US06, P05-US05 |
| 48 | [P05-US08 — Measure supported raster line marks](phase-05-charts-diagrams/stories/P05-US08.md) | 5 | P05-US06, P05-US05 |
| 49 | [P05-US09 — Gate raster parity, resources, and fallback](phase-05-charts-diagrams/stories/P05-US09.md) | 3 | P05-US07, P05-US08, P05-US05 |
| 50 | [P05-US10 — Extract basic diagram topology](phase-05-charts-diagrams/stories/P05-US10.md) | 5 | P05-US01, P03-US04 |
| 51 | [P06-US01 — Define grounded visual-model contracts](phase-06-visual-models/stories/P06-US01.md) | 5 | P05-US01 |
| 52 | [P06-US02 — Add an optional local visual-model adapter](phase-06-visual-models/stories/P06-US02.md) | 5 | P06-US01 |
| 53 | [P06-US03 — Add a policy-controlled hosted adapter](phase-06-visual-models/stories/P06-US03.md) | 5 | P06-US01 |
| 54 | [P06-US04 — Route eligible regions and select a visual-model adapter](phase-06-visual-models/stories/P06-US04.md) | 5 | P06-US02, P06-US03, P05-US09, P05-US10 |
| 55 | [P06-US05 — Ground and validate model observations](phase-06-visual-models/stories/P06-US05.md) | 5 | P06-US04, P05-US05 |
| 56 | [P06-US06 — Merge accepted evidence and guarantee deterministic fallback](phase-06-visual-models/stories/P06-US06.md) | 5 | P06-US05, P01-US04 |
| 57 | [P07-US01 — Define adapter contract and reusable conformance harness](phase-07-cross-format/stories/P07-US01.md) | 5 | P01-US04, P03-US04 |
| 58 | [P07-US02 — Prove PDF/direct-image semantic parity](phase-07-cross-format/stories/P07-US02.md) | 3 | P07-US01, P05-US09, P05-US10 |
| 59 | [P07-US03 — Add bounded and secure OOXML package intake](phase-07-cross-format/stories/P07-US03.md) | 5 | P07-US01 |
| 60 | [P07-US04 — Add a DOCX native-evidence adapter](phase-07-cross-format/stories/P07-US04.md) | 5 | P07-US01, P07-US03, P04-US02 |
| 61 | [P07-US05 — Add a PPTX native-evidence adapter](phase-07-cross-format/stories/P07-US05.md) | 5 | P07-US01, P07-US03, P03-US04 |
| 62 | [P07-US06 — Add an XLSX native-evidence adapter](phase-07-cross-format/stories/P07-US06.md) | 5 | P07-US01, P07-US03, P04-US02 |
| 63 | [P07-US07 — Extract native Office chart evidence](phase-07-cross-format/stories/P07-US07.md) | 5 | P07-US05, P07-US06, P05-US05 |
| 64 | [P07-US08 — Reconcile Office native evidence with bounded visual fallback](phase-07-cross-format/stories/P07-US08.md) | 5 | P07-US02, P07-US04, P07-US05, P07-US06, P07-US07 |
| 65 | [P07-US09 — Add future-adapter conformance gates](phase-07-cross-format/stories/P07-US09.md) | 5 | P07-US08 |
| 66 | [P08-US01 — Centralize feature flags and rollback controls](phase-08-production-hardening/stories/P08-US01.md) | 5 | P07-US09 |
| 67 | [P08-US02 — Add privacy-safe telemetry primitives and exporter isolation](phase-08-production-hardening/stories/P08-US02.md) | 5 | P08-US01 |
| 68 | [P08-US03 — Instrument stage latency and resource usage](phase-08-production-hardening/stories/P08-US03.md) | 5 | P08-US02 |
| 69 | [P08-US04 — Instrument quality, fallback, escalation, and cost](phase-08-production-hardening/stories/P08-US04.md) | 5 | P08-US02, P06-US06 |
| 70 | [P08-US05 — Calibrate text, layout, and table confidence](phase-08-production-hardening/stories/P08-US05.md) | 5 | P08-US03, P08-US04, P00-US03 |
| 71 | [P08-US06 — Calibrate chart, diagram, and model confidence](phase-08-production-hardening/stories/P08-US06.md) | 5 | P08-US03, P08-US04, P06-US06, P05-US05 |
| 72 | [P08-US07 — Route grounded review packets with budgets and outcomes](phase-08-production-hardening/stories/P08-US07.md) | 5 | P08-US05, P08-US06, P01-US04 |
| 73 | [P08-US08 — Produce a versioned artifact and license manifest](phase-08-production-hardening/stories/P08-US08.md) | 5 | P08-US03, P07-US09 |
| 74 | [P08-US09 — Enforce hosted privacy, retention, residency, and egress gates](phase-08-production-hardening/stories/P08-US09.md) | 5 | P08-US08, P06-US06 |
| 75 | [P08-US10 — Compare canaries and produce the blocking release gate](phase-08-production-hardening/stories/P08-US10.md) | 5 | P08-US04, P08-US07, P08-US08, P08-US09 |
| 76 | [P08-US11 — Define testable release and rollback runbooks](phase-08-production-hardening/stories/P08-US11.md) | 3 | P08-US10 |
| 77 | [P08-US12 — Execute failure-injection and rollback drill](phase-08-production-hardening/stories/P08-US12.md) | 5 | P08-US11 |

Total proposed scope: **77 stories, 362 story points**. This is a complexity
inventory, not a duration forecast.

## Sizing discipline

The backlog was audited for hidden multi-algorithm and multi-control-plane scope.
Raster analysis, visual-model orchestration, Office ingestion, telemetry,
calibration, release policy, and rollback were split at independent test and
rollback boundaries. A proposed five-point story may still be split during its
Definition-of-Ready check if new evidence expands its bounded scope; it may not
enter In Progress above the five-point ceiling.

The LlamaParse-15 review and approved Phase 0 split added twelve independently
testable stories relative to the original 57-story plan and re-estimated
P04-US01 from three to five points. The rationale and one-to-one gap ownership
are recorded in the
[gap-to-story matrix](benchmarks/llamaparse-15/gap-to-story-matrix.md).

## Recommended execution order

Use the table order as the default sequence. It is intentionally conservative:

1. create reproducible truth before behavior changes;
2. establish the evidence/relationship IR and canonical serialization;
3. repair text and spatial evidence;
4. correct layout, forms, redlines, lists, and page identity;
5. complete the dedicated latency-attribution and quality-preserving
   optimization chain;
6. resume tables only after separate confirmation;
7. add deterministic vector, raster, and diagram intelligence;
8. add optional models only after grounded fallbacks exist;
9. prove the same semantics across images and native Office formats;
10. instrument and calibrate before defining promotion thresholds;
11. gate artifacts, privacy, canaries, and rollback before release.

Some dependencies permit parallel engineering, but the delivery policy still
allows only one story In Progress unless an explicit exception is approved.
The milestone-specific corpus subsets and the current M5 semantic-twin blocker
are recorded in the
[benchmark execution order](benchmarks/llamaparse-15/execution-order.md).

## Current execution boundary

[P00-US01](phase-00-baseline/stories/P00-US01.md) and
[P00-US02](phase-00-baseline/stories/P00-US02.md) are Done. The latter
registers the exact approved catastrophe triplet and reviewed source truth
without changing production behavior. P00-US03 has captured and independently
validated five immutable reference runs and is Done. P00-US04 is also Done
after its portable registry passed all implementation gates and independent
review.
All 15 triplets and derived annotations are now explicitly public and
redistributable with no exceptions. The requester approved the bounded
P00-US04–P00-US10 replacement sequence with finite registry, claim, and control
denominators. P00-US05 passed Definition of Ready 10/10, all implementation
gates, and independent review and is Done. The requester approved the corrected
71/210 claim denominators. P00-US06 registered all 71 Batch A rows, passed
every gate and independent review, and is Done. P00-US07 registered all 76
Batch B rows, passed every gate and independent review, and is Done. P00-US08
registered all 63 Batch C rows, closed the 210-claim corpus, passed every gate
and independent review, and is Done. P00-US09 registered all 25 owners, 100
roles, and 109 case-gap rows, passed every gate and independent review, and is
Done. P00-US10 then retained 15/15 cases, 30/30 pages, the complete
reviewed-mask ledger, and 12 separate reports; all gates and independent
review passed. Phase 0 is complete at 44/44 points. The inferred remaining
authorization boundary is recorded, the additive-v1 schema policy is accepted,
and P01-US01 is Done after exact 15-case IR round trips, full regression, and
independent review. P01-US02 is Done after retaining 195/195 real Docling
references with explicit evidence/relationships, full regression, bounded
performance, and independent review. P01-US03 is Done after establishing one
strict canonical presentation contract, reviewing all 15 corpus dispositions,
proving zero duplicate contributions, passing full backend/frontend gates, and
staying below the phase performance ceiling. P01-US04 is Done after exact
canonical Markdown/text/JSON frontend parity across all 15 cases, frozen
legacy fallback, full regression, and independent Python-differential and UI
review. Phase 1 is complete at 20/20 points with all seven exit criteria
passing. Phase 2's font fixture/dependency policy is accepted. P02-US01 passed
its Definition of Ready, all implementation, corpus, compatibility, security,
performance, and regression gates, and two independent reviews; it is Done.
P02-US02 recovered the exact target with 150/150 grounded glyphs, zero healthy
rewrites, bounded performance, and passing independent review; it is Done.
P02-US03 completed exact selective routing with zero healthy-neighbor renders,
complete affine/pass/cost evidence, default-off canonical parity, bounded real
PDFium/Tesseract performance, and passing independent review; it is Done.
P02-US04 completed source-bound text reconciliation with strict retained
evidence, default-off parity, bounded performance, and passing independent
production/security and metrics/custody reviews; it is Done. P02-US05
completed numeric-safe OCR cleanup with exact decimal/hash controls,
default-off parity, bounded performance, retained final-code evidence, and
passing independent production/security and metrics/custody reviews; it is
Done. P02-US06 then completed spatial occurrence preservation with exact
12-label and grounded-short evidence, default-off parity, bounded performance,
retained final-code custody, and passing independent reviews; it is Done. The
final source-bound exit screen passed all 15 enabled/predecessor pairs, 5/5
affected target cases, every paired control parity check, approved owner drift
for all 15 cases, and the 10% cumulative performance ceiling. Phase 2 is
complete at 6 stories/25 points. Source alignment remains default off with
one-flag rollback and no new dependency.

Phase 3 is complete. P03-US01 is Done with exact 3/3 external table-caption
identities, bounded default-off projection, retained final-code evidence, and
passing independent review. P03-US02 is Done with exact 5/5 reviewed visual
captions, precision and recall of 1.0, unchanged frozen Uber OCR fragments,
bounded performance, retained final-code evidence, and passing independent
reviews. P03-US03 is Done with exact 8/8 reviewed notes, 14/14 exact
note/control records, five grounded links, zero false associations, passing
paired performance ceilings, exact rollback, retained final-code evidence, and
passing independent reviews. P03-US04 is Done with 41/41 fixed order pairs,
exact rollback, passing performance, and independently sealed final-code
evidence. P03-US05 is Done with exact reviewed redline/run relationships, 7/7
purchase source composition, retained 41/41 order, exact rollback, bounded
performance/resources, frontend compatibility, and independently sealed
final-code evidence. P03-US06 is Done with exact reviewed
form/control/key-value outputs, bounded resources and performance, frontend
compatibility, exact rollback, retained final-code evidence, and passing
independent reviews. P03-US07 is Done with exact component and settlement
outline graphs, zero false-list controls, strict rollback/security behavior,
bounded resources and paired performance, frontend compatibility, retained
final-code evidence, and passing independent reviews. P03-US08 is Done only
with the approved active time-bounded
[frontend bbox compatibility renewal](phase-03-layout/decisions/P03-US08-frontend-bbox-latency-exception-renewal.md).
Its strict final artifact remains absent, attempt 48 remains failed, its
complete companion remains quarantined post-seal-invalid, and memory is not
waived. The renewal retains the same 1.8935% exception, default-off rollback,
and no other waivers. Failed history is sealed through attempt 55 by manifest
`bca401f2207619ba84422e020104b9a609e0be0f4dc2b42f3ae4fb53d315ceff`.
Review is due no later than 2026-09-02, and the exception expires before
production enablement or any relevant running-region semantic/runtime/custody
change. Unrelated default-off Phase 04 table changes admitted by the operative
administrative classifier do not relabel attempt 48 or create a strict pass.
Phase 3 is complete at 8/8 stories and
38/38 points; 28 stories and 127 points are complete through Phase 3. The
requester authorized Phase 04 on 2026-08-03; P04-US01 independently passed
Definition of Ready 10/10. The exact hardened P03-US08 renewal received final
independent approval on 2026-08-04, and P04-US01 entered In Progress at that
historical checkpoint. On 2026-08-08 the requester authorized Phase Latency as
the sole active workstream: P04-US01 returned to **Ready — execution paused**,
LAT-US01 passed Definition of Ready 10/10 and became the only In Progress
story, and every later latency/Phase 04 story remains Proposed.
That was the historical scheduling state. On 2026-08-10, the requester paused
remaining latency work and resumed Phases 04–08 under the release-first policy;
functional dependency order still applies, while benchmark/evidence gates move
to post-release hardening.

Hardened superseding renewal (2026-08-03): the requester-authorized chain ends at
[`P03-US08-LATENCY-EXCEPTION-RENEWAL-20260803-PHASE04-TABLES-HARDENED`](phase-03-layout/decisions/P03-US08-phase04-tables-latency-exception-hardened-renewal.md)
and its
[executable record](phase-03-layout/evidence/P03-US08-phase04-tables-latency-waiver-hardened-renewal.json),
which is now bound to
[the exact-bundle independent approval](phase-03-layout/evidence/P03-US08-phase04-tables-hardened-renewal-independent-approval.md).
All prior records, identities, and measurements remain historical and
unchanged. Attempt 48 remains failed at `ny-timetable` /
`running_region_projection` p95 **0.050946750 seconds** versus the unchanged
**0.050000000-second** ceiling (**0.000946750 seconds / 1.8935%**, at most
**5%** candidate-specific); the companion remains quarantined, strict-final
evidence remains absent, and no strict current-artifact metrics pass is
claimed. Executable-record-sealed, default-off Phase 04 table-only changes and
Phase 04 exit within that exact scope no longer activate the prior blanket
expiry. Production enablement, any protected running-region semantic/runtime/
custody change, or table-scope expansion still requires a new explicit
decision and expires the renewal before the change; review is due no later
than **2026-09-02**. Default-off rollback and every non-waived RSS, paired and
other latency, correctness, security, compatibility, custody, resource,
output, rollback, and hosted-use gate remain mandatory.

Current administrative continuity (2026-08-07) is governed by
[`P03-US08-LATENCY-EXCEPTION-RENEWAL-20260807-PHASE04-TABLES-ADMINISTRATIVE-CONTINUITY`](phase-03-layout/decisions/P03-US08-phase04-tables-latency-exception-operative-administrative-renewal.md)
and its
[closed semantic classifier](phase-03-layout/evidence/P03-US08-phase04-tables-latency-waiver-operative-administrative-renewal.json).
That sponsor-authorized layer is operative only for unrelated, default-off
Phase 04 table development and evidence; it grants no story-Done, Phase 04
exit, production, hosted-use, or Phase 05 authority. It preserves the exact
attempt-48 failed observation, unchanged ceilings and maximum 5% bound,
strict-final absence, attempt-55 history manifest, rollback, and every
non-waived gate. It expires before any protected running-region semantic,
runtime, or custody change and remains reviewable no later than 2026-09-02.
Its exact classifier received
[independent policy/custody approval](phase-03-layout/evidence/P03-US08-phase04-tables-operative-administrative-renewal-independent-review.md)
on 2026-08-07 with all nine required checks passing. The approval is limited
to administrative continuity and does not replace any exact final-code,
story, production/security, metrics/custody, or Phase 04 exit review.
