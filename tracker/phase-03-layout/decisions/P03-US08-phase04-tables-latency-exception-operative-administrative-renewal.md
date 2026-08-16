# P03-US08 Phase 04 Tables Operative Administrative Renewal

Status: **OPERATIVE FOR AUTHORIZED PHASE 04 DEVELOPMENT ONLY**  
Decision ID: `P03-US08-LATENCY-EXCEPTION-RENEWAL-20260807-PHASE04-TABLES-ADMINISTRATIVE-CONTINUITY`  
Sponsor: Project owner/requester  
Recorded: 2026-08-07  
Review due: no later than 2026-09-02  

## Decision

The project owner/requester expressly authorizes this narrow administrative
continuity renewal so unrelated Phase 04 table changes can continue without
being misclassified as changes to the protected P03-US08 running-region
candidate. This decision is operative immediately for development, testing,
review, evidence collection, and documentation within the four authorized
Phase 04 table stories. It is not a strict metrics pass, production approval,
story-completion approval, Phase 04 exit approval, or Phase 05 authorization.

This renewal replaces the churn-sensitive rule that every unrelated Phase 04
table byte invalidates the P03-US08 exception. It does not replace the exact
final-code gates. A Phase 04 change is admitted here only when it satisfies the
closed semantic classifier in the accompanying machine-readable record. The
classifier asks what behavior and custody the change affects; it does not
prospectively trust a current or future Phase 04 file hash. Exact candidate
bytes, tests, configuration, dependencies, evidence, results, and review
findings must still be frozen and independently reviewed before a story is
marked Done and again as required by the Phase 04 exit gate.

The prior semantic-isolation candidate remains useful historical control and
terminal-evidence design, but its stale P04-US01 hash freeze is not authority
for current bytes. This renewal supersedes only that candidate's restriction
on development continuity. It does not rewrite any earlier decision, failed
attempt, blocked review, approval, or evidence artifact, and it does not claim
that an independent reviewer has approved this new renewal. An independent
policy/custody review of this renewal's exact bytes and classifier is required
before P04-US01 may be marked Done; the pending review request is recorded
separately.

## Immutable exception basis

The sole accepted observation remains immutable failed attempt 48 for
`ny-timetable` at `running_region_projection`:

| Field | Exact value |
|---|---:|
| Metric | `latency_p95_seconds` |
| Observed | `0.050946750` seconds |
| Strict ceiling | `0.050000000` seconds |
| Overrun | `0.000946750` seconds |
| Overrun fraction | `0.018935` (`1.8935%`) |
| Maximum candidate-specific bound | `0.05` (`5%`) |

The attempt-48 artifact remains failed. Its raw identity is SHA-256
`1289f186c1cd6ee7f99eaa843f66e5416f15c0215e205e0ed5936737cd2a7123`
at 158,921 bytes, and its recorded semantic SHA-256 is
`51433843638d69a2d09ced0d96a44a34323b1f5ece9c890c7c91088bac2df2e5`.
Failed history remains sealed through attempt 55 as exactly 55 artifacts with
manifest SHA-256
`bca401f2207619ba84422e020104b9a609e0be0f4dc2b42f3ae4fb53d315ceff`.

The canonical P03-US08 strict-final artifact remains absent. The complete
companion remains quarantined and is not a canonical substitute. Phase 03 and
Phase 04 records must not describe P03-US08 as a strict current-artifact
metrics pass.

Every original ceiling remains unchanged. In particular, the projection p95
ceiling remains 0.050000000 seconds, source-extraction p95 remains 0.250000000
seconds, paired parser ceilings remain 2.338000000 seconds for
`ny-timetable` and 1.457500000 seconds for `uber-earnings`, allocation and
peak-RSS-delta ceilings each remain 67,108,864 bytes, and the source report
size ceiling remains 8,388,608 bytes. The maximum 5% exception bound remains
candidate-specific to the exact attempt-48 observation; it is not a new
ceiling or general tolerance.

## Closed semantic classifier

A change is an admitted unrelated Phase 04 table change only when all of the
following are true:

1. It implements, tests, documents, measures, reviews, or rolls back only
   P04-US01, P04-US02, P04-US04, or P04-US03, in that dependency order and
   with no more than one story In Progress.
2. Its runtime effect is owned exclusively by Phase 04 table behavior and is
   unreachable when the relevant Phase 04 flag chain is false. Test fixtures,
   benchmark oracles, adversarial controls, metrics infrastructure, evidence,
   and tracker records must likewise be exclusively attributable to Phase 04
   tables or to this administrative renewal.
3. All four Phase 04 table switches remain false by default and preserve their
   dependency order. Disabling them restores the exact configured predecessor
   with no table-stage work. `PARSER_LAYOUT_RUNNING_REGIONS_ENABLED` remains
   false by default, independent of every table switch, and its rollback still
   performs zero P03-US08 work and returns the exact configured predecessor.
4. The change does not alter P03 running-region or printed-page semantics,
   runtime behavior, reachability, feature-flag behavior, outputs, serializer
   meaning, public compatibility, dependency resolution, benchmark/input
   custody, metrics policy, measurement method, evidence interpretation, or
   rollback.
5. Before a candidate is retained or relied on, every applicable non-waived
   gate executes and passes. A failure blocks retention and requires the
   declared rollback; it is never reclassified or suppressed. The change may
   not alter a gate, ceiling, failure, skip, warning, finding, or evidence
   requirement.
6. It adds no production enablement, hosted use, Phase 05 status or behavior,
   or public capability outside the authorized Phase 04 table scope.

The classifier is conjunctive and fail-closed. Ambiguity is not admitted.
Renaming, indirection, shared-file placement, test-only placement, or a
default-off flag does not make a mixed or protected change unrelated. A
change that affects both tables and a protected P03 surface is a protected
change and expires this renewal before that change can rely on it.

This administrative classifier permits the ordinary Phase 04 table work the
requester named: production implementation, compatible schema extensions,
configuration, fixtures and reviewed benchmark controls, frontend behavior,
tests, performance/RSS infrastructure, documentation, rollback, and evidence.
It does not establish that any such work is correct or complete; the
non-waived gates and exact final-code review do that.

## Gates that are not waived

No gate other than the single attempt-48 New York projection-p95 observation
is waived. The following remain mandatory and fail closed:

- peak RSS and allocation;
- paired parser, source-extraction, and Uber-projection latency;
- correctness, quality, source fidelity, and non-fabrication;
- security, malformed-input, timeout, and fail-closed behavior;
- API, schema, serializer, frontend, and predecessor compatibility;
- code, dependency, input, fixture, benchmark, evidence, and model custody;
- deadlines, memory, CPU, file-descriptor, process, and other resource bounds;
- output-size and bounded-diagnostic requirements;
- default-off behavior and exact rollback;
- hosted-use, hosted-request, token, and cost gates; and
- every prior-phase and Phase 04 story/exit gate not named as the sole latency
  exception.

Alternative table evidence may not be silently discarded; cells, spans, and
structure may not be fabricated; ambiguous candidates may not be promoted;
and charts, forms, or aligned prose may not be converted into canonical tables
without independently sufficient evidence. This renewal changes none of those
requirements.

## Expiry, review, and rollback

This renewal must remain reviewable no later than **2026-09-02** and expires
at the earliest of:

- immediately before production enablement or production reliance;
- immediately before any relevant P03 running-region semantic or runtime
  behavior change;
- immediately before any relevant running-region, metrics, dependency,
  benchmark, input, or evidence-custody change;
- immediately before any change to a ceiling, the 5% candidate-specific bound,
  default-off behavior, rollback, or a non-waived gate;
- immediately before a Phase 04 scope expansion outside the four named table
  stories or before any Phase 05 work/status transition;
- immediately upon classifier ambiguity, classifier relaxation, bypass or
  suppression of a required gate, or failure of the declared rollback; or
- at 23:59:59 UTC on 2026-09-02 if not earlier replaced by a reviewed renewal
  or strict current-code P03-US08 final campaign.

Expiry is fail-closed: P03-US08 returns to In Progress and every dependent
completion or exit claim is blocked until strict evidence or a separately
authorized renewal resolves it. The immediate operational rollback remains to
disable `PARSER_LAYOUT_RUNNING_REGIONS_ENABLED`; the four Phase 04 flags are
also disabled independently in reverse dependency order. No production use is
authorized by this decision.

## Evidence and review order

The machine-readable record binds the exact immutable attempt-48 evidence,
the sealed attempt-55 history manifest, this decision's raw identity, and the
closed classifier. It deliberately does not bind churn-sensitive Phase 04
implementation hashes.

The separate review request binds the exact bytes of this decision and its
machine-readable record. An independent reviewer must verify the immutable
facts, classifier closure, immediate-expiry triggers, non-waived gates,
default-off rollback, Phase 05 boundary, and absence of a strict-final claim.
No approval is implied by a pending review request.

For each Phase 04 story, exact final-code identities and complete executed
gate results remain required before Done. Phase 04 exit additionally requires
the complete focused and regression gates plus independent production/security
and metrics/custody approval. Retained final metrics and downstream reports
cannot retroactively authorize their own inputs.

## Phase boundary

This renewal covers only P04-US01, P04-US02, P04-US04, and P04-US03 in that
order. It does not implement, ready, start, approve, or otherwise cross into
Phase 05. Separate explicit requester authorization remains required.
