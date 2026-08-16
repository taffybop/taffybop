# P03-US08 Phase 04 Tables Latency Exception Renewal

Status: Approved, active, and time-bounded  
Decision ID: `P03-US08-LATENCY-EXCEPTION-RENEWAL-20260803-PHASE04-TABLES`  
Renews: `P03-US08-LATENCY-EXCEPTION-RENEWAL-20260803-FRONTEND-BBOX`  
Owner: Project owner/requester  
Recorded: 2026-08-03  
Review due: 2026-09-02

## Decision

The requester authorizes a narrow administrative renewal of the existing
P03-US08 latency exception so that unrelated, default-off Phase 04 table work
may change its explicitly bounded production, configuration, frontend, and
test surfaces without being misclassified as a running-region change.

This renewal is chained to, and does not rewrite, the immutable original
exception or frontend-bbox renewal. It permits only the Phase 04 table paths
and protected table functions named by the executable renewal record. Shared
files remain guarded structurally: configuration differences may add only the
four `table_*` settings and their validation/environment bindings; pipeline
differences may affect only the five named table construction/reconciliation
functions; and frontend differences may affect only the table renderer plus
its exact Phase 04 helper import. Every other original required-code surface,
including the complete running-region implementation, IR, API model,
presentation, serializer, frontend running-region validator, and P03-US08
tests, remains custody-locked.

Adding a Phase 04 path to the allowed set, changing a protected shared-file
surface, or changing running-region semantics/runtime/custody requires a new
explicit decision and expires this renewal before that change.

## Preserved observation and ceilings

The sole accepted observation remains immutable attempt 48:

- target: `ny-timetable`;
- stage: `running_region_projection`;
- metric: `latency_p95_seconds`;
- observed: **0.050946750 seconds**;
- strict ceiling: **0.050000000 seconds**;
- overrun: **0.000946750 seconds / 1.8935%**; and
- maximum candidate-specific authorization: **5%**.

Attempt 48 remains failed. The strict ceiling is unchanged, the canonical
strict-final artifact remains absent, and no Phase 03 result may be described
as a strict current-artifact metrics pass. The failed history remains sealed
at 55 artifacts with manifest
`bca401f2207619ba84422e020104b9a609e0be0f4dc2b42f3ae4fb53d315ceff`.

## Non-waived gates

This renewal waives no RSS, allocation, paired-parser latency, source
extraction latency, Uber projection latency, correctness or quality, security,
API/schema compatibility, dependency/input/fixture or code custody, resource
or deadline boundary, output-size, rollback, or hosted-use gate. It does not
authorize production enablement, hosted model use, a broader latency bound, a
new benchmark observation, or any Phase 05 work.

## Expiry and rollback

The record is reviewable no later than 2026-09-02 and expires before:

- production enablement of running regions;
- any running-region semantic or runtime behavior change;
- any relevant running-region custody change outside the structurally bounded
  Phase 04 table surfaces; or
- any expansion of the authorized Phase 04 path/function set.

Expiry or revocation returns P03-US08 to In Progress and blocks dependent exit
claims until strict current-code evidence or another explicit decision exists.
`PARSER_LAYOUT_RUNNING_REGIONS_ENABLED` remains false by default; disabling it
still performs zero P03-US08 work and returns the exact configured predecessor.
Each Phase 04 table flag is independently default-off and is not part of the
P03-US08 latency exception.

## Approval record

The requester stated in the active Codex thread on 2026-08-03:

> I also authorize the narrow administrative renewal of the existing P03-US08 latency exception required to permit unrelated Phase 04 table changes. The renewal must preserve the exact attempt-48 latency observation, unchanged ceilings, maximum 5% candidate-specific bound, default-off rollback, and every non-waived gate.

The complete instruction further requires review no later than 2026-09-02 and
expiry before production enablement or any relevant running-region
behavior/custody change; those terms are incorporated above and enforced by
the executable record.
