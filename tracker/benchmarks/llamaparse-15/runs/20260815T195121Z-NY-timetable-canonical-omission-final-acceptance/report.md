# NY timetable cold/warm stage diagnostic

This is diagnostic evidence only. The worker was process-isolated and used the real in-process ASGI application, but the host was not exclusive or quiet. It did not contact ports 8042/8043/3000/3002 and did not open a listener.

The production P04 limits remained 5.000 seconds per document and 0.500 seconds per page; the isolated canonical OCR omission limit remained 2.000 seconds. No production setting or application source file was edited by the run.

## Evidence scope

The original observation is limited to the frontend development log line `POST /api/parse?output_format=json 200 in 315.9s`. That event has no retained response body, stage trace, request timestamp, or code/configuration fingerprint. This controlled run is a current-tree reproduction. A matching stage shape is consistent with an explanation for the earlier event, but cannot prove its root cause retroactively.

## Attempts

| Lane | Status | Wall seconds | CPU seconds | processing.duration_ms | Stable output |
|---|---:|---:|---:|---:|---|
| cold | success | 79.638 | 92.993 | 58720 | `62dd895d9e588bcdf859df19cc4d3cd567c39024a7762a00c88c7f822ef0123e` |
| warm | success | 70.868 | 86.997 | 50376 | `62dd895d9e588bcdf859df19cc4d3cd567c39024a7762a00c88c7f822ef0123e` |

## Interpretation boundaries

- `processing.duration_ms` starts inside `_parse_loaded_document`; it excludes input loading and the outer API/request path and ends before visual semantics, shared-IR projection, canonical construction, terminal alignment/authority, and final response serialization.
- Stage spans are nested. Inclusive stage durations must not be summed. `stage-summary.json` closes the request using the disjoint top-level union plus an explicit residual and gives direct-child-subtracted exclusive values.
- Canonical OCR omission records separate the production function wall from diagnostic pre/post hashing. The enclosing terminal-commit span includes that observer overhead; `pre_capture_wall_ns` and `capture_wall_ns` are retained and never subtracted silently.
- Request CPU includes worker self plus reaped child CPU. Stage supplemental CPU uses the process clock and is not thread-exclusive. Observer overhead is recorded and never subtracted.
- The host retained other applications and both local backend/UI pairs, so this run can identify where this request spent time but cannot establish a clean production latency baseline from one pair.
- The shared latency observer has a repository-wide contract drift for the Office-only `_parse_document_without_stage_telemetry` `ParseResult.model_validate` caller. That branch is unreachable for this PDF. NY attribution remains conditional on the retained invocation counts, parentage, and exact timing closure.

## Pair comparison

- Stable semantic output equal: `True`
- Table row identities equal: `True`
- Canonical identities equal: `True`
- Cold/warm wall ratio: `1.123748`

## Mutation audit

- `app/` unchanged: `True`
- `.models/` path/size/mtime inventory unchanged: `True`
- Pre-run app aggregate: `9c671fbece3ee3828a42745db38073b95a13f2204756cf8aa940aae460bd4caf`
- Post-run app aggregate: `9c671fbece3ee3828a42745db38073b95a13f2204756cf8aa940aae460bd4caf`

See each attempt's `stage-summary.json`, `stage-trace.json`, `supplemental-stage-trace.json`, `observer-manifest.json`, `response.json`, and `host-*.json`; continuous resource evidence is in `resource-samples.ndjson`.
