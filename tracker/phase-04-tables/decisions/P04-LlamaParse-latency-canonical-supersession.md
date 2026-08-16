# Phase 04 LlamaParse Latency Canonical Supersession

Status: Canonical prospective planning contract; executable implementation,
fresh evidence, and independent approval pending  
Date: 2026-08-08  
Scope: Phase 04 candidate-latency comparator only  

## Decision

For all prospective Phase 04 Definition-of-Done and phase-exit decisions, the
sole operative candidate-latency comparator is
[`LlamaParse latency reference v1`](../../benchmarks/llamaparse-15/latency-reference-v1.md).
The reference configuration is LlamaCloud Parse v2, Agentic mode at 10
credits/page, cost optimizer off, cache disabled, with latency taken from the
provider UI's **Total Latency** field.

The initial 2026-08-08 observation for each case is a planning/reference
ceiling only. It is not sufficient evidence for a story or phase pass. Before
Definition of Done or Phase 04 exit, each applicable case must have at least
five interleaved candidate/Llama observations. Candidate p50 and empirical
inclusive nearest-rank p95 must each be less than or equal to the corresponding
paired Llama p50 and p95 for that case. Each case gates independently; a corpus
average cannot mask a slower case, and no failed observation may be dropped.

Candidate and Llama inputs and outputs must be semantically comparable. If that
cannot be established, latency is **Unmeasured/Blocked**. Historical M0 local-
parser wall times, candidate flag-off comparisons, table-stage timings, and
component timings remain useful diagnostics only. They cannot substitute for
the Llama reference or independently confer a candidate-latency pass. A latency
pass is valid only when every required quality and reliability result also
passes unchanged.

## Controlled supersession boundary

Effective prospectively from 2026-08-08, this decision supersedes only the
Phase 04 candidate-latency comparator and pass/fail formulas in earlier live
planning language and in the accepted historical table-stage-overhead lineage.
It does not rewrite, relabel, or invalidate the measurements, failures,
identities, schemas, decisions, or custody retained in those historical files.
Their local predecessor, whole-parser, named-stage, and component timings remain
diagnostic evidence.

This decision changes no production code, runtime behavior, API, serializer,
frontend, feature setting, story status, or Phase 05 status. It creates no
current-artifact pass and no hosted-use, production-enablement, story-completion,
phase-exit, or Phase 05 authority.

The designated Phase 04 one-shot planning observations are:

| Case | Provider UI Total Latency | LlamaCloud job ID |
|---|---:|---|
| `finance-10k` | 29.4 s | `pjb-415ucx2flb2ild9e0nzdsqnxqr6f` |
| `ny-timetable` | 45.6 s | `pjb-7ljh3v6chmcbpp7qriuwvbbglpat` |
| `postal-10k` | 25.3 s | `pjb-0qtz3dizelo6pu7gv0f4ur8g1bij` |

These values remain single-sample planning/reference ceilings and do not meet
the required refreshed distributional evidence contract.

## Non-waiver

All correctness and quality denominators, RSS/memory ceilings and sampling,
resource/CPU controls, cadence and process-identity controls, output ceilings,
deadlines and timeout/fail-closed behavior, security, compatibility, custody,
hosted-use controls, deterministic behavior, API/serializer/frontend gates,
default-off behavior, and rollback remain cumulative and mandatory.

The active P03-US08 administrative exception is unchanged and remains a P03
contract only. In particular, attempt 48 remains failed at `0.050946750`
seconds against the unchanged `0.050000000`-second ceiling: `0.000946750`
seconds / `1.8935%` over, within the maximum 5% candidate-specific bound.
Strict-final evidence remains absent. The exception remains default off,
reviewable no later than 2026-09-02, and expires before production enablement or
any relevant running-region semantic/runtime/custody change. It waives no RSS,
paired/source/Uber latency, correctness, security, compatibility, custody,
resource, output, rollback, or hosted-use gate. It is not the Phase 04 candidate
latency comparator.

The sealed P03 failed history remains bound to attempt-55 manifest
`bca401f2207619ba84422e020104b9a609e0be0f4dc2b42f3ae4fb53d315ceff`.

## Required closure

Before this prospective contract can support Definition of Done or Phase 04
exit, the executable metrics schema, validator, deterministic boundary tests,
retained final-code identities, interleaved measurements, failure accounting,
and independent production/security plus metrics/custody review must be updated
and approved. Until then the affected latency result remains pending, P04-US01
remains In Progress, P04-US02/P04-US04/P04-US03 remain Proposed, and Phase 05
remains Proposed and unauthorized.
