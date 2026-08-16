# NY timetable cold/warm stage diagnostic

This is diagnostic evidence only. The worker was process-isolated and used the real in-process ASGI application, but the host was not exclusive or quiet. It did not contact ports 8042/8043/3000/3002 and did not open a listener.

The production P04 limits remained 5.000 seconds per document and 0.500 seconds per page. No production setting or application source file was edited by the run.

## Evidence scope

The original observation is limited to the frontend development log line `POST /api/parse?output_format=json 200 in 315.9s`. That event has no retained response body, stage trace, request timestamp, or code/configuration fingerprint. This controlled run is a current-tree reproduction. A matching stage shape is consistent with an explanation for the earlier event, but cannot prove its root cause retroactively.

## Attempts

| Lane | Status | Wall seconds | CPU seconds | processing.duration_ms | Stable output |
|---|---:|---:|---:|---:|---|
| cold | success | 336.839 | 346.110 | 55066 | `c98405549392aa6512928113e0d25c8a757f200972cda4be505c96633587afce` |
| warm | success | 322.286 | 334.191 | 47091 | `c98405549392aa6512928113e0d25c8a757f200972cda4be505c96633587afce` |

## Root-cause finding on the controlled current tree

The reproduced slowdown is dominated by item-wise visual source-text recovery:

| Stage evidence | Cold | Warm |
|---|---:|---:|
| `pipeline.visual_semantics` | 273.623 s | 267.314 s |
| `visual.recover_pdf_visual_source_text` | 273.458 s | 267.156 s |
| Recovery calls | 1,778 | 1,778 |
| Recovery share of request | 81.18% | 82.89% |
| Recovery share of visual stage | 99.94% | 99.94% |
| `_declared_visual_kind` calls/time | 1,778 / 0.011 s | 1,778 / 0.010 s |

The 1,778 recovery calls exactly equal the 1,778 response items: 1,745 text items, 27 headings, three tables, and three footers. The response has zero image, chart, or diagram items.

The current call order explains the cost. `apply_visual_semantics` iterates every item at `app/services/visual_semantics.py:967`; for PDF input it calls `recover_pdf_visual_source_text` at lines 992–1003 and only then calls `_declared_visual_kind` at line 1015. Each recovery opens the PDF at `app/services/visual_source_text.py:1904` and calls `page.extract_words` at line 1913. Consequently, a cheap eligibility rejection follows an expensive full-page word extraction for every non-visual item.

The supplemental wrapper calibration was 131,750 ns across 64 cold no-op calls (about 2.06 microseconds/call) and 118,458 ns across 64 warm calls (about 1.85 microseconds/call). No correction was subtracted. Even multiplying the higher value by 1,778 gives about 3.66 ms, negligible beside 273.46 seconds.

Alternative stage evidence does not support the earlier hypotheses:

- Rendered OCR planned and executed three page requests and six PSM 3/11 Tesseract passes per attempt. All succeeded in 13.70–13.93 seconds total; there were no 30-second timeouts.
- Docling conversion was 35.42 seconds cold and 27.49 seconds warm. Converter reuse saved about 7.93 seconds, but the warm request remained 322.29 seconds because the 267.16-second recovery loop repeated.
- JSON encoding, public validation, model dump, and response construction together were 0.447 seconds cold and 0.329 seconds warm.
- P04 retained its 5.000-second document and 0.500-second page limits. Terminal table authority had zero invocations and the separately observed custody-validator implementation was below 1 ms. P04 is not the source of the 267–273 second visual loop.

This establishes the root cause for this controlled current-tree run. It is strongly consistent with the earlier 315.9-second frontend observation, but the earlier event remains unattributable by itself because it lacks retained stage/configuration evidence.

## Interpretation boundaries

- `processing.duration_ms` starts inside `_parse_loaded_document`; it excludes input loading and the outer API/request path and ends before visual semantics, shared-IR projection, canonical construction, terminal alignment/authority, and final response serialization.
- Stage spans are nested. Inclusive stage durations must not be summed. `stage-summary.json` closes the request using the disjoint top-level union plus an explicit residual and gives direct-child-subtracted exclusive values.
- Request CPU includes worker self plus reaped child CPU. Stage supplemental CPU uses the process clock and is not thread-exclusive. Observer overhead is recorded and never subtracted.
- The host retained other applications and both local backend/UI pairs, so this run can identify where this request spent time but cannot establish a clean production latency baseline from one pair.
- The shared latency observer has a repository-wide contract drift for an Office-only `ParseResult.model_validate` caller at `pipeline.py:10745`. That branch is unreachable for this PDF. NY attribution remains conditional on the retained invocation counts, parentage, and exact timing closure.

## Pair comparison

- Stable semantic output equal: `True`
- Table row identities equal: `True`
- Canonical identities equal: `True`
- Cold/warm wall ratio: `1.045157`

## Mutation audit

- `app/` unchanged: `True`
- `.models/` path/size/mtime inventory unchanged: `True`
- Pre-run app aggregate: `85862015f03d1d8e284d6b3b1448604f0c83e32da2e5e49bdd67edc193d2fd7f`
- Post-run app aggregate: `85862015f03d1d8e284d6b3b1448604f0c83e32da2e5e49bdd67edc193d2fd7f`

See each attempt's `stage-summary.json`, `stage-trace.json`, `supplemental-stage-trace.json`, `observer-manifest.json`, `response.json`, and `host-*.json`; continuous resource evidence is in `resource-samples.ndjson`.
