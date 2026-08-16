# P04-US01 Current-v10 Real Postal Smoke Result

Date: 2026-08-07  
Status: **PASS — noncanonical, non-retained one-case smoke**

Predeclaration: `P04-US01-current-v10-real-postal-smoke-predeclaration.md`  
Predeclaration size: 1,281 bytes  
Predeclaration SHA-256: `4338332d9c203c5d91d6e6e1a43ade11222e72e84109fdf8d8d60bd3e8499439`

The exact `metrics.fresh_snapshot(workspace, "postal-10k", True)` command ran
offline in a fresh worker with real process observation and exited `0` in
`28.94636625` command seconds. It did not target or write the retained final
metrics path.

Exact bounded stdout JSON:

```json
{"attestation_schema_id":"p04-us01-external-rss-monitor-attestation-v7","case_id":"postal-10k","document_sidecar_bytes":211603,"enabled":true,"lane_active_cpu_duration_ns":101131000,"lane_active_cpu_duty_ppm":36625,"lane_active_wall_duration_ns":2761192209,"lane_compressed_bytes":12203,"lane_duplex_bytes":334530,"lane_exchange_count":447,"lane_identity":[89244,1786056728376802816],"lane_protocol_schema_id":"p04-us01-current-rss-lane-protocol-custody-v4","lane_runtime_schema_id":"p04-us01-current-rss-lane-runtime-v2","maximum_marked_table_bytes":151076,"observer_identity":[89243,1786056728118516992],"peak_rss_bytes":1237417984,"phase04_stage_child_boundary_check_count":50,"phase04_stage_child_observer_continuous_maximum_gap_ns":38834375,"phase04_stage_child_observer_sample_count":98,"phase04_stage_children_rusage_unchanged":true,"phase04_stage_current_rss_baseline_bytes":1097154560,"phase04_stage_current_rss_end_bytes":1031487488,"phase04_stage_current_rss_peak_bytes":1131888640,"phase04_stage_peak_rss_increment_bytes":34734080,"phase04_stage_rss_child_processes_observed":0,"phase04_stage_rss_continuous_maximum_gap_ns":1936500,"phase04_stage_rss_continuous_sample_count":2022,"phase04_stage_rss_synchronous_sample_count":50,"table_stage_seconds":1.116322291,"wall_seconds":23.9180735,"worker_identity":[89242,1786056728062733056],"worker_stderr_bytes":0,"worker_stdout_bytes":0}
```

The v7 attestation and v4 full transcript validated, the 10 ms RSS and 100 ms
child gaps passed, active CPU was within the fixed-plus-rate bound, child
rusage was unchanged, no child process was observed, and worker stdout/stderr
were empty. The absolute process RSS is observational. The single enabled
`34,734,080`-byte candidate-window increment is not paired and cannot satisfy
or replace the `67,108,864`-byte paired gate.

No canonical campaign, retained metrics artifact, current metrics pass, story
completion, production approval, Phase 04 exit, or Phase 05 authorization is
created or claimed.
