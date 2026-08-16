# P03-US08 Hardened Phase 04 Renewal Independent Review 02

Status: **BLOCKED — superseded scanner identities require reseal and re-review**  
Recorded: 2026-08-03  
Scope: Administrative renewal guard only

## Findings

The independent reviewer confirmed that the sealed backend scanner validated
only the public functions it happened to observe. A module containing a strict
subset of the claimed nine-function public interface could therefore pass.
That contradicted the recorded exact public surface and would allow later-story
interfaces to be absent rather than present as strict default-off no-ops from
the start of Phase 04.

The reviewer also required the frontend export rule to be expressed as exact
closure: one non-async `export function readTableSemantics(item)` declaration
and no other export token or form. The prior expression explicitly admitted an
async declaration and did not prove absence of a second export form. Standalone
default/list forms were not retained as accepted witnesses; they are recorded
as required direct fail-closed regressions so the implementation claim and
executable rule are identical.

A follow-up probe against the first remediation patch found two concrete
CommonJS export escapes: assignment through the unmasked `module` object and
assignment through the unmasked `exports` object. Both forms preserved the one
ES-module export token while creating an additional runtime export. They remain
blocking findings on that superseded patch.

## Required remediation

- Require exact set equality between observed public backend functions and all
  nine frozen signatures.
- Keep later-story functions present from US01 but strict default-off/no-op
  until their owning story is enabled.
- Add missing-public and extra-public negative regressions.
- Replace partial positive fixtures with the complete safe nine-function
  surface.
- Require exactly one frontend `export` token and one matching, non-async
  `readTableSemantics` function declaration.
- Add direct regressions for async, default, named-list, and additional export
  forms.
- Reject unmasked CommonJS `module` and `exports` identifiers and retain both
  accepted witnesses as negative regressions.
- Reseal the decision, JSON, guard, tests, verification, and identity-bearing
  reports before another independent review.

This record grants no approval and changes no production behavior or story
status.
