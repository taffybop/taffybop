# P03-US08 Hardened Phase 04 Tables Renewal — Independent Review 09 (Blocked)

Status: **BLOCKED — no approval granted**  
Reviewed: 2026-08-04  
Scope: Pre-seal static-scope and guard-quality review after review 08 remediation

## Candidate reviewed

| Artifact | Bytes | Raw SHA-256 |
|---|---:|---|
| Decision | 25,343 | `bb3107b29f5a01876a64ee0179e1bff32b16bb93ecffa51da2f54c2d65510682` |
| Machine-readable renewal | 22,113 | `5d0ac8411fd785eda1db1cbc01d2082ea09d65482ddba4796982cf0f60db4655` |
| Executable custody guard | 339,873 | `ddaa463d92d0a1e92a8591433789e3649d0b47e1de045c96be3ad59a7e9f9273` |
| Focused guard tests | 187,391 | `6595a74ddcc9ae110df92681a99450a32062166b27239477b030faab7f8d51ff` |
| Administrative metrics/custody contract | 165,157 | `3862f5d386f0bf4440da646d1cc7603dedb7f14cf694d275da49a6d9d0c97e75` |
| Blocked independent review 08 | 4,802 | `cf4551c6ff5c47d25c7a42e3d57285e43aa18fa838a90c9cbd4b8307b2879bfa` |

The decision and renewal JSON were unchanged from v9; the JSON semantic
SHA-256 remained
`a8e38c8269e5faf1e03f5bff942dd97b74bea87f6ae26f9c6c175e50ed6eba87`.
This was deliberately a pre-seal review: the verification record had not yet
been amended to bind review 08 or the candidate guard identities.

## Blocking findings

1. **IR09-BE-SCOPE-01 — runtime formatted-value reconstruction.** The complete
   table-semantics validator accepted enabled replay output built with constant
   arithmetic inside f-strings, including `f"Phase {10 // 2}"` and
   `f"P{10 // 2:02d}"`. The same gap permitted character formatting that
   assembled `runningRegion`. Unknown but approved calls inside formatted
   values—such as `len`, `sum`, `round`, and `int`—also passed because the
   static fold silently dropped an unresolved `FormattedValue`.
2. **IR09-BE-SCOPE-02 — static reorder/decode reconstruction.** The common
   Python scope layer admitted static slicing/reversal and byte decoding,
   including `"50P"[::-1]`, `"".join(reversed("50P"))`, exact byte lists, and
   hexadecimal byte text. These cases can produce `P05` without any direct
   forbidden literal.
3. **IR09-FE-SCOPE-01 — static index and slice reordering.** Both the frontend
   text validator and exact helper validator accepted numeric index, `at`, and
   `slice` expressions that reordered inert literals into `P05` or `Phase05`.
   The confirmed forms included direct literals, simple aliases, and a literal
   nested in an array.
4. **IR09-FE-SCOPE-02 — computed numeric reconstruction.** The frontend guard
   accepted a locally computed numeric value combined with a partial scope
   literal, for example a value derived from `Number("10") / Number("2")`
   appended to `"phase"`. The arithmetic detector recognized only adjacent raw
   numeric tokens, not constant conversions or aliases.

## Execution evidence

- Complete focused guard on the reviewed candidate: **492 passed**, zero
  failed or skipped, **1** documented Starlette/httpx deprecation warning in
  29.27 seconds.
- Complete non-waived P03 metrics/custody contract: **122 passed, 1 expected
  strict-final skip, 1 warning** in 21.96 seconds.
- Controlled evaluation was used only to confirm the returned values of the
  small reviewer-authored reproducers; the renewal scanner itself did not
  execute candidate Python or JavaScript.

Attempt 48 remained failed at **0.050946750 seconds** against the unchanged
**0.050000000-second** ceiling (**0.000946750 seconds / 1.8935%**, maximum
**5%** candidate-specific). Canonical strict-final evidence remained absent,
the companion remained quarantined, all non-waived gates remained stated,
and the 55-artifact failed-history manifest remained
`bca401f2207619ba84422e020104b9a609e0be0f4dc2b42f3ae4fb53d315ceff`.
No production or story-status change occurred.

## Required disposition

This review grants no approval and must never be reclassified. Remediation
requires bounded exact arithmetic for static Python scalars; fail-closed
handling of unresolved formatted values when their fixed fragments can form
forbidden scope; bounded static slicing/reordering/byte decoding; frontend
closure for arithmetic and literal index/`at`/`slice` reordering; permanent
regressions; complete reruns; resealed identities; and a new independent
review. No production or status change may rely on this candidate.
