# Phase 03 — Layout

Status: Complete with approved time-bounded metrics exception — 8/8 stories,
38/38 points Done  
Outcome: Captions, notes, text-run semantics, forms, outlines, running regions,
page identity, geometry, and reading order remain distinct and explicitly
related

## Entry criteria

- Phase 01 IR is complete.
- Relevant Phase 02 text evidence is available.
- Reviewed positive, non-target, and negative fixtures for captions, notes,
  order, redlines, forms, lists, and running regions are immutable and available.

## Exit criteria

- Exhibit 7 caption is a distinct `caption_of` element.
- Exhibit 8 caption is outside the chart item; internal children are not captions.
- Source notes/footnotes are linked without relying on crop padding.
- Relationship-aware reading order and bbox containment invariants pass.
- Source-visible redlines retain run state, style, geometry, provenance, and a
  non-destructive canonical projection.
- Form labels, empty value regions, and static controls are explicitly related
  without converting the whole form into a false table.
- Nested lists and legal clauses preserve marker, parent, ordinal, and
  continuation across intervening elements.
- Physical and printed page identity remain separate; running regions are typed,
  ordered, and included once under a documented body/full policy.
- Phase fixtures close `GAP-LAYOUT-001`, `GAP-ORDER-001`, `GAP-PAGE-001`,
  `GAP-REDLINE-001`, `GAP-FORM-001`, `GAP-LIST-001`, `GAP-LINK-001`,
  `GAP-BBOX-001`, `GAP-PROVENANCE-001`, `GAP-DIAGNOSTICS-001`, and
  `GAP-SERIALIZATION-001` within the stories' declared scope.

## Stories

1. [P03-US01](stories/P03-US01.md) — Preserve external table captions
2. [P03-US02](stories/P03-US02.md) — Separate visual captions from internal children
3. [P03-US03](stories/P03-US03.md) — Associate source notes and footnotes
4. [P03-US04](stories/P03-US04.md) — Resolve relationship-aware reading order and bboxes
5. [P03-US05](stories/P03-US05.md) — Preserve source-visible redline and text-run semantics
6. [P03-US06](stories/P03-US06.md) — Extract form controls and key-value relationships
7. [P03-US07](stories/P03-US07.md) — Preserve list and legal-clause hierarchy
8. [P03-US08](stories/P03-US08.md) — Separate running regions and printed page identity

Total: 38 story points. P03-US07 and P03-US08 were each re-estimated 3→5 on
2026-08-01 at their independently approved Definition-of-Ready transitions.

## Completed checkpoint

P03-US01 is Done. Exact catastrophe and clinical external table captions pass
at 3/3 reviewed page/text/bbox identities with zero duplicates, complete
relationship/backlink coverage, unchanged table content, exact finance control
parity, bounded fail-closed behavior, and passing independent review. Evidence
is in [P03-US01-verification.md](evidence/P03-US01-verification.md).

P03-US02 is Done with exact 5/5 visual captions, exact catastrophe/Uber
children, zero primary/canonical leaks, bounded raw-provenance and resource
failure behavior, exact component/finance controls, passing frontend and broad
regressions, and independently sealed evidence. Evidence is in
[P03-US02-verification.md](evidence/P03-US02-verification.md).

P03-US03 is Done with exact 8/8 reviewed-note recovery, 14/14 classified
note/control records, five grounded links, zero false associations, passing
paired performance ceilings, exact rollback, frontend compatibility, and
independently sealed final-code evidence. Evidence is in
[P03-US03-verification.md](evidence/P03-US03-verification.md).

P03-US04 is Done with 41/41 reviewed order pairs, side-aware relationship
bundles, exact source-bbox ownership, two bounded source-grounded presentation
corrections, exact rollback, passing paired performance, and independently
sealed final-code evidence. Evidence is in
[P03-US04-verification.md](evidence/P03-US04-verification.md).

P03-US05 is Done with exact 3/3 omission repairs, 6/6 deleted groups, 7/7
group/rule edges, 9/9 deleted run/rule links, 7/7 purchase source composition,
41/41 retained order, complete default-off parity, bounded performance and
resources, frontend compatibility, and independently sealed final-code
evidence. Evidence is in
[P03-US05-verification.md](evidence/P03-US05-verification.md) under the accepted
[text-run policy](decisions/P03-text-run-semantics-policy.md).

P03-US06 is Done with exact ACORD 6-group/42-label/24-field/24-control and
216-relationship output, exact component 3-group/16-pair and 80-relationship
output, zero fabricated values, exact rollback, bounded resources and paired
performance, frontend compatibility, and independently sealed final-code
evidence. Evidence is in
[P03-US06-verification.md](evidence/P03-US06-verification.md) under the accepted
[form/key-value policy](decisions/P03-form-and-key-value-semantics-policy.md).
P03-US07 is Done with exact component 2-group/16-node/32-relationship and
settlement 1-group/3-node/6-relationship output, literal marker/bbox custody,
zero false outlines on reviewed controls, unchanged P03-US06 forms and
P03-US04 41/41 order, strict fail-closed behavior, passing frontend and
resource/performance gates, and independently sealed final-code evidence.
Evidence is in
[P03-US07-verification.md](evidence/P03-US07-verification.md) under the accepted
[outline policy](decisions/P03-outline-structure-policy.md).

P03-US08 is Done with the approved, active, time-bounded
[frontend bbox compatibility renewal](decisions/P03-US08-frontend-bbox-latency-exception-renewal.md).
The original decision and waiver remain immutable historical records. The
reviewed 30-page identity set, 27 detected printed labels and three explicit
nulls, 47 typed running regions, Body/Full projection, strict custody,
fail-closed behavior, frontend contract, and default-off rollback pass. The
exception still applies only to attempt 48's New York timetable projection p95:
0.050946750 seconds against the strict 0.050000000-second ceiling, a 1.8935%
overrun within the requester-authorized 5% candidate-specific boundary.

This closure is **not** a strict current-artifact metrics pass. Attempt 48
remains a failed candidate, the complete companion remains quarantined as
post-seal-invalid, and the canonical strict final artifact is absent. Peak RSS
and every non-latency gate remain unwaived; the companion's 20/20 paired
workers passed both 64 MiB RSS gates and every strict aggregate gate. The
renewed 86-path manifest is
`b5bfab2739f231a57abddf787a6c566c5fddec5b2128bd4892f3682622a06fcc`:
exactly two frontend paths differ from attempt 48 and the other 84 match,
including all measured backend/parser runtime paths. All 29 `app/**` paths are
identical with manifest
`3f60c9b297760cf5fc0b1e89cd0ef02666f35c77ccc474202b80e26915703bb7`.
The renewal is reviewed by 2026-09-02 and expires earlier on any further
required-code custody change, production enablement, or Phase 04 exit. Expiry
or revocation returns P03-US08 to In Progress and blocks dependent exit claims.

Phase exit details are in
[P03-phase-exit-completion.md](reports/P03-phase-exit-completion.md) and
[P03-phase-exit-verification.md](evidence/P03-phase-exit-verification.md). Phase
04 is separately authorized and P04-US01 is In Progress; all later Phase 04
stories remain Proposed.

Hardened superseding renewal (2026-08-03): the requester-authorized chain ends at
[`P03-US08-LATENCY-EXCEPTION-RENEWAL-20260803-PHASE04-TABLES-HARDENED`](decisions/P03-US08-phase04-tables-latency-exception-hardened-renewal.md)
and its
[executable record](evidence/P03-US08-phase04-tables-latency-waiver-hardened-renewal.json),
bound to
[the exact-bundle independent approval](evidence/P03-US08-phase04-tables-hardened-renewal-independent-approval.md),
without changing the earlier decisions, waivers, identities, or observations.
Attempt 48 remains failed at **0.050946750 seconds** against the unchanged
**0.050000000-second** New York projection-p95 ceiling (**0.000946750 seconds /
1.8935%**, within the maximum **5%** candidate-specific bound); its companion
remains quarantined, the canonical strict final remains absent, and this is not
a strict current-artifact metrics pass. The executable record distinguishes
only its structurally sealed, default-off Phase 04 table-only changes: those
changes and Phase 04 exit within the unchanged admitted scope no longer cause
blanket expiry. Any protected running-region semantic/runtime/custody change
or admitted-scope expansion requires a new explicit decision and expires the
renewal before that change; production enablement remains prohibited and
review is due no later than **2026-09-02**. Default-off rollback and all
non-waived RSS, paired/source/Uber latency, correctness, security,
compatibility, custody, resource, output, rollback, and hosted-use gates remain
in force. The preceding “Proposed and unstarted” sentence records the earlier
Phase 03 exit checkpoint; Phase 04 activity is governed by its separately
recorded authorization and story records.

The current development-continuity layer is
[`P03-US08-LATENCY-EXCEPTION-RENEWAL-20260807-PHASE04-TABLES-ADMINISTRATIVE-CONTINUITY`](decisions/P03-US08-phase04-tables-latency-exception-operative-administrative-renewal.md)
with its
[machine-readable semantic classifier](evidence/P03-US08-phase04-tables-latency-waiver-operative-administrative-renewal.json).
It is immediately operative only for semantically unrelated, default-off Phase
04 table development, testing, and evidence. It is not a strict pass,
story-Done, Phase 04 exit, production, hosted-use, or Phase 05 approval. The
attempt-48 observation and ceilings, maximum 5% candidate-specific bound,
sealed attempt-55 history, exact rollback, and every non-waived gate remain
unchanged; the renewal expires before any relevant P03 semantic, runtime, or
custody change and is reviewable no later than 2026-09-02. Its exact
classifier received
[independent policy/custody approval](evidence/P03-US08-phase04-tables-operative-administrative-renewal-independent-review.md)
on 2026-08-07 with all nine required checks passing. That approval covers only
administrative continuity; the exact final-code, story, production/security,
metrics/custody, and Phase 04 exit reviews remain mandatory.
