# Phase Latency Backlog

Status: **LAT-US01/LAT-US02 Done with recorded deferrals; LAT-US03–LAT-US08 paused for release-first Phase 04–08 delivery**  
Total: **8 stories, 36 story points**

| Story | Points | Acceptance summary | Dedicated test path | Dependencies | Status |
|---|---:|---|---|---|---|
| [LAT-US01](stories/LAT-US01.md) | 5 | Exact stage/request attribution, failure retention, disabled parity, and reproducible paired benchmark harness | `tests/stories/phase_latency/test_lat_us01_stage_profiler.py` | P00-US10, P01-US04, P02-US06, P03-US08 | **Done — scoped r34 owner exception** |
| [LAT-US02](stories/LAT-US02.md) | 3 | Prewarmed workers validate artifacts/readiness and reuse converters without cross-request state | `tests/stories/phase_latency/test_lat_us02_worker_prewarm.py` | LAT-US01 | **Done — production implementation complete; validation/campaign deferred** |
| [LAT-US03](stories/LAT-US03.md) | 5 | Identical request-scoped page/render/OCR evidence is reused with exact keys and no alternative loss | `tests/stories/phase_latency/test_lat_us03_shared_evidence_context.py` | LAT-US02 | Proposed — paused |
| [LAT-US04](stories/LAT-US04.md) | 5 | Independent page/region/OCR work executes concurrently under deterministic ordering and hard resource bounds | `tests/stories/phase_latency/test_lat_us04_parallel_execution.py` | LAT-US03 | Proposed — paused |
| [LAT-US05](stories/LAT-US05.md) | 3 | Redundant output copies are removed while one strict trust boundary and exact public bytes/errors remain | `tests/stories/phase_latency/test_lat_us05_output_path.py` | LAT-US04 | Proposed — paused |
| [LAT-US06](stories/LAT-US06.md) | 5 | Optional work is skipped only from sufficient source evidence with complete-path fallback on doubt | `tests/stories/phase_latency/test_lat_us06_adaptive_routing.py` | LAT-US05 | Proposed — paused |
| [LAT-US07](stories/LAT-US07.md) | 5 | Bounded prewarmed worker pool improves queue service without unsafe converter sharing or resource exhaustion | `tests/stories/phase_latency/test_lat_us07_worker_pool.py` | LAT-US06 | Proposed — paused |
| [LAT-US08](stories/LAT-US08.md) | 5 | Final production latency flow passes representative end-to-end, compatibility, basic-target, and rollback checks | `tests/stories/phase_latency/test_lat_us08_phase_exit.py` | LAT-US07 | Proposed — paused |

Execution is strictly LAT-US01 → LAT-US02 → LAT-US03 → LAT-US04 → LAT-US05
→ LAT-US06 → LAT-US07 → LAT-US08. Only one story may be In Progress. Every
later story requires its predecessor to be Done, a brief implementation-scope
and dependency check, and separate explicit requester confirmation to proceed;
adding it here is not permission to start it early. After completing each
story, stop and report before starting the next story.

LAT-US01's r34 [conditional completion record](reports/LAT-US01-non-rss-closure-r34.md)
and [scoped owner-exception decision](decisions/LAT-US01-r34-scoped-owner-exception.md)
record completion without rewriting the independent local instrumentation-HWM
failure as a pass. LAT-US02 passed its fresh
[10/10 readiness](evidence/LAT-US02-readiness.md) after separate requester
confirmation. The requester subsequently marked LAT-US02 Done with production
implementation complete and the remaining evidence migration, complete
validation, and campaign explicitly deferred. LAT-US03–LAT-US08 remain
Proposed and still require separate confirmation plus a brief dependency/scope
check. The
[blocked handoff](reports/LAT-US02-blocked-handoff.md) remains the historical
record of zero campaign/hosted use and must not be read as a campaign GO or
phase pass.

P04-US01 may resume under the release-first policy. No latency story authorizes
production enablement.

For LAT-US03–LAT-US08, story completion now prioritizes production code and
basic representative end-to-end validation. Each story must demonstrate its
enabled flow, compatible public behavior, ordinary failure handling,
configured basic bounds, and default-off rollback without a known blocking
functional defect. Hosted/all-corpus campaigns, exhaustive security and
adversarial review, strict performance/RSS qualification, process-lineage, and
evidence-custody proof are deferred to a later hardening phase and are not
story-completion gates. Deferred work must be described accurately and must
not be reported as passed.
