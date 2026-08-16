# P04-US01 Conditional Stage-Reachability Final-Code Amendment

Date: 2026-08-07  
Story: P04-US01  
Scope: test-only retained-metrics validation and evidence custody; no
production-path change  
Status: Accepted only with a separate independent approval bound to the exact
final-code bytes

## Decision

The sealed P04-US01 retained-metrics `v10` attempt 01 failed closed before it
could produce a final artifact. Its unchanged failure is recorded at
`tracker/phase-04-tables/evidence/P04-US01-retained-metrics-v10-attempt-01-failed.json`.
The bounded post-failure diagnostic established that the validator incorrectly
treated every enabled-only instrumentation hook as necessarily reachable.

The production-shaped `ny-timetable` observations were:

- flag off: seven calls and `0.011080459` measured seconds; the five
  always-reachable hooks ran and all six enabled-only hooks were zero;
- flag on: eight calls and `0.953800959` measured seconds; the same five
  always-reachable hooks ran, `budget_start` ran, and the five transaction,
  authority, and replay hooks were truthfully zero because those branches were
  not applicable to that document.

This amendment corrects only that reachability predicate. Current validation
requires a positive call count for the five always-reachable components:
`repair_extraction`, `docling_projection`, `seal`, `budget_finish`, and
`parse_result_custody`. It additionally requires `budget_start` when the Phase
04 table flag is enabled. The five hooks `table_transaction_detach`,
`terminal_authority`, `document_custody_transaction`,
`table_transaction_rebind`, and `finalize_replay` are conditional when enabled:
they may be exactly zero when the corresponding production branch is not
reached. All six enabled-only hooks remain forbidden when the flag is off.

Every component record remains mandatory. A zero call count still requires
exactly zero elapsed seconds; all elapsed values and call counts remain bounded;
the exact component elapsed sum and call-count sum must equal their snapshot
totals. The report continues to declare that named table-stage coverage is
incomplete and retains the paired whole-parser p50/p95 guard for unmeasured
work. Conditional reachability therefore does not discard elapsed work or
relax the latency formula.

## Schema and lineage

The correction is a new design, not a relabel or retry of `v10`:

- report `p04-us01-table-metrics-v11`;
- semantic projection `p04-us01-final-metrics-semantic-projection-v11`;
- paired performance `p04-us01-paired-performance-v10`; and
- quality evidence `p04-us01-quality-evidence-v7`.

The external monitor attestation remains
`p04-us01-external-rss-monitor-attestation-v7`; external observer remains
`p04-us01-controller-observer-process-v2`; execution accounting remains
`p04-us01-execution-accounting-v3`; lane protocol custody remains
`p04-us01-current-rss-lane-protocol-custody-v4`; and lane runtime remains
`p04-us01-current-rss-lane-runtime-v2`. All earlier report/projection/paired/
quality schemas are rejected for a current retained artifact. The sealed v10
predeclaration, stderr transcript, failure record, and diagnostic remain
historical evidence and must not be changed or represented as a pass.

The independent approval for these exact final-code bytes is an explicit
upstream final-code input at
`tracker/phase-04-tables/evidence/P04-US01-conditional-stage-reachability-final-code-amendment-independent-review.md`.
It is excluded only from downstream evidence discovery to keep the custody
graph acyclic. No candidate or canonical v11 campaign may begin until that
approval is complete and every required final-code identity is frozen.

During pre-approval ordinary verification, the dedicated lane module exposed
an order-dependent failure in its delayed-PREPARE test. That control passed in
isolation but its unnecessary active sampling phase failed the unchanged
active-CPU custody bound after another real lane. Bounded diagnostic splits
proved that cadence, target-read duration, descriptors, and identity were not
the cause; a one-second diagnostic observed `176,011,000 ns` active CPU over
`1,010,282,958 ns` active wall against the exact `103,028,295 ns` bound and
correctly failed closed. All temporary diagnostic code was then removed.

The control's governed purpose is to prove that PREPARE may idle beyond the
two-second lane timeout without busy looping and without losing responsiveness,
protocol custody, or lifecycle cleanup. It now observes the prepared lane's
process CPU across the full idle, requires that CPU to remain within the same
fixed-plus-rate arithmetic, issues a real target READ, and terminates through
the protocol ABORT path with exact operation and lifecycle validation. Exact
0 ms, 1 ms, and 100 ms active-window controls remain independently mandatory.
The fixed 2 ms plus 10% active-wall CPU formula, exact-bound/+1 arithmetic,
1 ms RSS target, 10 ms hard gap, and all lifecycle/resource validation remain
unchanged. The initial ordinary test failures and diagnostics were neither a
candidate nor a canonical campaign and created no retained artifact or pass
claim.

A later complete ordinary-module verification also failed closed once in the
unchanged real external-monitor delayed-PREPARE control: one continuous sample
gap was `12,069,250 ns` against the unchanged `10,000,000 ns` hard maximum
after 32 accepted samples. The remaining result was 396 passed, two expected
real-campaign skips, one pressure-candidate deselection, and one known warning.
The exact control then passed in isolation with no code, threshold, cadence,
or scheduler change. This is preserved as an ambient fail-closed observation,
not discarded or represented as a pass; it is not a candidate or canonical
campaign. A clean complete ordinary result on the frozen exact bytes remains a
precondition to independent approval and any v11 campaign.

## Gates and boundaries

The three performance cases, five pairs, quality cases, `0.10` table-stage and
whole-parser latency ceilings, `67,108,864`-byte paired RSS ceiling, 1 ms
current-RSS target, 10 ms hard current-RSS gap, 25 ms child target, 100 ms hard
child gap, output limits, deadlines, correctness, security, compatibility,
custody, resource, rollback, corpus, deterministic, diagnostic, and hosted-use
gates are unchanged and non-waived. The operative P03-US08 administrative
renewal and its exact attempt-48 observation, ceilings, maximum 5% bound,
default-off rollback, review date, expiry conditions, and all non-waived gates
remain unchanged.

This amendment changes no production code, configuration default, output,
custody behavior, or hosted use. A failed v11 candidate or canonical attempt
must be sealed and cannot be silently retried under the same design. This
amendment is not a current-artifact metrics pass, P04-US01 completion, Phase 04
exit, production enablement, or authority for Phase 05.
