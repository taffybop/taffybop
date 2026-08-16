# P03-US08 Phase 04 Tables Renewal — Implementation-State Test Amendment

Status: **SEALED CANDIDATE — independent approval required**  
Sealed: 2026-08-04  
Scope: Narrow, administrative test adaptation for already-admitted,
default-off Phase 04 table implementation states

## Purpose and boundary

The independently approved hardened Phase 04 tables renewal was sealed while
all admitted production paths were still at their frozen predecessors. Once
P04-US01 entered In Progress and the first exact, guard-admitted production
states were installed, four focused-test constructions remained hard-coded to
the predecessor file state. The executable custody guard correctly accepted
the production states, but those test constructions attempted to append or
replace the same state a second time and therefore failed before exercising
their intended assertions.

This amendment changes only
`tests/performance/test_p03_us08_provisional_latency_exception.py`. It makes
those test constructions idempotent with respect to the exact states already
accepted by the unchanged executable guard. It does not change the decision,
machine-readable renewal, custody guard, administrative metrics/custody
contract, production allowance, scanner grammar, path set, ceilings, facts,
or expiry. It supplies no Phase 04 story completion evidence and authorizes no
Phase 05 work.

Until a fresh independent approval record binds this exact amendment, the
candidate is not relied upon for further production work.

## Exact amended identity

| Artifact | Bytes | Raw SHA-256 |
|---|---:|---|
| Focused guard tests, amended candidate | 202,100 | `2e6713fde8d91d48e08e402ec0f6f9c0ee80f62496f72137692e60573134d100` |
| Previously approved focused guard tests | 201,049 | `51f69bf36583d687a4d870e76849d51f57581679f33cb0c33f1d97f46ca1d978` |

All other artifacts remain the exact independently approved identities:

| Artifact | Bytes | Raw SHA-256 |
|---|---:|---|
| Decision | 25,343 | `bb3107b29f5a01876a64ee0179e1bff32b16bb93ecffa51da2f54c2d65510682` |
| Machine-readable renewal | 22,113 | `5d0ac8411fd785eda1db1cbc01d2082ea09d65482ddba4796982cf0f60db4655` |
| Executable custody guard | 389,880 | `d749ea7a0713dbd35d2323b54dda4b1652c1077d501601b04e9b30135230f2bd` |
| Administrative metrics/custody contract | 165,157 | `3862f5d386f0bf4440da646d1cc7603dedb7f14cf694d275da49a6d9d0c97e75` |
| Required frontend readiness test | 2,156 | `ffc15e1ed0511b20a34bdead5342345b521f25e644b705806e2d9060a7d1f817` |
| Sealed renewal verification | 16,517 | `90e7623f6868d413001208bbb037f7526008fa241937171d9d9d41025f5d5100` |
| Independent renewal approval | 5,573 | `a57f537c7636a5dc918e819f916ee4c9234af5bdee6b375fd1956bf1492e7715` |

The renewal JSON semantic SHA-256 remains
`a8e38c8269e5faf1e03f5bff942dd97b74bea87f6ae26f9c6c175e50ed6eba87`.

## Exact test-only adaptations

The amendment is limited to four state-aware constructions:

1. The environment-suffix helper returns an already exact four-line suffix
   unchanged instead of appending a duplicate suffix.
2. The table-geometry helper returns an already valid geometry candidate
   unchanged instead of requiring the live file to be the predecessor.
3. The one-shot replacement helper accepts only the exact already-replaced
   state when the predecessor fragment is absent and the reviewed replacement
   occurs exactly once; all other missing, duplicate, or mixed states still
   fail.
4. The companion-difference assertion still requires every predecessor
   difference and now permits only their union with the exact closed Phase 04
   production-path set already frozen by the executable guard.

No assertion was deleted or skipped. No extra path, alias, source construct,
runtime capability, serializer behavior, resource allowance, or default-on
state was admitted.

## Guard-admitted implementation state under review

The current partial P04-US01 state is inside the unchanged closed allowance:

| Artifact | Bytes | Raw SHA-256 |
|---|---:|---|
| `.env.example` | 4,878 | `cb66f175e38197552258d095d8dc0a70522ec5bb7911b1414750499d6f9c7c3f` |
| `app/config.py` | 18,195 | `863695112bace175f12ae5e0e4294c9292a5b9c884b140e4a6a6cb506284f85d` |
| `app/services/tables.py` | 22,573 | `12101a10fc5344a820bafbe581f122504b230cae45c28b25519a2265f317aaf3` |
| `app/services/table_semantics.py` | 17,115 | `06bb02f1a4c295aa8eef36f3ac1ecd6dd3689dd7a5e8074520caa677322cb4ee` |

All four table flags remain false by default. The semantics file is the
guarded nine-function no-op scaffold; it is not P04-US01 completion evidence.
No pipeline, source-alignment, text-reconciliation, or frontend behavior is
activated by this partial state.

## Verification

The amended complete focused guard passed **576 tests, 1 warning in 33.22
seconds**, with no skip or failure. The complete non-waived P03 metrics/custody
contract passed **122 tests, 1 expected retained-final skip, 1 warning in
22.23 seconds**. The skip is the documented absence of the canonical
strict-final artifact. The warning in both commands is the pre-existing
Starlette/httpx deprecation warning. Python compilation passed for the
executable guard, amended focused tests, metrics/custody contract, configuration,
vector-table module, and guarded table-semantics scaffold.

## Preserved exception facts and non-waived gates

Attempt 48 remains failed for `ny-timetable` /
`running_region_projection` p95 at exactly **0.050946750 seconds** against the
unchanged **0.050000000-second** strict ceiling: **0.000946750 seconds / 1.8935%**
over. The maximum candidate-specific authorization remains **5%**. Canonical
strict-final evidence remains absent and the companion remains quarantined;
this is not a strict current-artifact metrics pass.

Failed history remains exactly 55 artifacts with manifest SHA-256
`bca401f2207619ba84422e020104b9a609e0be0f4dc2b42f3ae4fb53d315ceff`.
The running-region flag and all four table flags remain false by default.
Disabling the running-region flag performs zero P03-US08 work and returns the
exact configured predecessor.

RSS, allocation, paired/source/Uber latency, correctness, quality, security,
API/schema/serializer/frontend compatibility, dependency/input/fixture/code
custody, resource/deadline, output-size, rollback, and hosted-use gates remain
non-waived. Review remains due no later than **2026-09-02**, and the exception
expires before production enablement, any relevant running-region semantic or
runtime change, any relevant custody change, admitted Phase 04 scope/path
expansion, or hardened grammar/scanner relaxation.

P04-US01 alone is In Progress. P04-US02, P04-US04, P04-US03, and every Phase 05
story remain Proposed.
