# P03-US08 Provisional Latency Exception

Status: Approved, active, and time-bounded  
Decision ID: `P03-US08-LATENCY-EXCEPTION-20260803`  
Owner: Project owner/requester  
Recorded: 2026-08-03  
Review due: 2026-09-02

## Decision

P03-US08 may close as **Done with an approved, time-bounded metrics
exception**. This is not a strict current-artifact pass and does not change the
v1 metrics schema, its global ceilings, or any retained measurement.

The exception applies only to the New York timetable projection p95 in
immutable attempt 48:

- observed: **0.050946750 seconds**;
- strict ceiling: **0.050000000 seconds**;
- overrun: **0.000946750 seconds / 1.8935%**; and
- maximum candidate-specific authorization: **5%**.

The requester explicitly approved a near-boundary latency result on 2026-08-03
and asked that the remaining latency work be completed later. No other failed
gate is waived.

## Evidence bridge

Attempt 48 remains an immutable `failed_measurement_candidate`. Its fail-fast
behavior correctly leaves the paired campaign incomplete, so it is not used to
claim whole-parser or memory acceptance.

The companion post-seal-invalid campaign remains immutable at its quarantine
path. It completed all 20 paired workers and passed every strict gate,
including both latency and 64 MiB RSS gates. Its production/runtime custody is
byte-identical to attempt 48 and the current repository. The only two custody
differences are the benchmark validator and its contract test, changed solely
to fix validation of an already-retained artifact:

- `tests/benchmarks/running_region_metrics.py`; and
- `tests/performance/test_p03_us08_running_region_metrics_contract.py`.

The sealed waiver record binds both candidates, all 55 strict failed attempts,
the exact two-file bridge, default-off rollback, expiry, and zero hosted use:
[P03-US08-provisional-latency-waiver.json](../evidence/P03-US08-provisional-latency-waiver.json).

## Scope and exclusions

Affected fixture: `ny-timetable`.  
Affected consumer: Phase 03 exit adjudication for P03-US08 only.

This exception does **not** waive correctness, quality, security, schema or API
compatibility, allocation, RSS, paired-parser latency, source-extraction
latency, Uber projection latency, resource or deadline boundaries, output
limits, dependency/input/code custody, rollback, or hosted-use gates. It does
not authorize production enablement and it is not reusable by another
candidate, story, or phase.

## Expiry and rollback

The exception expires at the earliest of:

1. 2026-09-02;
2. any parser/runtime custody change;
3. production enablement of running regions; or
4. Phase 04 exit.

Before expiry, replace the exception with a strict current-code final campaign
or renew it through another explicit decision. If it expires or is revoked,
P03-US08 returns to In Progress and dependent exit claims are blocked.

`PARSER_LAYOUT_RUNNING_REGIONS_ENABLED` remains false by default. Setting it to
false is the rollback: the running-region module is not loaded, extraction and
projection are skipped, and the exact configured predecessor is returned.

## Approval record

The requester stated in the active Codex thread:

> latency alone can be fine at the moment - we can work that up later

and clarified that a result very close beyond the border is acceptable for the
moment. This record narrows that approval to the exact 1.8935% attempt-48
observation and preserves every original strict result unchanged.
