# P03-US08 Verification Evidence

Date: 2026-08-03  
Status: Pass under approved, active, time-bounded latency exception renewal  
Decision: `P03-US08-LATENCY-EXCEPTION-RENEWAL-20260803-FRONTEND-BBOX`  
Review due: 2026-09-02

## Acceptance posture

P03-US08 is Done under a candidate-specific latency exception renewed solely
across the approved frontend bbox compatibility correction. It is **not** a
strict current-artifact metrics pass. The v1 metrics schema, the 5% latency
ceiling, and the 64 MiB RSS ceiling remain unchanged; no additional gate is
waived.

The exception applies only to attempt 48's New York timetable running-region
projection p95:

| Field | Bound value |
|---|---:|
| Target | `ny-timetable` |
| Stage | `running_region_projection` |
| Metric | `latency_p95_seconds` |
| Observed | 0.050946750 seconds |
| Strict ceiling | 0.050000000 seconds |
| Overrun | 0.000946750 seconds |
| Overrun fraction | 1.8935% |
| Maximum candidate authorization | 5% |

No other candidate, metric, target, story, phase, or production-enablement
decision inherits this exception.

## Exact reviewed result

| Contract | Expected | Verified result |
|---|---:|---:|
| Reviewed pages | 30 | 30 exact |
| Source-visible printed labels / explicit nulls | 27 / 3 | 27 / 3 exact |
| Accepted running regions | 47 | 47 exact |
| Header / footer / navigation-top / navigation-bottom | 16 / 30 / 0 / 1 | 16 / 30 / 0 / 1 exact |
| Repeated regions / groups | 28 / 9 | 28 / 9 exact |
| Body / header / footer / Full canonical blocks | 223 / 16 / 31 / 270 | Exact |
| Hosted requests / tokens / cost | 0 / 0 / $0 | 0 / 0 / $0 |

Physical index, embedded label, detected printed label, display fallback, and
running-region evidence remain independent. Uber page 1 retains a null detected
label and its unchanged legacy display fallback; pages 2 and 3 remain visible
positive controls. Body excludes accepted running regions, Full includes each
once in source-proven order, and the fused manufacturing owner has byte-exact
inverse reconstruction.

Strict public/IR/canonical/API contracts, exact source and predecessor
bindings, factory-issued projection authority, physical-only navigation,
bidi-isolated display text, Body/Full selection, and page-scoped
render/source/copy/download parity are enforced. Hostile labels, malformed
reports, forged authority, false body-number/heading candidates, repetition
and ownership conflicts, visibility negatives, resource overflow, and
deadline failures reject or roll back atomically. Repeat projection and
terminal strip/replay are idempotent and fail closed.

## Primary candidate and companion bridge

Attempt 48 remains immutable failed evidence:

- path:
  [P03-US08-running-region-metrics-attempt-48-failed.json](P03-US08-running-region-metrics-attempt-48-failed.json);
- status: `failed_measurement_candidate`;
- size: 158,921 bytes;
- raw SHA-256:
  `1289f186c1cd6ee7f99eaa843f66e5416f15c0215e205e0ed5936737cd2a7123`;
- semantic SHA-256:
  `51433843638d69a2d09ced0d96a44a34323b1f5ece9c890c7c91088bac2df2e5`;
  and
- attempt-48 code-manifest SHA-256:
  `30e6025c3d5f02f2797476cb56ecbdb2349ddc0a57b730fc01e35a9667ce1e3f`.

Its only recorded stage failure is the New York projection p95 above. The
fail-fast path intentionally contains no paired workers or paired samples, so
attempt 48 supplies no whole-parser or RSS acceptance claim.

The complete companion remains immutable and quarantined:

- path:
  [P03-US08-running-region-metrics-attempt-31-post-seal-invalid.json](P03-US08-running-region-metrics-attempt-31-post-seal-invalid.json);
- status retained inside the artifact: `final_measurement_candidate`;
- disposition: post-seal-invalid, not canonical final evidence;
- size: 230,069 bytes;
- raw SHA-256:
  `925f16fcff8bfe54bf20ec40d19e7395ca2fae2e68f8694b49e5c08b65a9ad50`;
- semantic SHA-256:
  `59fe4439b0afbcd99b37c4a19fc006ad436ad623772d007e859ef117561f4fe4`;
  and
- code-manifest SHA-256:
  `5212a1f27a70053ab93b5c6475cbc87e0dd8c6288a0a7f84e3ef40c0d2c1e436`.

The companion completed all 20 paired workers and passed all 21 aggregate
gates, including strict paired latency and both 64 MiB RSS gates. Current code
has the 86-path manifest
`b5bfab2739f231a57abddf787a6c566c5fddec5b2128bd4892f3682622a06fcc`.
It differs from attempt 48 at exactly two authorized frontend paths:

- `frontend/lib/running-regions.ts`; and
- `frontend/tests/p03-us08-running-regions.test.mts`.

The other 84 required paths, including every measured backend/parser runtime
path, match attempt 48. All 29 `app/**` backend paths are identical, with
manifest
`3f60c9b297760cf5fc0b1e89cd0ef02666f35c77ccc474202b80e26915703bb7`;
`measured_backend_parser_runtime_paths_match_original` is true. Current code
differs from the companion at exactly four paths: the two frontend paths above
and the companion's historical evidence validation delta:

- `tests/benchmarks/running_region_metrics.py`; and
- `tests/performance/test_p03_us08_running_region_metrics_contract.py`.

Thus 82/86 required paths match the companion. This exact chained bridge
supports the non-waived gates that attempt 48 did not execute; it does not
convert either candidate into a canonical strict final artifact.

## Non-waived gates

Peak RSS is **not waived**. The exception also does not waive:

- allocation, output sizes, or any deadline/resource boundary;
- paired-parser, source-extraction, or Uber projection latency;
- correctness, quality, security, or API/schema compatibility;
- code, dependency, input, fixture, and predecessor custody;
- rollback or default-off behavior; or
- hosted usage.

The canonical strict-final metrics artifact is absent. Attempt 48 remains
failed; the companion remains post-seal-invalid.

## Sealed renewal, original exception, and failed history

Active machine-readable renewal:
[P03-US08-frontend-bbox-latency-waiver-renewal.json](P03-US08-frontend-bbox-latency-waiver-renewal.json)

Active decision:
[P03-US08-frontend-bbox-latency-exception-renewal.md](../decisions/P03-US08-frontend-bbox-latency-exception-renewal.md)

The active records bind the exact two-file frontend delta, renewed 86-path
manifest, immutable candidate and history identities, original decision and
waiver identities, unchanged exception scope, expiry, rollback, and zero
hosted use. Their final sealed byte identities are recorded by the executable
renewal guard.

The original records remain byte-for-byte immutable historical inputs:

- [P03-US08-provisional-latency-waiver.json](P03-US08-provisional-latency-waiver.json):
  4,873 bytes, raw SHA-256
  `1fe75bc3d749730938653030052d463340eb2e856b810e0586e9afb12e9a72c8`,
  semantic SHA-256
  `0d3cd13942dd465c537dd7075baf0d2e8b30bc5dd891af55622c07f493610554`;
  and
- [P03-US08-provisional-latency-exception.md](../decisions/P03-US08-provisional-latency-exception.md):
  3,476 bytes, raw SHA-256
  `7bea63acad8403e442362edd8aabe0f4db084e6abd0cdd59e2b148b40a8b0d25`.

The sealed failed-history ledger contains attempts 1–55. Its manifest SHA-256
is `bca401f2207619ba84422e020104b9a609e0be0f4dc2b42f3ae4fb53d315ceff`.
Attempts 52–55 are history only and are not the exception basis; the exception
remains bound solely to attempt 48's exact near-boundary observation.

## Test and UI gates

- Active renewal waiver, expiry, history, custody, race, and default-off guard:
  **28/28 passed**, with one pre-existing Starlette warning in **16.88
  seconds**.
- Full focused US08 closeout rerun: **291 passed, 1 expected strict-final
  skip, 1 warning in 65.87 seconds**.
- Frontend Node **24.14.0** lint, typecheck, production build, **106/106 unit
  tests**, and **1/1 bundle test**: **Pass** after the compatibility correction.
- Responsive frontend checks: **22/22 Pass**.
- Hosted use: **0 requests / 0 tokens / $0**.

Warning counts apply only to their named invocation. Automated UI evidence
covers closed-contract validation, O(1) absence handling, physical-only
navigation, bidi-isolated labels, Body/Full selection, rendering,
normalization, source, copy/download, production build, bundle, and responsive
behavior.

Live browser verification passes for `clinical-study.pdf`. The UI shows four
physical pages, printed label `1/21` on the first selected page, and 22
canonical blocks; Body and Full views both work. Public-item bbox `w`/`h`
aliases are accepted only when exactly equal to `width`/`height`, while strict
running-region bboxes continue to reject aliases.

## Expiry and rollback

The active renewal expires at the earliest of:

1. 2026-09-02;
2. any further required-code custody change;
3. production enablement of running regions; or
4. Phase 04 exit.

Before expiry it must be replaced by a strict current-code final campaign or
explicitly renewed. On expiry or revocation, P03-US08 returns to In Progress
and dependent exit claims are blocked.

`PARSER_LAYOUT_RUNNING_REGIONS_ENABLED` remains false by default. Disabling it
prevents loading the running-region module, skips extraction and projection,
and returns the exact configured predecessor. The exception does not authorize
production enablement.

## Hardened superseding renewal — 2026-08-03

Current applicability is governed, only together with fresh independent
approval of the hardened implementation, by
[`P03-US08-LATENCY-EXCEPTION-RENEWAL-20260803-PHASE04-TABLES-HARDENED`](../decisions/P03-US08-phase04-tables-latency-exception-hardened-renewal.md)
and
[P03-US08-phase04-tables-latency-waiver-hardened-renewal.json](P03-US08-phase04-tables-latency-waiver-hardened-renewal.json).
The decision identity is **10,763 bytes**, raw SHA-256
`4cbc9e63fbf4124744f710b8a6d9bf40aa25d600d802a54fc1cb8657f36db19e`.
The executable record identity is **14,614 bytes**, raw SHA-256
`0583643f4a140e6cd452cd5430785621347cce941de093a60aecf97cb5cde85c`,
semantic SHA-256
`33721223b119ba1f2f62c696f03053d244bf5c2c131ae0b42e8290939000ef90`.
The record renews the frontend-bbox renewal and preserves every earlier
identity, attempt, manifest, result, ceiling, and status. In particular, the
failed-history manifest remains
`bca401f2207619ba84422e020104b9a609e0be0f4dc2b42f3ae4fb53d315ceff`.

Attempt 48 therefore remains failed for `ny-timetable` /
`running_region_projection` / `latency_p95_seconds`: **0.050946750 seconds**
observed against the unchanged **0.050000000-second** strict ceiling, an
overrun of **0.000946750 seconds / 1.8935%** under the unchanged maximum **5%**
candidate-specific bound. The companion remains quarantined, canonical
strict-final evidence remains absent, and this remains explicitly not a strict
current-artifact metrics pass.

Only default-off Phase 04 table paths and protected functions enumerated by
the executable record may differ. Table-only changes admitted and structurally
sealed there, and Phase 04 exit within that exact scope, do not trigger the
former blanket required-code/Phase-04-exit expiry. A protected running-region
semantic/runtime/custody change or any admitted-scope expansion requires a new
explicit decision and expires the renewal before the change. Production
enablement remains prohibited; review is due no later than **2026-09-02**.
`PARSER_LAYOUT_RUNNING_REGIONS_ENABLED=false` remains the exact-predecessor
rollback. RSS, paired-parser/source-extraction/Uber latency, correctness,
security, API/schema compatibility, dependency/input/fixture/code custody,
resource/deadline, output-size, rollback, and hosted-use gates remain unwaived.
