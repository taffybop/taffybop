# P03-US08 Hardened Phase 04 Tables Renewal — Independent Approval

Status: **APPROVED — exact frozen bundle only**  
Approved: 2026-08-04  
Scope: Narrow administrative P03-US08 renewal for unrelated, default-off
Phase 04 table work

## Approval outcome

Three independent final lanes approved the same immutable bundle after the
verification record was sealed: production/policy/scope, metrics/custody/
resource, and compatibility/boundary. Each lane recomputed the identities,
inspected the exception facts and status boundaries, ran proportionate gates,
and made no file edit. Reviews 08–14 and every earlier failed or blocked review
remain blocked history; none is reclassified as approval.

This approval changes no reviewed artifact. It permits only the table-only
Phase 04 changes admitted by the executable renewal. It is not a strict
current-artifact metrics pass and does not authorize production enablement,
running-region semantic/runtime/custody changes, scope expansion, scanner
relaxation, or Phase 05 work.

## Exact approved bundle

| Artifact | Bytes | Raw SHA-256 |
|---|---:|---|
| Decision | 25,343 | `bb3107b29f5a01876a64ee0179e1bff32b16bb93ecffa51da2f54c2d65510682` |
| Machine-readable renewal | 22,113 | `5d0ac8411fd785eda1db1cbc01d2082ea09d65482ddba4796982cf0f60db4655` |
| Executable custody guard | 389,880 | `d749ea7a0713dbd35d2323b54dda4b1652c1077d501601b04e9b30135230f2bd` |
| Focused guard tests | 201,049 | `51f69bf36583d687a4d870e76849d51f57581679f33cb0c33f1d97f46ca1d978` |
| Administrative metrics/custody contract | 165,157 | `3862f5d386f0bf4440da646d1cc7603dedb7f14cf694d275da49a6d9d0c97e75` |
| Required frontend readiness test | 2,156 | `ffc15e1ed0511b20a34bdead5342345b521f25e644b705806e2d9060a7d1f817` |
| Sealed verification record | 16,517 | `90e7623f6868d413001208bbb037f7526008fa241937171d9d9d41025f5d5100` |

The renewal JSON semantic SHA-256 is
`a8e38c8269e5faf1e03f5bff942dd97b74bea87f6ae26f9c6c175e50ed6eba87`.
The administrative contract's exact predecessor was independently
reconstructed at 162,944 bytes and SHA-256
`3604bf403b900970414ce8cc86d40bf806958cb0b1cb2d17e776ee404c2b408e`.

## Immutable blocked history added during final hardening

| Review | Bytes | Raw SHA-256 |
|---|---:|---|
| 08 | 4,802 | `cf4551c6ff5c47d25c7a42e3d57285e43aa18fa838a90c9cbd4b8307b2879bfa` |
| 09 | 4,344 | `1d9e3cbf6626b91a66cbd56c793c8abac652b17171bdb7358dd0d88ef0a0adf7` |
| 10 | 3,787 | `ff97869c9582480f879a7ddf7113698c44626e13ecbca550f107402c22633aae` |
| 11 | 3,890 | `d80c132673979f162fca90135816a810f1cacb488978abf53c009949a6580bd2` |
| 12 | 4,280 | `c5ce59f91eae54ec05cd1580f824a62da6e5abfae8bbb97827043f23d059ff4e` |
| 13 | 2,936 | `c75b5b1f4449ab1b5f7332bdc2881bfa7915fbd711501ee3dc07a19275f2fb5e` |
| 14 | 3,134 | `d7469d732d9bdaa6450f666f53ae5f203e42b6f4b4330520bb991cf7ebdbb087` |

The failed audit, red-team review, and reviews 02–07 also matched every size
and hash recorded in the sealed verification record and remain explicitly
blocked with no approval.

## Independent execution evidence

- Production/policy/scope lane: focused guard **576 passed, 1 warning in
  31.93 seconds**; metrics/custody **122 passed, 1 expected retained-final
  skip, 1 warning in 22.33 seconds**; compilation passed for the guard,
  contracts, Phase 04 fixtures, and P04-US01 story test.
- Metrics/custody/resource lane: focused guard **576 passed, 1 warning in
  33.64 seconds**; metrics/custody **122 passed, 1 expected skip, 1 warning in
  23.61 seconds**; frontend readiness **3 passed**; resource/non-execution
  **34 passed**, exception-fact/expiry/default-off **15 passed**, and
  exact-five/86 custody **5 passed**.
- Compatibility/boundary lane: focused guard **576 passed, 1 warning in 31.80
  seconds**; metrics/custody **122 passed, 1 expected skip, 1 warning in 22.43
  seconds**; backend API/schema/serializer **130 passed**; frontend Node
  24.14.0 compatibility/readiness **29 passed**.

The only warning was the documented Starlette/httpx deprecation. The sole
skip was the retained strict-final absence check; canonical strict-final
evidence remains absent.

## Preserved exception and boundary

Attempt 48 remains failed for `ny-timetable` /
`running_region_projection` p95 at **0.050946750 seconds** against the
unchanged **0.050000000-second** ceiling: **0.000946750 seconds / 1.8935%**
over. The maximum candidate-specific authorization remains **5%**. The
companion remains quarantined and cannot establish a strict current-artifact
pass.

Failed history remains exactly 55 artifacts with manifest SHA-256
`bca401f2207619ba84422e020104b9a609e0be0f4dc2b42f3ae4fb53d315ceff`.
The running-region flag and all four table flags remain false by default.
Disabling the running-region flag still performs zero P03-US08 work and
returns the exact configured predecessor.

RSS, allocation, paired/source/Uber latency, correctness, quality, security,
API/schema/serializer/frontend compatibility, dependency/input/fixture/code
custody, resource/deadline, output-size, rollback, and hosted-use gates remain
non-waived. The renewal is reviewable no later than **2026-09-02** and expires
before production enablement, any relevant running-region semantic/runtime or
custody change, admitted Phase 04 scope/path expansion, or hardened
grammar/scanner relaxation.

At approval time P04-US01 was Ready and held; P04-US02, P04-US04, P04-US03,
and every Phase 05 story were Proposed. The subsequent P04-US01 status
transition may rely on this record only while the exact approved renewal and
its closed scope remain valid.
