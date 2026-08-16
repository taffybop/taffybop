# P03-US08 Phase 04 Tables Renewal — Implementation-State Amendment Approval

Status: **APPROVED — exact test-only amendment**  
Approved: 2026-08-04  
Scope: State-aware execution of the already-approved, closed Phase 04 tables
allowance

## Approval outcome

Three independent, read-only lanes approved the same sealed amendment after
recomputing its identities and re-running proportionate gates:
production/policy/security, metrics/custody/resource, and
compatibility/boundary. No reviewer edited a file. The approval binds only the
focused-test adaptation identified below; the original hardened renewal,
failed/blocked reviews, and failed metrics history remain immutable.

This approval does not relax the executable guard, admit another production
path, expand Phase 04 scope, supply P04-US01 completion evidence, enable a
flag, authorize production use, or authorize Phase 05.

## Exact approved amendment

| Artifact | Bytes | Raw SHA-256 |
|---|---:|---|
| Sealed amendment record | 6,672 | `4a411bad9e605c3c4644c826c05d497474ce7c45c52b546b8c6e97eda9f841bc` |
| Amended focused guard tests | 202,100 | `2e6713fde8d91d48e08e402ec0f6f9c0ee80f62496f72137692e60573134d100` |
| Previously approved focused guard tests | 201,049 | `51f69bf36583d687a4d870e76849d51f57581679f33cb0c33f1d97f46ca1d978` |

The production/policy reviewer reverse-applied the nine source hunks and
reconstructed the exact previously approved focused test at the size and hash
above. The amended helpers are idempotent only for the exact already-admitted
environment suffix, geometry candidate, one-shot replacement, and closed
companion-difference states. No assertion was removed or skipped.

The unchanged sealed artifacts remain:

| Artifact | Bytes | Raw SHA-256 |
|---|---:|---|
| Decision | 25,343 | `bb3107b29f5a01876a64ee0179e1bff32b16bb93ecffa51da2f54c2d65510682` |
| Machine-readable renewal | 22,113 | `5d0ac8411fd785eda1db1cbc01d2082ea09d65482ddba4796982cf0f60db4655` |
| Executable custody guard | 389,880 | `d749ea7a0713dbd35d2323b54dda4b1652c1077d501601b04e9b30135230f2bd` |
| Administrative metrics/custody contract | 165,157 | `3862f5d386f0bf4440da646d1cc7603dedb7f14cf694d275da49a6d9d0c97e75` |
| Required frontend readiness test | 2,156 | `ffc15e1ed0511b20a34bdead5342345b521f25e644b705806e2d9060a7d1f817` |
| Sealed renewal verification | 16,517 | `90e7623f6868d413001208bbb037f7526008fa241937171d9d9d41025f5d5100` |
| Original independent approval | 5,573 | `a57f537c7636a5dc918e819f916ee4c9234af5bdee6b375fd1956bf1492e7715` |

The renewal JSON semantic SHA-256 remains
`a8e38c8269e5faf1e03f5bff942dd97b74bea87f6ae26f9c6c175e50ed6eba87`.

## Status-boundary reconciliation

The independent compatibility review initially found two Phase 04 readiness
tests that still asserted the pre-start `Ready` state. They were deliberately
advanced to require P04-US01 `In Progress`, later Phase 04 and all Phase 05
stories `Proposed`, and no completion evidence. No readiness fixture, oracle,
limit, production assertion, or acceptance denominator changed.

| Test artifact | Bytes | Raw SHA-256 |
|---|---:|---|
| P04-US01 table contract | 6,816 | `9b17783fa1c8fc49b2e1b92edcd4025cc40e03c4219387130bcd84a049a4616a` |
| P04-US01 span-fidelity story tests | 27,879 | `396363d2d6c56e5288a3187fce7d98dbc535acffe2a505a56d8108c12d35f936` |

The reconciled focused Phase 04 slice passed **101 tests, 1 warning in 1.06
seconds**.

## Independent execution evidence

- Production/policy/security: complete amended guard **576 passed, 1 warning
  in 44.42 seconds**; metrics/custody **122 passed, 1 expected strict-final
  skip, 1 warning in 30.67 seconds**; nine amendment-sensitive constructions
  passed; 29 security/scope/default-off/expiry/ceiling/RSS negatives passed;
  compilation passed.
- Metrics/custody/resource: complete amended guard **576 passed, 1 warning in
  46.73 seconds**; metrics/custody **122 passed, 1 expected skip, 1 warning in
  28.64 seconds**; resource/non-execution **34 passed**; exception
  fact/expiry/default-off **15 passed**; exact-five/86 custody **5 passed**;
  frontend readiness **3 passed**; compilation passed.
- Compatibility/boundary: complete amended guard **576 passed, 1 warning in
  42.51 seconds**; metrics/custody **122 passed, 1 expected skip, 1 warning in
  30.50 seconds**; broad API/schema/serializer/table/P03/P04 compatibility
  **210 passed**; frontend Node 24.14.0 **109/109 tests**, lint, and typecheck
  passed; compilation passed.

The warning in Python commands was the existing Starlette/httpx deprecation.
The sole skip was the retained strict-final absence check. Canonical
strict-final evidence remains absent.

## Preserved exception and boundary

Attempt 48 remains failed for `ny-timetable` /
`running_region_projection` p95 at exactly **0.050946750 seconds** against the
unchanged **0.050000000-second** strict ceiling: **0.000946750 seconds / 1.8935%**
over. The maximum candidate-specific authorization remains **5%**. The
companion remains quarantined, and this is not a strict current-artifact
metrics pass.

Failed history remains exactly 55 artifacts with manifest SHA-256
`bca401f2207619ba84422e020104b9a609e0be0f4dc2b42f3ae4fb53d315ceff`.
The running-region flag and all four table flags remain false by default.
Disabling the running-region flag performs zero P03-US08 work and returns the
exact configured predecessor.

RSS, allocation, paired/source/Uber latency, correctness, quality, security,
API/schema/serializer/frontend compatibility, dependency/input/fixture/code
custody, resource/deadline, output-size, rollback, and hosted-use gates remain
non-waived. Review remains due no later than **2026-09-02**. The exception
expires before production enablement, any relevant running-region semantic or
runtime behavior change, any relevant running-region custody change,
authorized Phase 04 scope/path expansion, or hardened grammar/scanner
relaxation.

P04-US01 alone is In Progress. P04-US02, P04-US04, P04-US03, and every Phase 05
story remain Proposed.
