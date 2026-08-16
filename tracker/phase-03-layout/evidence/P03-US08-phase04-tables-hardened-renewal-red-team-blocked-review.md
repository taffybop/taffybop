# P03-US08 Phase 04 Tables Hardened Renewal Red-Team Review

Status: **BLOCKED — superseded implementation requires fresh independent review**  
Recorded: 2026-08-03  
Scope: Administrative renewal guard only; no production or story-status change

## Outcome

An independent red-team review found that the then-current hardened renewal
grammar was still permissive enough to admit unrelated execution, unsafe
callback or loader access, resource abuse, default-off drift, and frontend
browser side effects. The reviewed implementation was therefore blocked. No
finding in this record is waived, and this record is immutable failed-review
history. Later remediation may be relied on only after a fresh independent
review of newly sealed identities.

The review used parse-only and stub-only controls. It did not perform an
external filesystem, process, network, browser, or hosted-service side effect.

## Confirmed finding IDs

Backend table-semantics scanner:

- `TS-01`: module-level assignment could execute during import;
- `TS-02`: a parameter/member callback could be dispatched;
- `TS-03`: an imported attribute resolver could indirectly dispatch a
  callback;
- `TS-04`: an imported module-loader object could expose data-loading access;
- `TS-05`: debugger/input-style execution was admitted; and
- `TS-06`: an input-controlled loop lacked a proved cardinality/deadline
  boundary.

Pipeline normalization:

- `PL-01`: a table keyword on an unrelated call could be removed before the
  baseline comparison;
- `PL-02`: a builtin or callable object could be passed to a helper;
- `PL-03`: a helper name containing the word `table` could be treated as
  authorized without being an exact interface; and
- `PL-04`: the whole analysis context could be passed to a helper.

Configuration normalization:

- `CFG-01`: a duplicate or kill-switch formula could satisfy the prior
  reference collection;
- `CFG-02`: dependency polarity could be inverted; and
- `CFG-03`: one combined condition could stand in for the required independent
  dependency guards.

Frontend scanner:

- `FE-01` through `FE-12`: computed or fragmented property names, reflective
  access, timer callbacks, image/resource assignment, commented dynamic
  import syntax, resource-bearing JSX, browser storage/broadcast APIs, escaped
  global names, and computed document/HTML properties were admitted by the
  prior text-pattern checks.

The earlier reviewer also reported
`GUARD_ACCEPTED_REFLECTION_ALIAS_DYNAMIC_IMPORT_SIDE_EFFECT`, demonstrating
that split reflection names could be combined with dynamic import and a
side-effect target. This is retained as a separate blocking finding.

## Required remediation

The reviewer required closed, exact grammars: exact configuration guard ASTs;
an exact per-function pipeline call graph and argument paths; exact public
backend helper names/signatures; exact symbol imports without aliases; no
module-level execution; provenance-typed method receivers; exact plain-data
copy/validation bounds; bounded loops with deadline checks; and a frontend
surface that rejects computed calls/members, browser capabilities,
resource/event JSX, and additional exported runtime functions.

Every finding above must have a permanent negative regression, the complete
cross-story positive shape must still pass, and the resulting decision, JSON,
guard, tests, and verification record must be resealed. This record provides
no approval of that remediation.
