# P03-US08 Phase 04 Tables Renewal Independent Audit

Date: 2026-08-03  
Status: **Blocked — independent custody approval withheld**  
Scope: Phase 04 tables latency-renewal administration only

This is a non-recursive verification record. It does not amend, renew, hash,
or approve itself; it records observations about the sealed decision,
executable renewal, guard implementation, and current workspace. No production
code, Phase 04 story status, or Phase 05 record was changed by this audit.

## Blocking findings

1. **Unlisted-path expansion can pass the shared-surface guard.** The decision
   requires a new explicit decision before adding a Phase 04 path. The
   executable validator compares only the fixed running-region code manifest,
   then removes each allowed pipeline function body in full before hashing.
   An in-memory adversarial probe added a local import and call to the unlisted
   project module `app.services.unlisted_phase04_helper` inside
   `_merge_tables`. The normalized digest remained accepted and
   `_validate_phase04_renewal` returned successfully, producing
   `GUARD_ACCEPTED_UNLISTED_HELPER_IMPORT_FROM_ALLOWED_FUNCTION`. The helper did
   not need to be present because the guard neither executes the code nor
   closes the project-local import/path set. The same construction could route
   running-region behavior through an unlisted helper while the record still
   claims `running_region_behavior_changed=false` and
   `running_region_custody_changed=false`.

2. **The sealed human and executable scopes disagree on function count.** The
   decision says pipeline changes may affect only **five** named functions.
   The executable record and validator allow **six**:
   `_analyze_shared_pages`, `_docling_table_item`, `_merge_body_items`,
   `_merge_tables`, `_normalize_docling_body`, and `_vector_table_item`.
   Because the decision and record are identity-sealed, the discrepancy must
   be resolved by an explicit superseding correction rather than an in-place
   edit.

Required closure is a sealed replacement/correction that has one unambiguous
allowlist, plus an adversarial guard that rejects any unlisted project-local
dependency reachable from the admitted files/functions. The guard must be
rerun against final Phase 04 code before the renewal is used for custody
approval.

## Preserved terms verified

- Attempt 48 remains `failed_measurement_candidate` for `ny-timetable` /
  `running_region_projection` / `latency_p95_seconds`: **0.050946750 seconds**
  observed against the unchanged **0.050000000-second** strict ceiling,
  **0.000946750 seconds / 1.8935%** over, within the unchanged maximum **5%**
  candidate-specific bound.
- The canonical strict-final artifact remains absent. The complete companion
  remains quarantined at its post-seal-invalid path and is not promoted.
- `PARSER_LAYOUT_RUNNING_REGIONS_ENABLED` remains false by default; disabling
  it skips P03-US08 work and returns the exact configured predecessor.
- The renewal preserves the complete non-waived list: allocation, API/schema
  compatibility, code/dependency/input/fixture custody, correctness/quality,
  deadline/resource boundaries, hosted usage, output sizes, paired-parser
  latency, peak RSS, rollback, security, source-extraction latency, and Uber
  projection latency.
- Review remains due no later than **2026-09-02**. The record requires expiry
  before running-region production enablement, semantic/runtime behavior
  change, relevant custody change, or authorized Phase 04 scope expansion.
- Failed history remains attempts 01–55 with manifest SHA-256
  `bca401f2207619ba84422e020104b9a609e0be0f4dc2b42f3ae4fb53d315ceff`.
- Tracker superseding-current notes retain the failed-attempt, absent-strict-
  final, non-strict-current-artifact, rollback, non-waiver, review, expiry, and
  Phase 04/05 boundary disclosures. All Phase 04 and Phase 05 story files were
  still Proposed at this audit checkpoint.

## Audited identities

| Record | Bytes | Raw SHA-256 |
|---|---:|---|
| Original decision | 3,476 | `7bea63acad8403e442362edd8aabe0f4db084e6abd0cdd59e2b148b40a8b0d25` |
| Original executable waiver | 4,873 | `1fe75bc3d749730938653030052d463340eb2e856b810e0586e9afb12e9a72c8` |
| Frontend-bbox renewal decision | 3,456 | `6c1ac4c74a97f847122dd38877c6e44466795eddf1b73b26c84850ef775137e0` |
| Frontend-bbox executable renewal | 5,236 | `9e5761d53c8769daca3c2c59f37bfc99b1db12f89f28410e2b8667583a4e58d1` |
| Phase 04 tables renewal decision | 4,242 | `951f9e2a73fecdb6fa591a807af882fec334b26d9c63fdbcee16d92b96b42aad` |
| Phase 04 tables executable renewal | 6,007 | `5abc6cac91184bbd515ea855f49d168c614b53299f4415a29517e38441b9e02b` |
| Attempt 48 failed candidate | 158,921 | `1289f186c1cd6ee7f99eaa843f66e5416f15c0215e205e0ed5936737cd2a7123` |
| Quarantined complete companion | 230,069 | `925f16fcff8bfe54bf20ec40d19e7395ca2fae2e68f8694b49e5c08b65a9ad50` |

The Phase 04 executable renewal semantic SHA-256 remains
`84e95a5992ff45df073eaab500fde1185a6fd65affb3445989c2fc7adee32675`.
At the audit checkpoint the four allowed existing shared files remained
byte-identical to the recorded baseline, and the three optional added Phase 04
paths were absent; therefore no protected running-region behavior change had
yet occurred.

## Focused execution

Command:
`.venv/bin/pytest -q tests/performance/test_p03_us08_provisional_latency_exception.py`

Result: **29 passed, 1 pre-existing Starlette deprecation warning in 18.84
seconds**. This nominal pass verifies the sealed identities, exact observation,
unchanged bounds, rollback, expiry date, non-waived gates, history, and one
out-of-scope pipeline mutation. It does not close blocking finding 1 because
the present suite has no unlisted dependency/path-expansion adversary.

## Disposition

Independent production/security and metrics/custody approval is **withheld**.
The current workspace baseline is intact, but the renewal must not be relied on
to admit Phase 04 code changes until both blocking findings are corrected and
the corrected guard passes on final code.
