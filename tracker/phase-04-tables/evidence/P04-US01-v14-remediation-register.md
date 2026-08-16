# P04-US01 v14 Remediation Register

Date opened: 2026-08-07  
Scope: corrective successor to the rejected initial v13 monitor bundle  
Status: **OPEN — IMPLEMENTATION/REVIEW WORK ONLY; NO REAL-EXECUTION AUTHORITY**

This mutable register tracks closure of the findings sealed in
`P04-US01-v13-initial-exact-bundle-independent-review-rejected.md`. It is not a
decision, approval, predeclaration, candidate record, or metrics result. V14
cannot become operative until final code and deterministic evidence are frozen
with exact identities and a fresh independent production/security and
metrics/custody review reports zero Blocking, Major, correctness, security,
custody, compatibility, and performance/resource findings.

| ID | Severity | Required closure | State |
| --- | --- | --- | --- |
| V14-B01 | Blocking | One dispatch-anchored 6/7/7.5/8-second lane PREPARE state machine; bounded materialization retry; exact attempt/runtime retention when available; retryable signal/timer cleanup | In progress |
| V14-B02 | Blocking | One absolute 9-second deadline propagated through both enclosing relay hops and every send/header/body/parse/response operation; ordinary 5/2-second behavior unchanged | Open |
| V14-M01 | Major custody | Bounded append proof for compact-to-compact and compact-to-terminal cadence continuity beyond the 32-entry suffix, including maxima | Design in progress |
| V14-M02 | Major custody | Post-quiescence failed-lane bundle retaining the primary classified failure once plus bounded protocol, lifecycle/reap, identity, runtime/lease, and cleanup proof | In progress |
| V14-M03 | Major correctness/custody | Protocol state matrix accepts and strictly distinguishes prequalification service, qualification, post-PREPARE service, and measurement failures | Open |
| V14-M04 | Major resource/custody | Sole worker ownership retained until observer/lane death, lease release, worker-group termination, descriptor closure, and reap are proved | In progress |
| V14-m01 | Minor naming | Rename the touched-memory allocation-probe policy so it is not described as non-real | Open |

Required deterministic adversarial coverage includes expiry at 6, 7, and 7.5
seconds; expired transitions and partial cleanup; slow-drip headers and bodies
across both relays; 33-, 64-, and 1,000-sample append continuity and tampering;
malformed BIND/PREPARE and invalid prequalification operations; post-PREPARE
service and measurement failures; qualification/EOF/timeout/cancellation/
cleanup custody; and fail-first/permanent cleanup with no descendant, zombie,
or file-descriptor leak.

No entry may be marked closed solely because a focused test passes. Closure
requires final-code inspection, the proportionate deterministic gate, exact
file identities, and independent re-review. Any governed test collected under
`real_metrics`, any PREPARE/observer/current-RSS execution, the reviewed-corpus
campaign, and the one-shot canonical command remain prohibited until the later
v14 decision and review explicitly authorize them.

P04-US01 remains In Progress. P04-US02, P04-US04, and P04-US03 remain Proposed.
The final metrics artifact remains absent. Phase 03 is not a strict
current-artifact metrics pass. Phase 05 remains Proposed and unauthorized.
