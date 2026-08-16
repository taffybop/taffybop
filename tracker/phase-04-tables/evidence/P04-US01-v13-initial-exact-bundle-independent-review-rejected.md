# P04-US01 v13 Initial Exact-Bundle Independent Review — Rejected

Date: 2026-08-07  
Scope: independent production/security and metrics/custody review of the
initial v13 compact-transport monitor bundle  
Status: **REJECTED — NO PREDECLARATION, PREPARE, CANDIDATE, CANONICAL,
PRODUCTION, HOSTED-USE, STORY-COMPLETION, OR PHASE-EXIT AUTHORITY**

## Disposition

Two independent read-only reviews rejected the initial frozen v13 bundle.
One review reported three Blocking findings. The adversarial review reported
one consolidated Blocking deadline finding, four Major findings, and one
Minor finding. The overlap in deadline findings is not counted as additional
authority or evidence. No reviewer edited production, test, governance, or
failed-history inputs, and neither reviewer executed a governed
`real_metrics`, PREPARE, observer, current-RSS, corpus, or campaign node.

The reserved pending review leaf remains non-authoritative. This rejection is
immutable failed design-review history. A later design must use a new version,
fix every Blocking and Major finding, rerun deterministic evidence on the
final bytes, and obtain a fresh exact-byte approval before any real execution
or one-shot predeclaration.

## Blocking findings

1. The one-shot 6-second qualification watchdog could expire during attempt
   materialization and the retry could then execute without the live absolute
   7-second finalizer guard.
2. Deadline transitions and finalizer cleanup were not one closed state
   machine. The 7-second arm and attempt validation occurred outside the
   enclosing cleanup `finally`; an already elapsed 7.5-second rearm could
   escape from the timeout handler; exact attempt/runtime custody could be
   reduced by the generic service handler; and a partially failed `close()`
   could not be retried because it marked itself closed before restoration was
   proved.
3. The claimed absolute 9-second enclosing PREPARE relay used resettable
   socket inactivity timeouts. Separate send, header, and payload operations
   could exceed the total bound, including through a slow-drip frame.

The required correction is one dispatch-anchored 6/7/7.5/8/9-second state
machine, decreasing remaining time before every guarded transition and socket
operation, no unguarded materialization retry, bounded staged failure
construction, exact attempt/runtime retention whenever materialization
completed, and retryable proof of timer/handler/pending-signal/mask cleanup.

## Major findings

1. Compact-to-compact and compact-to-terminal custody did not prove append-only
   cadence continuity after more than the retained 32-entry suffix. A bounded,
   independently verifiable append proof is required; endpoint hashes alone
   are insufficient.
2. A failed current-RSS execution retained the classified lane failure but
   discarded the lane protocol and post-quiescence lifecycle/reap proof at the
   observer boundary. Failure custody must be assembled only after quiescence
   and retain one bounded failed-lane bundle without duplicating the exact
   qualification attempt.
3. Protocol-custody validation rejected legitimate prequalification service
   failures. The state matrix must distinguish prequalification service
   errors with no qualification, actual PREPARE qualification failures,
   post-PREPARE service failures bound to the retained passed qualification,
   and measurement failures.
4. The unreaped-preservation fallback could set the worker guard released
   while sampler quiescence was unproved, abandoning the sole owner and
   permitting a live process/group, zombie, or bootstrap descriptor to
   persist. Ownership must remain active until exact observer/lane death,
   lease release, worker termination, and reap are proved.

## Minor finding

The policy key `rss_non_real_allocation_probe_design` contradicted the actual
`real_metrics` marker on the touched-memory allocation probe. A later design
must rename and reconcile this as opt-in/noncanonical real execution rather
than describing it as non-real.

## Frozen reviewed identities

| Artifact | Bytes | SHA-256 |
| --- | ---: | --- |
| `pyproject.toml` | `944` | `975f9d5cde7e3c618bc201c2ef0df26e6a9ebda73a3322a0bf0d0bd12f36bfe7` |
| `tests/fixtures/phase_04/tables/rss_lane.py` | `287383` | `f3518e97e98a7d4c45baef32335ca4897436ec89b6eb6aed72c2f30066fdc879` |
| `tests/performance/test_p04_us01_rss_lane.py` | `64541` | `bf2efa0b684ee8c215298825bf63fdc66d47cf8fa11ae963378e5ea0e9bf7553` |
| `tests/fixtures/phase_04/tables/metrics.py` | `562424` | `77c7c722919bb2f2cfbf7678791a2b097e0247af4641e9eb93fe5c5508747376` |
| `tests/performance/test_p04_us01_table_metrics.py` | `404962` | `fa83a4160fbcf1c6af0c6010f953e79a8d4fac7ab05137780040955c57e15e1a` |
| `tracker/phase-04-tables/decisions/P04-US01-v13-compact-transport-monitor-controlled-supersession.md` | `15719` | `0afc804821545a3235c95669baaceb3f0c236f2264db9033566274cae4f85000` |
| `tracker/phase-04-tables/evidence/P04-US01-v13-compact-transport-monitor-controlled-supersession-independent-review.md` | `3209` | `21bf12b8be4211aabdf3be0c92763d32ff5dbb3d505956900927134ebf1cdd87` |
| `tracker/phase-04-tables/evidence/P04-US01-v13-preapproval-accidental-real-execution-history.md` | `12303` | `576eeb8239fb4bd61abcd2997e47a1985082ae78cc94f2c9e66a2a9049ba1757` |

The independent checks also reconfirmed the approved production identities:

| Artifact group | SHA-256 |
| --- | --- |
| table semantics | `f1fe19a70af069002c6b155e8b21a5e70e877f4baf64aa34a03fad2f26fee836` |
| pipeline | `060243b5c298bbf9613239f8e09e9b15c9777d0724a32fb900e10a004489f7b4` |
| runtime contract | `ae7492b5b86f781e1e1a9bcf411c376e8955f33ee84474162a94784c3417a028` |
| P03 boundary | `43901a3ac9aa455ce3776b5892fbb1732b91fa57310832e92692458b4e659cb2` |
| production benchmarks | `aaffe967092f60ed5e8ef85dd03cffa5b55b587a7e81b182b1b799ce01eb7be7` |

Collection-only review found 458 nodes: 21 governed `real_metrics` nodes and
437 deselected ordinary nodes, with one documented Starlette deprecation
warning. The marker boundary and transcript-budgeting design had no review
finding. The P03-US08 renewal also had no governance finding: attempt 48,
unchanged ceilings, the maximum 5% candidate-specific bound, default-off
rollback, every non-waived gate, review no later than 2026-09-02, expiry before
production enablement or relevant running-region behavior/custody change, and
strict-final absence remain unchanged.

P04-US01 remains In Progress. P04-US02, P04-US04, and P04-US03 remain Proposed.
The retained final metrics artifact remains absent. This review does not
describe Phase 03 as a strict current-artifact metrics pass and does not
authorize any Phase 05 work.
