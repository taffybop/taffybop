# P03-US08 Hardened Phase 04 Renewal Independent Review 06

Status: Blocked; superseded by remediation and requires fresh review  
Review date: 2026-08-04  
Scope: Final static-root, phase-boundary, and running-region scope review

## Reviewed bundle

- Decision: 23,396 bytes, raw SHA-256
  `f3b02772501140e1ca6b7fbd865fc91733a7d39bbcfabb8770289ee580d27318`.
- Machine-readable renewal: 20,439 bytes, raw SHA-256
  `5b8894f40c6082465b0f00f1b39aaba6ec496776ae4fd83ff33d92f15c0282e3`,
  semantic SHA-256
  `a63e635ead65ddff1a3aa49356393fabaefd687e53b6b8ae5ac063a2400894b6`.
- Executable guard: 298,695 bytes, raw SHA-256
  `159cd91a25cdd273798eb5be73f73af7dfe329b8fe27cbbfcf84b61073a6d5c2`.
- Guard tests: 168,501 bytes, raw SHA-256
  `7df133ea544affd70c07317a9733d04a73fbd4935ef0a320b5a607c194374ae6`.
- Implementation verification: 9,083 bytes, raw SHA-256
  `084a1bcf742c5b6231a73d29b5ddd385de30370ba4045206c95067dfebab7927`.

The reviewed guard passed 339 tests with one pre-existing Starlette/httpx
warning. A concurrent metrics/custody review approved the immutable
administrative facts, but that approval did not override these findings.

## Findings

### IR06-FE-01 - rebound static roots

Severity: Major / correctness and ownership  
Disposition at review: Blocking

The frontend scanner trusted `Object`, `JSON`, and `Array` by spelling but
did not protect those roots from local or parameter rebinding. Valid helpers
could assign opaque input to those names and invoke `Object.values`,
`JSON.stringify`, or `Array.isArray`. Const/let/var assignment, parameter
shadowing, destructuring, TypeScript casts, and borrowed-method variants were
accepted. This contradicted the closed receiver/callback ownership contract.

### IR06-SCOPE-01 - compact Phase 05 backend forms

Severity: Major / phase boundary  
Disposition at review: Blocking

The common backend token grammar omitted `P05`, `p05`, and separator forms
such as `P_0_5`. An otherwise valid nine-function module could define one of
those names and execute span-path mutation, creating Phase 05 behavior inside
the admitted Phase 04 module.

### IR06-SCOPE-02 - camel and compact running-region forms

Severity: Major / scope boundary  
Disposition at review: Blocking

The same grammar accepted `runningRegion` and `runningregions`. Exact import
and pipeline controls still prevented direct coupling to the existing P03
implementation, so no current running-region behavior or custody changed, but
the accepted identifiers contradicted the renewal's claimed scope closure.

## Review decision

**BLOCKED.** No final production/security approval was granted. Production
surfaces remained at predecessor identities, P04-US01 remained Ready and
held, later Phase 04 stories remained Proposed, and every Phase 05 story
remained Proposed.

The post-decision blocked review records 03–05 were accurately hash-listed in
the verification record but were not added retroactively to the machine JSON.
The reviewer judged this nonblocking provided the eventual independent
approval record binds their exact identities together with the final
verification record.

## Remediation checkpoint

The executable guard now uses shared boundary-aware Phase 05/running-region
normalization and exact unshadowed static-root ownership. Permanent tests cover
case, separator, camel, compact, plural, assignment, shadow, destructuring,
cast, borrow, update, and false-positive controls.

Final-code identities are:

- executable guard: 301,252 bytes, raw SHA-256
  `932b850e15b5fc457c592847716060c916bebd3ffbe6f9d0a9354c0493cef052`;
  and
- guard tests: 174,491 bytes, raw SHA-256
  `4858937e23057f00d40ca154575eeef27ecd49bad6a62f6e8e5696f5d9926983`.

Python compilation passed and the complete final-code guard passed 376 tests
with one pre-existing warning. This checkpoint is not self-approval; the
amended bundle requires a new independent review.
