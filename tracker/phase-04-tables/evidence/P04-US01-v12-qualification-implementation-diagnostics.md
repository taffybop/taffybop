# P04-US01 v12 Qualification Implementation Diagnostics

Date: 2026-08-07  
Scope: noncanonical implementation-test history for the leased-identity and
classified-cadence monitor amendment  
Status: retained diagnostics only; no candidate, canonical campaign, current
metrics pass, or approval

## Purpose and limits

This record preserves every observed result from the first v12 lane
implementation cycle. None of these observations may be removed, relabelled as
a candidate, selected as retained metrics, or used to authorize a real
qualification. The final metrics artifact remains absent. The 1 ms target,
10 ms hard current-RSS gap, fixed 2 ms plus 10% active-CPU bound, and every
other non-waived gate remained unchanged.

## First transitional complete-lane result

The first complete lane test invocation finished with **17 passed, 6 failed,
and 1 known warning**. One failure was a synthetic transcript fixture that
still used the superseded v11 shape. Five real-process controls reached the new
three-second PREPARE qualification and failed closed:

- comprehensive control: qualification cadence failure;
- delayed-PREPARE control: qualification cadence failure;
- zero-second active control: qualification cadence failure, with 606 accepted
  samples and classification `sampling_call_duration`;
- one-millisecond active control: qualification resource/CPU rejection; and
- 100-millisecond active control: qualification cadence failure.

The first terminal output did not surface every sanitized numeric payload, so
this record does not invent them. The result remains a real failed ordinary
test observation, not a discarded warm-up.

## Bounded implementation diagnostics

Two separately executed single real diagnostics retained the following exact
evidence before real execution was stopped:

1. Qualification resource rejection after a complete window:
   - wall `3,005,999,125 ns`;
   - CPU `423,231,000 ns`;
   - duty `140,795 ppm`;
   - unchanged maximum `302,599,912 ns`;
   - 1,851 lease-bound continuous samples;
   - 1,853 target reads;
   - 4 full identity validations; and
   - maximum RSS call `674,584 ns`.
2. Classified cadence rejection:
   - 183 accepted samples;
   - observed gap `16,289,250 ns` against `10,000,000 ns`;
   - scheduler contribution `15,212,625 ns`;
   - sampling-call duration `70,375 ns`;
   - prior accepted maxima `535,875 ns` scheduler and `148,375 ns` read; and
   - retained runtime wall `294,421,541 ns`, CPU `13,836,000 ns`, 184
     lease-bound reads, 185 total reads, and 3 full validations.

The resource diagnostic exposed self-induced evidence-path work: the hot loop
fully validated and deep-copied the same 13-field cadence record twice per
sample and shifted a list-backed timing ring. The correction keeps one
authoritative lane and every retained validator, but constructs the trusted
internal timing record once, uses a fixed `deque(maxlen=32)`, and performs full
strict validation when bounded success/failure evidence is materialized. It
does not change sampling cadence, acceptance, failure classification, RSS
source, or a resource ceiling. Qualification CPU rejection now surfaces the
specific bounded cause `rss_qualification_cpu_exceeded` instead of a generic
operation failure.

## Deterministic correction history

- First post-optimization deterministic/resource slice: **18 passed, 1
  failed, 13 deselected, 1 known warning in 0.61 s**. The single failure was
  message custody only: a mutated lease correctly failed closed as `worker
  lease custody differs` while the test required the sanitized `worker lease
  was lost` category.
- Corrected message-custody rerun: **19 passed, 13 deselected, 1 known warning
  in 0.57 s**.
- Final non-real lane gate: **31 passed, 1 real diagnostic deselected, 1 known
  warning in 3.72 s**.
- Python compilation of both lane files exited zero.

No real qualification was run after the explicit stop. A later real
qualification requires exact-byte independent approval and a separate,
immutable, one-shot diagnostic predeclaration. It may not wait until green or
automatically retry.

## Frozen lane checkpoint

| File | Bytes | SHA-256 |
| --- | ---: | --- |
| `tests/fixtures/phase_04/tables/rss_lane.py` | 154,292 | `f78f2331daf7c47a62d3473981ccd6dd0588b6242714c2bda007caa1bf23ba4e` |
| `tests/performance/test_p04_us01_rss_lane.py` | 52,392 | `28caae754ee9c7981ea2b81aecc0a0ed566c67cb20bb00d6a05348b174355d24` |

This checkpoint is subject only to a concrete integration mismatch; any later
byte change must receive a new identity and cannot rewrite this history.

P04-US01 remains In Progress. P04-US02, P04-US04, and P04-US03 remain
Proposed. This record does not approve production or hosted use, complete
Phase 04, change the operative P03-US08 renewal, or authorize Phase 05.
