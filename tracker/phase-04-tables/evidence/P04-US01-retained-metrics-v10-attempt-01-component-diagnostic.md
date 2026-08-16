# P04-US01 v10 Attempt-01 Component-Reachability Diagnostic

Date: 2026-08-07  
Status: diagnostic only; not a pass and not canonical evidence  
Cause under diagnosis: `worker table-stage component measurement differs`

After canonical v10 attempt 01 was sealed failed, two one-worker
`ny-timetable` diagnostics ran against the same frozen code. Only the parent
`_validate_snapshot` call was replaced with a no-op inside the disposable
diagnostic controller process so the already-canonical raw worker snapshot
could be printed. Worker production execution, instrumentation, external
monitoring, output generation, offline mode, cleanup, and worker diagnostic
checks were unchanged. These runs cannot satisfy a gate.

Exact flag-off bounded output:

```json
{"case_id":"ny-timetable","enabled":false,"table_stage_call_count":7,"table_stage_components":{"budget_finish":{"call_count":1,"elapsed_seconds":2.75e-06},"budget_start":{"call_count":0,"elapsed_seconds":0.0},"docling_projection":{"call_count":3,"elapsed_seconds":0.010029875},"document_custody_transaction":{"call_count":0,"elapsed_seconds":0.0},"finalize_replay":{"call_count":0,"elapsed_seconds":0.0},"parse_result_custody":{"call_count":1,"elapsed_seconds":1.0542e-05},"repair_extraction":{"call_count":1,"elapsed_seconds":0.001035417},"seal":{"call_count":1,"elapsed_seconds":1.875e-06},"table_transaction_detach":{"call_count":0,"elapsed_seconds":0.0},"table_transaction_rebind":{"call_count":0,"elapsed_seconds":0.0},"terminal_authority":{"call_count":0,"elapsed_seconds":0.0}},"table_stage_seconds":0.011080459,"wall_seconds":48.255870292,"worker_stderr_bytes":0,"worker_stdout_bytes":0}
```

Exact flag-on bounded output:

```json
{"case_id":"ny-timetable","enabled":true,"table_stage_call_count":8,"table_stage_components":{"budget_finish":{"call_count":1,"elapsed_seconds":2.334e-06},"budget_start":{"call_count":1,"elapsed_seconds":5.541e-06},"docling_projection":{"call_count":3,"elapsed_seconds":0.871726584},"document_custody_transaction":{"call_count":0,"elapsed_seconds":0.0},"finalize_replay":{"call_count":0,"elapsed_seconds":0.0},"parse_result_custody":{"call_count":1,"elapsed_seconds":1.2542e-05},"repair_extraction":{"call_count":1,"elapsed_seconds":0.000980625},"seal":{"call_count":1,"elapsed_seconds":0.081073333},"table_transaction_detach":{"call_count":0,"elapsed_seconds":0.0},"table_transaction_rebind":{"call_count":0,"elapsed_seconds":0.0},"terminal_authority":{"call_count":0,"elapsed_seconds":0.0}},"table_stage_seconds":0.953800959,"wall_seconds":48.644693333,"worker_stderr_bytes":0,"worker_stdout_bytes":0}
```

The flag-off topology is exact: all five always-reachable components ran and
all six enabled-only components were zero. In the flag-on topology,
`budget_start` ran, while the five transaction/authority/replay components were
not applicable and remained zero. Their zero time/count is truthful, not
missing elapsed work. The v10 validator nevertheless required all enabled-only
components to have a positive call count, causing the canonical failure.

The correction must not claim complete named-stage coverage. It must keep the
paired whole-parser guard, exact component sum/count validation, all five
always-reachable hooks, enabled `budget_start`, flag-off zero enforcement, and
all ceilings/non-waived gates. Any correction is a new schema/design and cannot
relabel or retry v10 attempt 01.
