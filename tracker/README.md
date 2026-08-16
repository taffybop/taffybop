# Document Parser Improvement Tracker

Status: Phases 0–3 complete (Phase 3 exception-bound; 28 stories, 127 points); LAT-US01 and LAT-US02 administratively Done with their stated deferrals; remaining latency work paused; Phase 04 is release-first complete; Phase 05 is Complete — release-first core functionality validated; Phase 06 has not started; Phases 07–08 remain unstarted  
Source assessments:
[Catastrophe Recap Parsing Assessment](../analysis/catastrophe-recap-benchmark-assessment.md)
and [LlamaParse-15 Benchmark Assessment](benchmarks/llamaparse-15/README.md)  
Proposed scope: 77 stories, 362 story points

Current source-grounded remediation is tracked separately in the
[`functional-fidelity-defects`](functional-fidelity-defects/README.md) queue.
That queue reconciles all 25 remaining LlamaParse-15 functional gaps into 13
root-cause defects and 22 one-at-a-time implementation slices without
rewriting the historical phase records below.

This tracker decomposes the assessment into independently executable stories.
The original planning package changed no production code, dependency,
configuration, API, schema, fixture, or test implementation. Subsequent
approved Phase 0 execution completed the test/reporting-only P00-US01 contract
and the catastrophe source-truth P00-US02 story; no production behavior
changed. P00-US03 has now captured and independently validated the repeatable
measurement baseline.

## Release-first policy for Phases 04–08

Effective 2026-08-10, the requester paused the remaining latency work and
directed Phases 04–08 to use the
[`release-first delivery policy`](release-first-phases-04-08.md). Production
functionality, a representative end-to-end flow, compatibility, ordinary safe
failure, and rollback are release-blocking. Detailed latency/RSS/CPU/process
lineage, adversarial matrices, evidence campaigns, exhaustive gates, and
environment-specific proof move to post-release hardening. Historical records
remain intact and are not relabeled as passes. That policy change did not
itself start or complete implementation. Subsequent authorized work completed
Phase 04 and, on 2026-08-12, all ten Phase 05 stories under the release-first
criteria. Phase 06 has not been started.

## Historical latency source of truth

The 2026-08-08 policy required every In Progress or Proposed story in Phases 04–08 to use
the authenticated
[`LlamaParse latency reference v1`](benchmarks/llamaparse-15/latency-reference-v1.md)
as its sole latency benchmark under the
[`source-of-truth decision`](decisions/2026-08-08-llamaparse-latency-source-of-truth.md).
The initial provider-UI Total Latency rows are planning/reference ceilings;
completion requires at least five interleaved candidate/Llama samples per
applicable case, with candidate p50 and nearest-rank p95 each no greater than
the paired Llama values and unchanged quality/reliability. Previous local
latency benchmarks are non-operative. All RSS, resource, correctness, quality,
security, compatibility, custody/hosted-use, output, timeout/fail-closed,
default-off, and rollback gates remain independent and mandatory. LAT-US02's
requester-directed numerical RSS values are observational rather than a strict
completion threshold for that story alone; required measurements and every
leak/OOM/growth/orphan/cleanup/state-retention control remain mandatory, and
later-story/phase-exit RSS gates are unchanged.

## Paused latency-improvement phase

[`phase-latency`](phase-latency/README.md) is retained as the latency and
post-release hardening workstream. It
contains 8 stories and 36 points in strict LAT-US01 through LAT-US08 order.
LAT-US01 passed Definition of Ready 10/10 and is now Done under its
[scoped r34 owner exception](phase-latency/decisions/LAT-US01-r34-scoped-owner-exception.md).
LAT-US02 was later marked Done under the requester-directed production-first
scope with its deeper validation explicitly deferred. LAT-US03–LAT-US08 remain
Proposed and are paused. P04-US01 retains its completed readiness and historical
evidence. Phase 04 and Phase 05 subsequently completed under the release-first
acceptance criteria; this status update does not relabel deferred hardening
evidence as passed or grant default-on production enablement.

The [LAT-US01 r34 completion record](phase-latency/reports/LAT-US01-non-rss-closure-r34.md)
and its scoped exception retain the local HWM failure without representing it
as a pass. The separate
[LAT-US02 readiness](phase-latency/evidence/LAT-US02-readiness.md) records the
operative authorization and its non-transferable numerical RSS treatment.
The separate [CPU-lineage blocker](phase-latency/evidence/LAT-US02-cpu-lineage-blocker.md)
is the operative campaign NO-GO and is not a completion or waiver.

## Delivery rules

For unfinished Phases 04–08, the release-first policy overrides the exhaustive
metric/evidence portions of the general rules below. Functional dependencies,
production implementation, focused tests, compatibility, safe failure, and
rollback remain required.

- Allowed story points: **1, 2, 3, 5**.
- Any scope estimated above 5 points must be split before it can become Ready.
- Only one story may be In Progress.
- Every story begins with a Definition-of-Ready check.
- Every completed story must run its dedicated tests, impacted phase regression,
  API/schema compatibility, and all prior-phase release gates.
- Before/after quality and performance metrics remain required for deferred
  post-release hardening qualification.
- For release-first completion, the story completion comment and named focused
  regression tests are the release record; historical completion reports and
  evidence bundles remain deferred.
- Work stops for approval after every story unless an explicit sequential phase
  authorization applies. Readiness, completion, and mandatory-stop gates are
  never waived.

Story points represent complexity, uncertainty, affected components, test and
regression effort, and integration risk. They are not calendar-time estimates.

## Status flow

```text
Proposed
  -> Ready (Definition of Ready confirmed)
  -> In Progress
  -> In Review
  -> Done (Definition of Done confirmed)
  -> Approval gate before any next story
```

Blocked stories remain Proposed or Ready with a documented blocker; they do not
move to In Progress.

## Definition of Ready

A story is Ready only when:

1. scope and non-scope are explicit;
2. points are 5 or fewer;
3. dependencies are Done;
4. acceptance criteria are measurable;
5. dedicated tests are identified;
6. required fixtures are available and legally usable;
7. API/schema impact is documented;
8. feature-flag requirements are identified;
9. rollback behavior is defined;
10. expected quality and performance measurements are specified.

The story completion report must record this check before implementation starts.

## Definition of Done

A story is Done only when:

1. implementation and all acceptance criteria are complete;
2. dedicated story tests pass;
3. impacted phase and prior-phase regressions pass;
4. API/schema compatibility tests pass;
5. unrelated fixtures have no unexplained regression;
6. before/after metrics are recorded;
7. tracker and configuration documentation are current;
8. feature flag and rollback are verified where practical;
9. a completion report exists;
10. the next story has not started without approval.

## Proposed test locations

The tracker links to proposed tests, but actual tests remain in the project test
tree and will be created only by their approved story:

```text
tests/
  stories/
    phase_00/
    phase_01/
    phase_02/
    phase_03/
    phase_04/
    phase_latency/
    phase_05/
    phase_06/
    phase_07/
    phase_08/
  regression/
    phase_00/
    phase_01/
    phase_02/
    phase_03/
    phase_04/
    phase_latency/
    phase_05/
    phase_06/
    phase_07/
    phase_08/
  contract/
  fixtures/
  benchmarks/
  performance/
```

Snapshot assertions may supplement but never replace assertions for text value,
element type, reading order, bbox, provenance, confidence, parse concerns,
Markdown, JSON, omissions, duplicates, and unsupported content.

## Tracker layout

Every phase contains:

- `README.md`: phase outcome, entry/exit criteria, and story index;
- `backlog.md`: ordered story summary;
- `phase-regression.md`: required regression suites and gates;
- `metrics.md`: before, target, and after measurements;
- `stories/`: complete story specifications;
- `reports/`: story completion and phase reports;
- `decisions/`: architecture and scope decisions;
- `evidence/`: metric outputs, before/after artifacts, and review evidence.

Global planning:

- [Roadmap and phase summary](roadmap.md)
- [Dependency graph, execution gates, risks, and open questions](dependencies.md)
- [LlamaParse-15 benchmark assessment](benchmarks/llamaparse-15/README.md)
- [Source-reviewed gap register](benchmarks/llamaparse-15/gap-register.md)
- [Gap-to-story mapping](benchmarks/llamaparse-15/gap-to-story-matrix.md)
- [Milestone plan](benchmarks/llamaparse-15/milestone-plan.md)
- [Phase 02 exit verification](phase-02-text-integrity/evidence/P02-phase-exit-verification.md)
- [Phase 02 completion report](phase-02-text-integrity/reports/P02-phase-exit-completion.md)

The supplied 15-case corpus is sufficient for the M0 PDF baseline but contains
no fully scanned document, direct-image twin, image-only-PDF twin, DOCX, PPTX,
or XLSX twin. Phase 07's M5 parity exit gate remains blocked until those
approved semantic twins exist.

## Approval boundary

The user authorized sequential execution of Phase 0 on 2026-07-28. P00-US01
and P00-US02 are Done with corrected completion evidence. The exact
catastrophe triplet was approved as public/redistributable, and on 2026-07-29
the requester confirmed the same classification for all remaining 14 triplets
and derived annotations with no exceptions. P00-US01 through P00-US04 are Done.
The
former combined P00-US04 reached 8 of 10 readiness checks before the requester
approved its bounded replacement on 2026-07-29. Phase 0 now has 10 stories/44
points: portable registry, claim contracts, three finite claim batches,
controls, and the renumbered P00-US10 runner. The new P00-US04 passed its own
Definition of Ready 10/10, all implementation gates, and independent review.
P00-US05 passed Definition of Ready 10/10, all implementation gates, and
independent review and is Done. The requester approved correcting the claim
denominator to 71 for batch A and 210 corpus-wide while retaining one-to-one
mapping. P00-US06 then registered all 71 Batch A rows, passed every gate and
independent review, and is Done. P00-US07 then registered all 76 Batch B rows,
passed every gate and independent review, and is Done. P00-US08 registered all
63 Batch C rows, closed the 210-claim corpus, passed every gate and independent
review, and is Done. P00-US09 registered all 25 owners, 100 roles, and 109
case-gap rows, passed every gate and independent review, and is Done. P00-US10
then retained the immutable 15-case baseline and 12-dimension report, passed
all gates and independent review, and is Done. Phase 0 closed at 10 stories
and 44 points. On 2026-07-29 the requester supplied autonomous remaining-phase
authorization; its executable Phase 01–08 interpretation is recorded in
`decisions/2026-07-29-autonomous-execution-boundary.md`. P01-US01 then
introduced the default-off internal IR, passed all gates and independent
review, and is Done. P01-US02 retained 195/195 real Docling references, passed
all gates and independent review, and is Done. P01-US03 then established the
strict canonical presentation contract with 3,009/3,009 unique corpus
contributions, zero unreviewed differences, bounded cumulative performance,
and passing independent review. P01-US04 completed exact backend/frontend
canonical parity across all 15 corpus cases, retained the absent-only legacy
fallback, passed full regression and independent differential/UI review, and
closed Phase 1 at 20/20 points with all seven exit criteria passing. Phase 2's
font fixture, dependency, license, and security policy is accepted. P02-US01
then added bounded malformed-font detection, passed all acceptance, regression,
compatibility, performance, security, and independent-review gates, and is
Done. P02-US02 passed all recovery, compatibility, security, performance,
evidence, and independent-review gates and is Done. P02-US03 then passed all
selective-routing, compatibility, security, real-engine performance, retained
evidence, and independent-review gates and is Done. P02-US04 then completed
strict evidence/geometry reconciliation, retained 15-case final-code metrics,
passed full compatibility and security review, and is Done. P02-US05 then
completed numeric-safe OCR cleanup, passed all acceptance, regression,
compatibility, performance, custody, and independent-review gates, and is
Done. P02-US06 then completed spatial occurrence preservation with exact
12-label and grounded-short evidence, bounded performance, retained custody,
and passing independent reviews; it is Done. The final source-bound phase-exit
screen then passed all 15 enabled/predecessor pairs, 5/5 affected target cases,
all control parity and approved-owner-drift checks, and the 10% performance
ceiling. Phase 2 is complete at 6 stories/25 points. Its retained artifact is
`phase-02-text-integrity/evidence/P02-source-text-alignment-metrics.json`,
SHA-256
`6fdd74cb7adece95ae4a67cc98d1d02e3ca071f9166d4c8c26150768114dbacb`.
The source-alignment flag remains off by default with one-flag rollback and no
new dependency. Phase 03 then completed. P03-US01 completed exact
source-grounded external table-caption projection at 3/3 reviewed identities
with zero duplicates, full bbox/link coverage, unchanged table content,
bounded performance, exact rollback, retained final-code evidence, and passing
independent reviews; it is Done. P03-US02 then completed exact recovery of all
5 reviewed visual captions with precision and recall of 1.0, unchanged frozen
Uber OCR fragments, bounded performance, retained final-code evidence, and
passing independent reviews; it is Done. P03-US03 then completed exact 8/8
reviewed source-note/footnote recovery, 14/14 classified note/control records,
five grounded links, zero false associations, bounded paired performance,
exact rollback, retained final-code evidence, and passing independent security
and metrics/custody reviews; it is Done. P03-US04 is Done with 41/41 fixed
order pairs, exact rollback, passing performance, and independently sealed
final-code evidence. P03-US05 is Done with exact reviewed redline/run
relationships, 7/7 purchase source composition, retained 41/41 order,
default-off parity, bounded performance/resources, frontend compatibility, and
independently sealed final-code evidence. P03-US06 is Done with exact reviewed
form/control/key-value outputs, bounded resources and performance, frontend
compatibility, exact rollback, retained final-code evidence, and passing
independent reviews. P03-US07 is Done with exact component and settlement
outline graphs, zero false-list controls, strict rollback/security behavior,
bounded resources and paired performance, frontend compatibility, retained
final-code evidence, and passing independent reviews. P03-US08 is Done only
with the approved active time-bounded
[frontend bbox compatibility renewal](phase-03-layout/decisions/P03-US08-frontend-bbox-latency-exception-renewal.md):
attempt 48 remains failed, the complete companion remains quarantined
post-seal-invalid, the strict canonical final is absent, and RSS is not waived.
The renewal preserves the exact 1.8935% latency exception, and failed history
is sealed through attempt 55 by manifest
`bca401f2207619ba84422e020104b9a609e0be0f4dc2b42f3ae4fb53d315ceff`.
It is default off, reviewable no later than 2026-09-02, and expires before
production enablement or any relevant running-region semantic/runtime/custody
change. Unrelated, default-off Phase 04 table work admitted by the operative
administrative classifier does not relabel attempt 48 or create a strict pass.
Phase 3 is complete at 8/8 stories and
38/38 points; the cumulative
total through Phase 3 is 28 stories and 127 points. On 2026-08-03 the requester
explicitly authorized Phase 4. P04-US01 independently passed Definition of
Ready 10/10 and entered In Progress on 2026-08-04; the other three Phase 4
stories remain Proposed. The authorization grants no new waiver. The exact
hardened P03-US08 bundle received independent final approval recorded in
[the approval record](phase-03-layout/evidence/P03-US08-phase04-tables-hardened-renewal-independent-approval.md).
The requester-approved
[Phase 4 authorization](decisions/2026-08-03-phase-04-authorization.md) and
[phase-boundary/clean-chat handoff](decisions/2026-07-30-phase-boundary-and-clean-chat-handoff.md)
govern the transition.

Hardened superseding renewal (2026-08-03):
[`P03-US08-LATENCY-EXCEPTION-RENEWAL-20260803-PHASE04-TABLES-HARDENED`](phase-03-layout/decisions/P03-US08-phase04-tables-latency-exception-hardened-renewal.md)
and its
[executable record](phase-03-layout/evidence/P03-US08-phase04-tables-latency-waiver-hardened-renewal.json)
govern current applicability together with
[the exact-bundle independent approval](phase-03-layout/evidence/P03-US08-phase04-tables-hardened-renewal-independent-approval.md),
without rewriting any earlier decision, waiver, identity, or result. Attempt
48 remains failed at `ny-timetable` /
`running_region_projection` p95 **0.050946750 seconds** against the unchanged
**0.050000000-second** ceiling (**0.000946750 seconds / 1.8935%** over, within
the unchanged maximum **5%** candidate-specific bound); the companion remains
quarantined, the strict-final artifact remains absent, and Phase 03 is not a
strict current-artifact metrics pass. Only default-off Phase 04 table changes
admitted and structurally sealed by that executable record are exempt from the
former blanket required-code/Phase-04-exit trigger. A protected running-region
semantic, runtime, or custody change, or expansion of the authorized table
scope, requires a new explicit decision and expires this renewal before the
change; production enablement also remains prohibited, and review is due no
later than **2026-09-02**. Default-off rollback and every non-waived RSS,
paired/source/Uber latency, correctness, security, compatibility, custody,
resource, output, rollback, and hosted-use gate remain in force.

## Historical phase-latency authorization (2026-08-08)

The requester then authorized autonomous completion of
[`phase-latency`](phase-latency/README.md) as the exclusive workstream, with no
loss of reliability, stability, correctness, quality, or safety. That boundary
superseded earlier live-status wording at the time, but does not rewrite the
historical facts or sealed evidence above. P04-US01 was **Ready — execution
paused**. LAT-US01 subsequently completed under its exact scoped r34 exception.
On 2026-08-10 LAT-US02 received separate requester confirmation, passed its
fresh 10/10 readiness check, and became the sole **In Progress** story;
LAT-US03–LAT-US08 and all other Phase 04 stories remain Proposed.

The LAT-US02 production local campaign is blocked by independently confirmed
Major `LAT-US02-METRIC-CPU-001`; no campaign or hosted call occurred. Resolving
it requires separate authority for a non-bypassable process-lineage
architecture and does not authorize LAT-US03.

The requester's later
[`story-by-story confirmation boundary`](decisions/2026-08-08-phase-latency-story-confirmation-boundary.md)
narrows only that execution cadence: after LAT-US01 is genuinely Done and
reported, stop until the requester explicitly confirms LAT-US02. That
confirmation was supplied on 2026-08-10. The same stop and confirmation
requirement still applies after LAT-US02 and every later story.

The exact
[`phase-latency P03-US08 continuity renewal`](phase-latency/decisions/LAT-P03-US08-latency-continuity-renewal.md)
preserves attempt 48 unchanged, every ceiling, the maximum 5% candidate-
specific bound, strict-final absence, default-off rollback, and all non-waived
gates. It remains reviewable no later than 2026-09-02 and expires before
production enablement or any relevant protected running-region semantic,
runtime, reachability, output, dependency, evidence, or custody change. That
historical authorization claimed no strict P03 pass, Phase 04 resumption,
Phase 05 authority, hosted use, or production approval. The later release-first
authorizations and completion records supersede only the Phase 04/05 delivery
status: Phase 05 is complete as of 2026-08-12, and Phase 06 has not started.
