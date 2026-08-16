# P03-US08 Phase 04 Operative Administrative Renewal — Independent Review Request

Status: **PENDING — no independent approval claimed**  
Requested: 2026-08-07  
Required before: P04-US01 may be marked Done or this renewal may support any
story-completion or Phase 04 exit claim  
Latest review date: 2026-09-02  

## Exact review bundle

| Artifact | Bytes | Raw SHA-256 |
|---|---:|---|
| `tracker/phase-03-layout/decisions/P03-US08-phase04-tables-latency-exception-operative-administrative-renewal.md` | 10,226 | `93b95e2d07b4e58a6f8f9a8ae43e587ec199d4fbaaeac4d59c8770702fd32504` |
| `tracker/phase-03-layout/evidence/P03-US08-phase04-tables-latency-waiver-operative-administrative-renewal.json` | 9,722 | `99ac85518d573cb64abd4127444e45d631e767ec8ee236104c389fc420619c41` |

The machine-readable record's closed `change_classifier` canonicalizes as the
UTF-8 output of `jq -j -S -c '.change_classifier'` and has SHA-256
`a776f175759752777cbc4db465386b8af17737552750b0c5411d6ca1622f3a30`.

## Required independent checks

The reviewer must independently verify and report each item as Pass or a
blocking finding:

1. The only exception remains immutable failed attempt 48 New York
   `running_region_projection` p95 `0.050946750` seconds versus the unchanged
   `0.050000000`-second ceiling: delta `0.000946750`, `1.8935%`, within a
   maximum `5%` candidate-specific bound.
2. Attempt-48 raw SHA-256
   `1289f186c1cd6ee7f99eaa843f66e5416f15c0215e205e0ed5936737cd2a7123`
   (158,921 bytes) is unchanged; failed history remains exactly 55 artifacts
   through attempt 55 at manifest SHA-256
   `bca401f2207619ba84422e020104b9a609e0be0f4dc2b42f3ae4fb53d315ceff`.
3. The canonical strict-final artifact is absent, attempt 48 remains failed,
   and neither artifact describes Phase 03 as a strict current-artifact
   metrics pass.
4. The semantic classifier admits only unrelated, default-off work for
   P04-US01, P04-US02, P04-US04, and P04-US03 in that order; mixed or ambiguous
   effects fail closed.
5. Any P03 running-region semantic/runtime/reachability/custody change,
   production enablement, Phase 05 work, classifier relaxation, ceiling or
   rollback change, or non-waived-gate change expires the renewal before
   reliance.
6. RSS/allocation, paired/source/Uber latency, correctness, security,
   compatibility, custody, resources, output, rollback, hosted-use, and every
   other non-named gate remain unwaived.
7. `PARSER_LAYOUT_RUNNING_REGIONS_ENABLED` and all four Phase 04 flags remain
   default-off with exact predecessor rollback and independent switch
   behavior.
8. The renewal is reviewable no later than 2026-09-02, auto-expires at
   23:59:59 UTC that day if not replaced, never authorizes production, and
   blocks completion/exit claims on expiry.
9. Sponsor authorization is not misrepresented as independent approval. This
   pending request itself grants no approval.

## Required review output

Record the independent result in a new immutable leaf at:

`tracker/phase-03-layout/evidence/P03-US08-phase04-tables-operative-administrative-renewal-independent-review.md`

That leaf must identify the reviewer role, date, both exact bundle identities,
the classifier digest, commands or methods used, Pass/finding results for all
nine checks, and a final disposition. It must not edit this request or any
historical decision/evidence record. Approval, if warranted, applies to the
administrative classifier only; it cannot substitute for exact final-code,
story, production/security, metrics/custody, or Phase 04 exit review.
