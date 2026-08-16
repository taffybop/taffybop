# Recommended Story Execution Order

Status: Phases 0–3 complete (Phase 3 exception-bound; 28 stories, 127 points); LAT-US01 Done under scoped r34 owner exception (local HWM failure retained); LAT-US02 In Progress with campaign blocked by a CPU-lineage Major; LAT-US03–LAT-US08 Proposed; P04-US01 Ready with execution paused  
Policy: one story In Progress at a time; completion report and approval before
the next story

LAT-US01 is complete only under its exact
[scoped r34 owner exception](../../phase-latency/decisions/LAT-US01-r34-scoped-owner-exception.md).
Its retained local HWM failure is not a pass. LAT-US02 later received separate
requester confirmation and passed fresh readiness, but its
[production campaign is blocked](../../phase-latency/evidence/LAT-US02-cpu-lineage-blocker.md)
by Major `LAT-US02-METRIC-CPU-001`. No local campaign or hosted run occurred;
LAT-US03 and later stories remain Proposed.

Latency policy: unfinished Phases 04–08 use only the authenticated
[`LlamaParse latency reference v1`](latency-reference-v1.md). Initial rows are
planning ceilings; final-code gates require at least five interleaved samples
per applicable case with candidate p50/p95 no greater than paired LlamaParse
p50/p95 and no quality/reliability reduction. Earlier local latency benchmarks
are non-operative. The later explicit Phase Latency authorization inserts the
eight-story latency chain before Phase 04 resumes; the canonical current order
is maintained in [`tracker/roadmap.md`](../../roadmap.md).

## Why this order

The benchmark does not justify jumping directly to chart or model work. The
safe sequence is:

1. make reviewed truth and repeatable measurement executable;
2. establish evidence, relationships, and one canonical presentation path;
3. repair text/OCR without rewriting healthy text;
4. correct layout semantics, forms, redlines, lists, and page identity;
5. complete the dedicated latency attribution and quality-preserving
   optimization chain;
6. validate table candidates and structures after separate resumption;
7. add deterministic chart/diagram structure and measurement;
8. permit optional visual models only behind grounding and fallback;
9. prove cross-format parity after the missing M5 twins exist;
10. instrument, calibrate, review, canary, and prove rollback.

## Original benchmark-derived order retained for audit

The table below is the pre-Phase-Latency 69-story ordering retained for audit.
The operative 77-story/362-point order inserts LAT-US01–LAT-US08 after
P03-US08 and before P04-US01, as shown in the canonical roadmap. It must not be
used to start P04 while Phase Latency is active.

| Order | Story | Points | Benchmark reason |
|---:|---|---:|---|
| 1 | P00-US01 | 3 | Metric/manifest contracts |
| 2 | P00-US02 | 5 | Catastrophe reviewed truth |
| 3 | P00-US03 | 5 | Single-case reference baseline |
| 4 | P00-US04 | 3 | Portable 15-case corpus registry |
| 5 | P00-US05 | 3 | Reviewed-claim and inclusion-mask contracts |
| 6 | P00-US06 | 5 | Reviewed claims batch A: 71 claims |
| 7 | P00-US07 | 5 | Reviewed claims batch B: 76 claims |
| 8 | P00-US08 | 5 | Reviewed claims batch C: 63 claims |
| 9 | P00-US09 | 5 | Finite benchmark control registry |
| 10 | P00-US10 | 5 | Immutable corpus runs and semantic reports |
| 11 | P01-US01 | 5 | Evidence/relationship/geometry IR |
| 12 | P01-US02 | 5 | Preserve evidence during normalization |
| 13 | P01-US03 | 5 | Canonical presentation and deduplication |
| 14 | P01-US04 | 5 | Backend/frontend parity |
| 15 | P02-US01 | 5 | Detect malformed font mappings |
| 16 | P02-US02 | 5 | Safe embedded-font recovery |
| 17 | P02-US03 | 5 | Selective unresolved-span OCR |
| 18 | P02-US04 | 5 | Evidence-ranked text reconciliation |
| 19 | P02-US05 | 2 | Numeric-safe token cleanup |
| 20 | P02-US06 | 3 | Spatial repetition and short tokens |
| 21 | P03-US01 | 3 | Table captions |
| 22 | P03-US02 | 5 | Visual caption/child separation |
| 23 | P03-US03 | 5 | Source notes and footnotes |
| 24 | P03-US04 | 5 | Relationship-aware order and ownership |
| 25 | P03-US05 | 5 | Redline/text-run semantics |
| 26 | P03-US06 | 5 | Forms, controls, and key-value relations |
| 27 | P03-US07 | 5 | List/legal outline hierarchy |
| 28 | P03-US08 | 5 | Running regions and printed page identity |
| 29 | P04-US01 | 5 | Explicit cells, spans, and dense-grid fidelity |
| 30 | P04-US02 | 5 | Reconcile table evidence |
| 31 | P04-US04 | 5 | Reject false tables and preserve alternatives |
| 32 | P04-US03 | 5 | Continued/multi-page tables |
| 33 | P05-US01 | 5 | Chart/diagram contract and fallback |
| 34 | P05-US02 | 5 | Vector marks/panels/transforms |
| 35 | P05-US03 | 5 | Axes, legends, categories, and series |
| 36 | P05-US04 | 5 | Vector values with tolerance/provenance |
| 37 | P05-US05 | 5 | Validation and safe serialization |
| 38 | P05-US06 | 5 | Raster labels/axes/legends |
| 39 | P05-US07 | 5 | Supported raster bars |
| 40 | P05-US08 | 5 | Supported raster lines |
| 41 | P05-US09 | 3 | Raster parity/resources/fallback |
| 42 | P05-US10 | 5 | Basic diagram topology |
| 43 | P06-US01 | 5 | Grounded visual-model contract |
| 44 | P06-US02 | 5 | Optional local adapter |
| 45 | P06-US03 | 5 | Policy-controlled hosted adapter |
| 46 | P06-US04 | 5 | Region routing/adapter selection |
| 47 | P06-US05 | 5 | Ground model observations |
| 48 | P06-US06 | 5 | Additive merge and deterministic fallback |
| 49 | P07-US01 | 5 | Adapter contract/conformance |
| 50 | P07-US02 | 3 | PDF/direct-image parity |
| 51 | P07-US03 | 5 | Secure OOXML intake |
| 52 | P07-US04 | 5 | DOCX adapter |
| 53 | P07-US05 | 5 | PPTX adapter |
| 54 | P07-US06 | 5 | XLSX adapter |
| 55 | P07-US07 | 5 | Native Office chart evidence |
| 56 | P07-US08 | 5 | Office native/visual reconciliation |
| 57 | P07-US09 | 5 | Future-adapter conformance |
| 58 | P08-US01 | 5 | Central feature flags/rollback |
| 59 | P08-US02 | 5 | Privacy-safe telemetry |
| 60 | P08-US03 | 5 | Stage resources and performance |
| 61 | P08-US04 | 5 | Quality/fallback/escalation/cost telemetry |
| 62 | P08-US05 | 5 | Text/layout/table confidence calibration |
| 63 | P08-US06 | 5 | Chart/diagram/model confidence calibration |
| 64 | P08-US07 | 5 | Grounded review routing |
| 65 | P08-US08 | 5 | Artifact/license manifest |
| 66 | P08-US09 | 5 | Hosted privacy/retention/residency gates |
| 67 | P08-US10 | 5 | Blocking canary/release gate |
| 68 | P08-US11 | 3 | Release and rollback runbooks |
| 69 | P08-US12 | 5 | Failure-injection/rollback drill |

Historical pre-insertion total: **69 stories, 326 points**. Operative total:
**77 stories, 362 points**. Points represent complexity and risk, not duration.

P03-US07 and P03-US08 were each re-estimated 3→5 on 2026-08-01 after their
independent readiness audits; these updates produce the current total without
rewriting the historical planning estimates.

## Milestone boundaries

| Boundary | Stories that must be complete before the run | Run |
|---|---|---|
| M0 evidence gate | P00-US01–US10 | All 15; truth/runner contracts |
| M1 text gate | P01-US01–US04, P02-US01–US06 | Complete — affected targets passed, followed by 15/15 enabled/predecessor and all-15 drift screens |
| M2 layout gate | P03-US01–US08 | Layout subset, then all 15 drift screen |
| M3 table gate | P04-US01/US02/US04/US03 | All table/form/false-table cases |
| M4 chart/diagram gate | P05-US01–US10; optionally P06 only after local gate | All visual-structure cases |
| M5 cross-format gate | P07-US01–US09 and approved semantic twins | Direct image, image-only PDF, embedded image, native PDF, Office twins |
| M6 release-candidate gate | P08-US01–US10 plus all completed prior phases | Full corpus and broader regression |

P08-US11/US12 follow the M6 blocking candidate and are required before actual
production release.

## Parallelism note

Some dependency branches permit engineering in parallel, but the user-approved
delivery policy still allows only one story In Progress. Any exception requires
explicit approval and must preserve independent flags, tests, completion
reports, and rollback.

## Current execution boundary

P00-US01 through P00-US03 are Done with executable test/reporting contracts,
reviewed catastrophe truth, and an independently validated separate five-run
catastrophe reference baseline; the heterogeneous M0 analysis
artifacts were not used as substitute proof. P00-US10 retained its own strict
integration and full-corpus runs as completion proof.
Custody is resolved for all 15 triplets and derived annotations
with no exceptions, and the bounded 10-story/44-point Phase 0 split is
approved. The new P00-US04 portable registry passed Definition of Ready, all
implementation gates, and independent review and is Done. P00-US05 also passed
all gates and independent review and is Done. The requester approved the
corrected 71/210 denominators. P00-US06 registered all 71 Batch A rows, passed
every gate and independent review, and is Done. P00-US07 registered all 76
Batch B rows, passed every gate and independent review, and is Done. P00-US08
registered all 63 Batch C rows, closed the 210-claim corpus, passed every gate
and independent review, and is Done. P00-US09 registered all 25 owners, 100
roles, and 109 case-gap rows, passed every gate and independent review, and is
Done. P00-US10 then completed 15/15 cases and 30/30 pages, preserved the
reviewed truth boundary, and passed every gate and independent review. Phase 0
is complete.

Phase 1 is complete after P01-US01–P01-US04 established the additive shared IR,
retained source evidence and relationships, enforced one canonical
presentation path, and proved exact backend/frontend parity with passing
regression, performance, compatibility, and independent-review gates.

In Phase 2, P02-US01–P02-US04 completed bounded malformed-font detection, safe
identity-mapped recovery, selective unresolved-span OCR, and source-bound text
reconciliation. P02-US05 then completed numeric-safe OCR cleanup with exact
decimal/hash controls, default-off parity, retained final-code metrics, and
passing independent production/security and metrics/custody reviews. P02-US06
then completed spatial occurrence preservation with exact 12-label and
grounded-short evidence, bounded performance, retained custody, and passing
independent reviews. The final source-bound exit screen passed all 15
enabled/predecessor pairs, 5/5 affected cases, all control parity checks,
approved owner drift, and the cumulative performance ceiling. Phase 02 is
complete at 6 stories/25 points.

P03-US01–P03-US07 are Done with retained exact caption, relationship,
source-note, reading-order, bbox-ownership, text-run/redline, form/key-value,
and outline/list evidence. P03-US08 is Done only with the approved active
[frontend bbox compatibility renewal](../../phase-03-layout/decisions/P03-US08-frontend-bbox-latency-exception-renewal.md);
its strict final remains absent, attempt 48 remains failed, the complete
companion remains quarantined, and RSS is not waived. The renewal retains the
same 1.8935% exception, and failed history is sealed through attempt 55 by
manifest
`bca401f2207619ba84422e020104b9a609e0be0f4dc2b42f3ae4fb53d315ceff`.
It remains reviewable no later than 2026-09-02 and expires before production
enablement or any relevant running-region semantic/runtime/custody change;
unrelated default-off Phase 04 table work admitted by the operative classifier
does not relabel attempt 48. Phase 03 is complete at 8/8 stories and 38/38
points, bringing the
cumulative total through Phase 03 to 28 stories and 127 points. The requester
authorized Phase 04 on 2026-08-03; P04-US01 independently passed Definition of
Ready 10/10 and entered In Progress on 2026-08-04 at that historical
checkpoint. On 2026-08-08, Phase Latency became the sole active workstream:
P04-US01 returned to Ready with execution paused, LAT-US01 passed readiness
10/10 and became the only In Progress story, and every later latency/Phase 04
story remains Proposed.

Hardened superseding renewal (2026-08-03):
[`P03-US08-LATENCY-EXCEPTION-RENEWAL-20260803-PHASE04-TABLES-HARDENED`](../../phase-03-layout/decisions/P03-US08-phase04-tables-latency-exception-hardened-renewal.md)
and its
[executable record](../../phase-03-layout/evidence/P03-US08-phase04-tables-latency-waiver-hardened-renewal.json)
govern current applicability together with
[the exact-bundle independent approval](../../phase-03-layout/evidence/P03-US08-phase04-tables-hardened-renewal-independent-approval.md),
while preserving every historical identity and result above. Attempt 48
remains failed at `ny-timetable` /
`running_region_projection` p95 **0.050946750 seconds** against the unchanged
**0.050000000-second** ceiling (**0.000946750 seconds / 1.8935%**, within the
unchanged maximum **5%** candidate-specific bound); the companion remains
quarantined, canonical strict-final evidence remains absent, and this is not a
strict current-artifact metrics pass. Default-off Phase 04 table changes
admitted and structurally sealed by the record, and Phase 04 exit within that
exact scope, no longer trigger blanket expiry. Production enablement, admitted
scope expansion, or a protected running-region semantic/runtime/custody change
requires a new explicit decision and expires the renewal before the change;
review is due no later than **2026-09-02**. Exact-predecessor default-off
rollback and every non-waived RSS, paired/source/Uber latency, correctness,
security, compatibility, custody, resource/deadline, output, rollback, and
hosted-use gate remain mandatory. The earlier “Proposed and unstarted” phrase
is a historical checkpoint; current Phase 04 status is controlled by the Phase
04 tracker, without any Phase 05 authorization.
