# LAT-US02 production campaign blocked: Darwin request-CPU lineage cannot be proven complete

Date: 2026-08-10  
Finding: `LAT-US02-METRIC-CPU-001`  
Severity: **Major**  
Disposition: **NO-GO — keep LAT-US02 In Progress; do not launch the local
production campaign**

## Blocking authority

The [phase metrics contract](../metrics.md) requires request-boundary CPU from
exact counters, recomputed per process. Missing, rounded, sampled-late, or
post-validation-contaminated CPU evidence blocks. The requester-directed
[LAT-US02 numerical RSS deferral](../decisions/LAT-US02-owner-directed-rss-deferral.md)
applies only to numerical RSS; it does not waive CPU completeness, process
lineage, cleanup, orphaning, or other reliability controls.

The frozen adapter combines worker `RUSAGE_SELF`/`RUSAGE_CHILDREN` aggregates
with before/after snapshots of descendants that are still live. A native child
or grandchild that is short-lived, reparented, or reaped between those edges can
lack a retained `(pid, create_time_ns)` CPU row or tombstone without forcing
`cumulative_contamination_detected=true`. The evaluator can therefore accept an
aggregate whose owned lineage is incomplete. Float-valued `getrusage` and
`psutil` counters are also converted to nanoseconds; they are not an
independent exact per-process ledger.

## Reproduced Darwin gaps

Independent host controls reproduced all of the following:

- an exited zombie contributed zero to root `RUSAGE_CHILDREN` until `wait()`,
  then advanced it by approximately `0.251` seconds;
- a live direct child that spawned and waited a CPU-busy grandchild exposed
  only about `0.0012` seconds in its own `psutil` CPU while the root aggregate
  advanced by about `0.323` seconds only after that child exited and was
  waited; and
- an unwaited/orphaned grandchild consumed about `0.3`–`0.4` seconds while the
  root retained only about `0.0006` seconds for the intermediate child.

These controls prove that edge snapshots plus root child rusage can silently
omit owned native work. A passing adapter fixture likewise permits a peak
process count of two while retaining only the root CPU identity.

## Exhausted in-scope alternatives

- Nested Seatbelt cannot be applied inside the retained outer worker sandbox;
  the exact host returns `sandbox_apply: Operation not permitted`.
- The current Darwin SDK states that recursive kqueue `NOTE_TRACK`,
  `NOTE_TRACKERR`, and `NOTE_CHILD` process tracking has been unsupported since
  macOS 10.5. `NOTE_FORK` alone has a child-registration race.
- DYLD interposition, Python audit hooks, Mach-O import scans, and sampled
  process-tree reconciliation are bypassable by native/direct-syscall or
  runtime-loaded code and cannot be represented as kernel-authoritative
  completeness.
- A hard `RLIMIT_NPROC=0` exec wrapper can prevent Tesseract descendants, but it
  cannot prevent or completely observe raw native forks from the Python worker
  while that worker must retain authority to start Tesseract.

The remaining authoritative designs materially expand the approved story:
permanent worker fork denial plus an external Tesseract broker with
request-scoped `wait4`/rusage and quiescence custody, privileged EndpointSecurity
lineage, or an equivalent VM/container/kernel accounting boundary. None is
authorized by LAT-US02's no-process-architecture scope.

## Frozen custody at the stop boundary

- application identity:
  `4c75f9384e298a65adab275ec3a12df8088af2db84064e1a99c3e9931f4a53ed`
- dependency-manifest identity:
  `0253ae6df39a044b66d2b10d1a486841c7a25b2b1225e9a6aee2b6bf3016a2dc`
- runtime-dependency identity:
  `1801756d928fdb92825663653b8c7d87a39c2d5cb9563dcad614c12aef8c299b`
- parser-runtime identity:
  `542c879fdc2cfe0be223e4729082bac529780d90c6d811c853de852765b35a35`
- LAT-US02 harness identity:
  `4c1094e4558311908e4eccc29eb987abad312405428a0e1abf7b2b08ee35c750`
- approved artifact content identity:
  `7da24e7a135b1f0c66048fb552c5dce4d41bc328daf9e86670f435203dad09d4`
  (`56` files; `563,549,064` bytes; no symlinks)

No LAT-US02 production campaign directory, attempt receipt, evaluation,
completion report, ASGI campaign, hosted call, credit use, or provider egress
exists. There was no failed measurement to retry and no numerical RSS result to
select.

## Required resume gate

Resume only after the requester explicitly authorizes an architecture that
provides non-bypassable worker-group birth/exit lineage, exact native
per-process counters, reaped-process tombstones, request-edge quiescence, and
fail-closed missing/rounded/late evidence. The replacement must cover
short-lived children and grandchildren, reparenting, PID reuse, counter
regression, observation errors, and cleanup; then refreeze all identities and
obtain fresh production/security and metrics/custody approval before the one
permitted campaign.

LAT-US03 and every later story remain Proposed.
