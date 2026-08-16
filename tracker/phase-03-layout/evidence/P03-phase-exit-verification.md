# Phase 03 Exit Verification Evidence

Date: 2026-08-03  
Status: Pass with approved, active, time-bounded metrics exception renewal  
Phase: Layout — 8/8 stories, 38/38 points Done

## Evidence identity

| Record | Identity |
|---|---|
| Active renewal decision | [`P03-US08-LATENCY-EXCEPTION-RENEWAL-20260803-FRONTEND-BBOX`](../decisions/P03-US08-frontend-bbox-latency-exception-renewal.md); final byte identity is enforced by the executable renewal guard |
| Active executable renewal | [Frontend bbox latency waiver renewal](P03-US08-frontend-bbox-latency-waiver-renewal.json); final byte and semantic identities are enforced by the executable renewal guard |
| Original exception decision | Immutable historical record; 3,476 bytes; SHA-256 `7bea63acad8403e442362edd8aabe0f4db084e6abd0cdd59e2b148b40a8b0d25` |
| Original executable waiver | Immutable historical record; 4,873 bytes; raw SHA-256 `1fe75bc3d749730938653030052d463340eb2e856b810e0586e9afb12e9a72c8`; semantic SHA-256 `0d3cd13942dd465c537dd7075baf0d2e8b30bc5dd891af55622c07f493610554` |
| Renewed required-code custody | 86 paths; manifest SHA-256 `b5bfab2739f231a57abddf787a6c566c5fddec5b2128bd4892f3682622a06fcc`; 84/86 paths match attempt 48 |
| Backend custody | All 29 `app/**` paths match attempt 48; manifest SHA-256 `3f60c9b297760cf5fc0b1e89cd0ef02666f35c77ccc474202b80e26915703bb7` |
| Primary attempt 48 | 158,921 bytes; raw SHA-256 `1289f186c1cd6ee7f99eaa843f66e5416f15c0215e205e0ed5936737cd2a7123`; semantic SHA-256 `51433843638d69a2d09ced0d96a44a34323b1f5ece9c890c7c91088bac2df2e5` |
| Complete companion | 230,069 bytes; raw SHA-256 `925f16fcff8bfe54bf20ec40d19e7395ca2fae2e68f8694b49e5c08b65a9ad50`; semantic SHA-256 `59fe4439b0afbcd99b37c4a19fc006ad436ad623772d007e859ef117561f4fe4` |
| Failed-history ledger | Attempts 01–55; manifest SHA-256 `bca401f2207619ba84422e020104b9a609e0be0f4dc2b42f3ae4fb53d315ceff` |

The active renewal binds the original immutable
[executable waiver](P03-US08-provisional-latency-waiver.json) and
[human decision](../decisions/P03-US08-provisional-latency-exception.md), plus
the exact two-file frontend compatibility delta and current repository custody.
The chained validator binds exact regular files, canonical JSON, semantic
digests, internal identities, the two-file attempt-48-to-current delta, the
four-file companion-to-current delta, default-off rollback, expiry, and the
complete failed ledger. Attempts 52–55 are bound as failed history only; they
are not the selected exception evidence.
Attempts 54–55 came from an older disconnected Codex thread that has now
ended. No product/runtime byte changed during their history-only
reconciliation; the final guard and focused US08 gate were rerun afterward.

## Exit adjudication

| Claim | Evidence result |
|---|---|
| Strict current-artifact pass | **Not claimed** |
| Canonical strict final artifact present | **No** |
| P03-US08 completion basis | Approved candidate-specific, time-bounded exception |
| Excepted metric | Attempt 48, `ny-timetable`, `running_region_projection`, p95 latency only |
| Observed / strict ceiling | 0.050946750 / 0.050000000 seconds |
| Overrun | 0.000946750 seconds / 1.8935% |
| Maximum authorized overrun | 5% for this exact candidate and metric |
| Peak RSS waived | **No** |
| Other gates waived | **No** |
| Feature default | `PARSER_LAYOUT_RUNNING_REGIONS_ENABLED=false` |
| Hosted use | 0 requests / 0 tokens / $0 |

Attempt 48 remains a `failed_measurement_candidate`. Its fail-fast campaign
does not contain paired measurements; consequently it supports only the exact
near-boundary latency adjudication and cannot support paired-parser or RSS
claims.

The
[complete companion](P03-US08-running-region-metrics-attempt-31-post-seal-invalid.json)
remains quarantined as post-seal-invalid. It is not relabeled or promoted to a
canonical final artifact. It completed 20/20 paired workers and passed all 21
strict aggregate gates. Current code differs from attempt 48 only at the two
approved frontend paths; the other 84/86 paths match, and
`measured_backend_parser_runtime_paths_match_original` is true. Current code
differs from the companion at exactly those two frontend paths plus its two
historical evidence-validator paths, leaving 82/86 paths identical. This
chained custody supports the non-waived paired and memory evidence.

## Functional acceptance

| Reviewed denominator | Result |
|---|---|
| Physical pages | 30/30 exact |
| Detected printed labels / explicit nulls | 27 / 3 exact |
| Running regions | 47/47 exact |
| Role counts | 16 header / 30 footer / 0 navigation-top / 1 navigation-bottom |
| Repeated regions | 28 in 9 groups exact |
| Body / header / footer / Full blocks | 223 / 16 / 31 / 270 exact |
| Duplicate Body/Full presentation | 0 |
| Physical-index overwrite | 0 |

Source reports, opaque projection authority, exact PDF/predecessor bindings,
strict public/IR/canonical schemas, relationship and bbox custody,
physical-only navigation, bidi-isolated printed-label display, frontend
Body/Full parity, atomic rollback, idempotent terminal replay, closed resource
limits, and deadline boundaries pass within the accepted P03-US08 contract.

## Performance and memory interpretation

| Evidence | Uber | New York timetable |
|---|---:|---:|
| Attempt 48 source extraction p95 | 0.048295959 s — Pass | 0.215154375 s — Pass |
| Attempt 48 projection p95 | 0.006768750 s — Pass | 0.050946750 s — Exception, 1.8935% over |
| Companion paired p95 | 0.267703208 s — Pass | 1.447505041 s — Pass |
| Companion peak RSS delta | 12,877,824 bytes — Pass | 47,316,992 bytes — Pass |

Both RSS deltas remain below the strict 64 MiB ceiling. RSS is not waived. The
companion's passing results do not erase attempt 48's failure and do not create
a strict current-code final artifact; they are admissible only through the
exact signed custody bridge.

## Verification gates

- Fresh active-renewal six-file Phase 03/US08 gate: **291 passed, 1 intentional
  strict-final skip, 1 warning in 65.87 seconds**.
- Focused active-renewal guard: **28/28 passed, 1 pre-existing Starlette warning
  in 16.88 seconds**.
- Retained pre-renewal complete-backend regression: **2,383 passed, 11 skipped,
  163 warnings in 892.68 seconds (14:52)**. It predates the frontend correction
  and renewal guard/test changes, so it is not claimed as a fresh
  current-required-code run. All 29 `app/**` backend/parser paths remain
  identical; the fresh 291/28 focused gates cover the active renewal chain.
- Python compilation: **Pass**. Offline lockfile integrity: **Pass — 140
  packages resolved with no lock drift**.
- Frontend Node **24.14.0** lint, typecheck, production build, **106/106 unit
  tests**, and **1/1 bundle test** pass after the compatibility correction;
  responsive checks are **22/22**.
- Live `clinical-study.pdf` UI verification passes with four physical pages,
  printed label `1/21`, 22 canonical blocks, and working Body/Full views.
- The strict final-candidate test remains skipped because the canonical strict
  final artifact is absent. That skip is an explicit limitation, not a pass.

Warning counts belong to the named invocations and are not added across
overlapping reruns.

## Expiry, rollback, and phase boundary

The renewal is reviewed by **2026-09-02** and expires earlier upon any further
required-code custody change, production enablement of running regions, or
Phase 04 exit. On expiry or revocation, P03-US08 returns to In Progress and
dependent exit claims are blocked until strict current-code evidence passes or
another explicit decision is approved.

The production flag remains off by default. Disabling it performs no P03-US08
module load, extraction, projection, traversal, or serialization and returns
the exact configured predecessor.

Phase 04 remains Proposed and unstarted pending separate authorization. This
Phase 03 exit record does not authorize its implementation or status change.

## Hardened superseding renewal — 2026-08-03

The preceding identity and Phase 04 statements preserve the historical Phase
03 exit checkpoint. The requester-authorized chain now ends at
[`P03-US08-LATENCY-EXCEPTION-RENEWAL-20260803-PHASE04-TABLES-HARDENED`](../decisions/P03-US08-phase04-tables-latency-exception-hardened-renewal.md)
and
[P03-US08-phase04-tables-latency-waiver-hardened-renewal.json](P03-US08-phase04-tables-latency-waiver-hardened-renewal.json),
with final approval bound in
[the independent approval record](P03-US08-phase04-tables-hardened-renewal-independent-approval.md).
Their identities are, respectively, **25,343 bytes** / raw SHA-256
`bb3107b29f5a01876a64ee0179e1bff32b16bb93ecffa51da2f54c2d65510682`
and **22,113 bytes** / raw SHA-256
`5d0ac8411fd785eda1db1cbc01d2082ea09d65482ddba4796982cf0f60db4655`
/ semantic SHA-256
`a8e38c8269e5faf1e03f5bff942dd97b74bea87f6ae26f9c6c175e50ed6eba87`.
All earlier identities and claims above remain unchanged.

Attempt 48 remains failed at `ny-timetable` /
`running_region_projection` p95 **0.050946750 seconds** versus the unchanged
**0.050000000-second** strict ceiling (**0.000946750 seconds / 1.8935%**, at
most **5%** candidate-specific). The companion remains quarantined, the
canonical strict final remains absent, and no strict current-artifact metrics
pass is claimed. The new record removes only its enumerated, structurally
sealed, default-off Phase 04 table changes—and Phase 04 exit within that exact
scope—from the old blanket expiry. Production enablement, admitted-scope
expansion, or any protected running-region semantic/runtime/custody change
requires a new explicit decision and expires this renewal before the change;
review is due no later than **2026-09-02**. Exact-predecessor default-off
rollback and every non-waived RSS, paired/source/Uber latency, correctness,
security, compatibility, custody, resource/deadline, output, rollback, and
hosted-use gate remain mandatory. This administrative renewal records the
separately authorized boundary; it does not itself change a Phase 04 story
status or authorize Phase 05.
