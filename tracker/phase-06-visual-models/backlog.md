# Phase 06 Backlog

Release-first completion (2026-08-12): all grounded model stories are complete
against their story-local release criteria and the
[shared policy](../release-first-phases-04-08.md). Mock/test-double end-to-end
flows are sufficient; live model campaigns and hardware qualification are
deferred. Hosted behavior remains off and denied without explicit policy.

| Story | Status | Points | Acceptance summary | Dedicated test path | Dependencies |
|---|---|---:|---|---|---|
| [P06-US01](stories/P06-US01.md) | Done | 5 | Observations reference evidence, distinguish generated/explicit/derived semantics, and cannot overwrite source | `tests/stories/phase_06/test_p06_us01_model_contract.py` | P05-US01 |
| [P06-US02](stories/P06-US02.md) | Done | 5 | Local adapter is optional, bounded, offline, versioned, and license-recorded | `tests/stories/phase_06/test_p06_us02_local_adapter.py` | P06-US01 |
| [P06-US03](stories/P06-US03.md) | Done | 5 | Hosted calls require policy approval, budgets, redaction context, and mockable transport | `tests/stories/phase_06/test_p06_us03_hosted_adapter.py` | P06-US01 |
| [P06-US04](stories/P06-US04.md) | Done | 5 | Only evidenced unresolved visual regions route; complete/non-target regions skip within area and cost limits, while end-to-end latency uses the paired LlamaParse gate | `tests/stories/phase_06/test_p06_us04_routing.py` | P06-US02, P06-US03, P05-US09, P05-US10 |
| [P06-US05](stories/P06-US05.md) | Done | 5 | False captions/identities, unsupported directions, and values without mark/axis/tolerance evidence are rejected | `tests/stories/phase_06/test_p06_us05_grounding.py` | P06-US04, P05-US05 |
| [P06-US06](stories/P06-US06.md) | Done | 5 | Accepted generated evidence retains origin and appears once; every rejection/failure returns deterministic output | `tests/stories/phase_06/test_p06_us06_merge_fallback.py` | P06-US05, P01-US04 |

LlamaParse-15 evidence is tracked under `GAP-VISUAL-001`,
`GAP-CHART-002`, `GAP-DIAGRAM-001`, `GAP-BBOX-001`,
`GAP-PROVENANCE-001`, `GAP-DIAGNOSTICS-001`, and
`GAP-SERIALIZATION-001`. Story points and dependencies are unchanged.

The sole operative latency benchmark for these stories is
[`latency-reference-v1.md`](../benchmarks/llamaparse-15/latency-reference-v1.md).
Local component timings are diagnostic only; timeout, quality, RSS/resource,
security, compatibility, custody/hosted-use, output, cost, default-off, and
rollback gates remain independently blocking.

Release-first implementation is complete. Deferred campaigns and evidence
artifacts remain intentionally absent, and Phase 07 is not started.
