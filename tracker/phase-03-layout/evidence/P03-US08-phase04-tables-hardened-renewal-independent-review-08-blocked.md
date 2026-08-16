# P03-US08 Hardened Phase 04 Tables Renewal — Independent Review 08 (Blocked)

Status: **BLOCKED — no approval granted**  
Reviewed: 2026-08-04  
Scope: Final contract, Phase-boundary/security, and metrics/custody review of
the frozen v9 hardened renewal bundle

## Frozen bundle reviewed

| Artifact | Bytes | Raw SHA-256 |
|---|---:|---|
| Decision | 25,343 | `bb3107b29f5a01876a64ee0179e1bff32b16bb93ecffa51da2f54c2d65510682` |
| Machine-readable renewal | 22,113 | `5d0ac8411fd785eda1db1cbc01d2082ea09d65482ddba4796982cf0f60db4655` |
| Executable custody guard | 309,919 | `c26abdaf58ee8f69d4aef0df52150b01900008e9935ae2918c1f14c273c2addc` |
| Focused guard tests | 181,765 | `7434d601c6ae393fbb2179f9bb01bea95d8029afd253832d9f8cfaf8fda9eb71` |
| Administrative metrics/custody contract | 165,157 | `3862f5d386f0bf4440da646d1cc7603dedb7f14cf694d275da49a6d9d0c97e75` |
| Verification record | 12,187 | `9977e1533e4c2e195c28f1c97366b75c7b621bb8bbc0ef69fc4bb30a4085e6f2` |

The renewal JSON semantic SHA-256 independently recomputed to
`a8e38c8269e5faf1e03f5bff942dd97b74bea87f6ae26f9c6c175e50ed6eba87`.
All supplied identities matched at review start. The executable guard and
focused tests changed after the reviewers reported their blockers, so those
later candidates were not part of this frozen review.

## Blocking findings

1. **IR08-BE-SCOPE-01 — Python mapping/set reconstruction.** The backend scope
   scanner reconstructed list and tuple literals but omitted dictionaries and
   sets. It accepted a helper whose returned mapping used
   `"".join({"Phase ": 0, "05": 1})`; controlled execution returned exactly
   `{"scope": "Phase 05"}`. A set-based equivalent was also admitted. Three-
   and higher-fragment container orderings therefore remained outside the
   claimed reconstructed-string closure.
2. **IR08-BE-SCOPE-02 — formatted and aliased reconstruction.** The exact
   nine-function backend helper surface accepted enabled-path values built as
   `f"Phase {5}"`, `f'run{"ningRegion"}'`, and
   `first = "Ph"; second = "ase05"; scope = first + second`. The AST fold did
   not evaluate `FormattedValue` nodes or resolve simple constant bindings.
3. **IR08-FE-SCOPE-01 — split frontend literal reconstruction.** Both the
   frontend text validator and exact exported-helper validator accepted
   `"Ph" + "ase05"`, `["Ph", "ase05"].join("")`, the equivalent aliased and
   running-region forms, and `"tab" + "lephase05enabled"`. The raw-source
   boundary regex did not reconstruct literals split inside `phase` or
   `running`, while the masked scan removed the literals entirely.
4. **IR08-FREEZE-01 — reviewed identities changed.** Remediation of the first
   backend finding changed the guard and focused tests while the other two
   reviews were still running. Even absent the remaining findings, the v9
   identities could not receive final approval after that mutation.

## Execution evidence

- Complete focused renewal guard, independently repeated on the frozen v9
  bundle: **426 passed**, zero failed or skipped, **1** documented
  Starlette/httpx deprecation warning (observed review runtimes 27.84–28.88
  seconds).
- P03 running-region metrics/custody contract, independently repeated:
  **122 passed, 1 expected strict-final skip, 1 warning** (observed review
  runtimes 19.15–20.90 seconds).
- Combined frozen focused and metrics/custody execution: **548 passed, 1
  expected strict-final skip, 1 warning** in 48.76 seconds.
- The frozen `REQUIRED_CODE_PATHS` remained exactly 86. The exact, disjoint
  five-path Phase 04 set, pinned readiness-test identity, tested sixth-path
  rejection, exact two-state administrative contract, and byte-mutation
  rejection all passed.

Attempt 48 remained failed at **0.050946750 seconds** against the unchanged
**0.050000000-second** ceiling (**0.000946750 seconds / 1.8935%**, maximum
**5%** candidate-specific). Canonical strict-final evidence remained absent,
the companion remained quarantined, the 55-artifact failed-history manifest
remained
`bca401f2207619ba84422e020104b9a609e0be0f4dc2b42f3ae4fb53d315ceff`,
and every non-waived gate remained stated and executable. Hosted usage was
zero. All production surfaces remained at their predecessor identities.
P04-US01 remained Ready and held; later Phase 04 and every Phase 05 story
remained Proposed.

## Required disposition

This review grants no approval and must never be reclassified. Remediation
requires permanent regressions for mapping/set, formatted-value, alias, and
frontend multi-fragment reconstruction; bounded, non-executing fail-closed
scanners; resealed exact identities; complete focused and metrics/custody
gates; and a new independent review of the final frozen bundle. No production
or story-status change may rely on the v9 bundle.
