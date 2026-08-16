# P03-US08 Frontend Bbox Compatibility Latency Exception Renewal

Status: Approved, active, and time-bounded  
Decision ID: `P03-US08-LATENCY-EXCEPTION-RENEWAL-20260803-FRONTEND-BBOX`  
Renews: `P03-US08-LATENCY-EXCEPTION-20260803`  
Owner: Project owner/requester  
Recorded: 2026-08-03  
Review due: 2026-09-02

## Decision

The requester renews the P03-US08 latency exception solely across the
frontend bbox compatibility correction required to display a valid parser
response. The correction accepts the established `w` and `h` bbox aliases
only when they exactly match `width` and `height`; strict running-region bbox
validation remains fail-closed.

The only authorized current-code differences from immutable attempt 48 are:

- `frontend/lib/running-regions.ts`: 49,506 bytes / SHA-256
  `73bad8a2ac6ce143ae69f9dc50dc61e955a42c56f0f8476d8bba12de3edf786d`
  to 50,738 bytes / SHA-256
  `1dfac1d71e34136267e2a1432261510b5785ac06a1c001da737eda27129be7af`;
  and
- `frontend/tests/p03-us08-running-regions.test.mts`: 33,483 bytes / SHA-256
  `20772d1f5a34b4c3834af6b4dea5becacbf91cac33f60dca41bf7ed4fef3549d`
  to 34,495 bytes / SHA-256
  `f6ab8b7c2ebaf6a8dd2cd58febb90b0647a7223017481042e6ba7d20fbb93ffc`.

All other 84 required custody paths, including every measured backend/parser
runtime path, remain byte-identical to attempt 48. The attempt-48 code
manifest remains
`30e6025c3d5f02f2797476cb56ecbdb2349ddc0a57b730fc01e35a9667ce1e3f`;
the renewed 86-path manifest is
`b5bfab2739f231a57abddf787a6c566c5fddec5b2128bd4892f3682622a06fcc`.

## Preserved exception and evidence

This renewal retains exactly the original candidate-specific observation:

- target: `ny-timetable`;
- stage: `running_region_projection`;
- metric: `latency_p95_seconds`;
- observed: **0.050946750 seconds**;
- strict ceiling: **0.050000000 seconds**;
- overrun: **0.000946750 seconds / 1.8935%**; and
- maximum candidate-specific authorization: **5%**.

Attempt 48, the quarantined complete companion, all 55 failed-history
artifacts, the original decision, and the original waiver remain immutable.
No benchmark is relabeled and no canonical strict-final artifact is created.
The executable renewal record binds their original identities:
[P03-US08-frontend-bbox-latency-waiver-renewal.json](../evidence/P03-US08-frontend-bbox-latency-waiver-renewal.json).

## Scope, exclusions, expiry, and rollback

This renewal does not waive any additional metric, correctness, quality,
security, API/schema compatibility, allocation, memory/RSS, paired-parser
latency, source-extraction latency, Uber projection latency, resource or
deadline boundary, output-size, dependency/input/fixture custody, rollback,
or hosted-use requirement. It does not authorize production enablement.

The review date remains 2026-09-02. The renewal expires earlier upon any
further required-code custody change, production enablement of running
regions, or Phase 04 exit. Expiry or revocation returns P03-US08 to In Progress
and blocks dependent exit claims.

`PARSER_LAYOUT_RUNNING_REGIONS_ENABLED` remains false by default. Disabling
the flag remains the exact rollback to the configured predecessor.

## Approval record

The requester stated in the active Codex thread on 2026-08-03:

> I approve renewing the P03-US08 latency exception for this frontend-only bbox compatibility fix, retaining the same 1.8935% latency exception, 2026-09-02 review date, default-off rollback, and no other waivers.

