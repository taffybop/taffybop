# P03-US07 Settlement Marker Source-Truth Addendum

Date: 2026-08-01  
Status: Accepted readiness evidence

## Purpose

This Phase 03 addendum corrects only the marker-shape shorthand in two frozen
Phase 00 records. Those records remain byte-for-byte immutable because their
identities are bound into the reviewed-claim and benchmark-control registries.
Their parenthesized `(a)`–`(c)` wording is historical shorthand, not the
literal source text, and must not be used as the P03-US07 marker oracle.

All other reviewed findings and dispositions in the frozen records remain in
force.

## Frozen-record custody

| Artifact | Bytes | SHA-256 | Treatment |
|---|---:|---|---|
| `tracker/benchmarks/llamaparse-15/cases/settlement-agreement.md` | 12,863 | `1e1680bd2b28eca6c68c364a32e1381d64ae7d5c8155325ac03c10e4d8addba9` | Immutable Phase 00 reviewed-claim input |
| `tracker/benchmarks/llamaparse-15/runs/baseline-20260728-current/settlement-agreement/comparison-report.md` | 2,879 | `cf963684ea690c163eafe9bbe742f2cad2cf74431030adb7cdd294873d34e0c3` | Immutable retained baseline comparison |

## Corrected literal source truth

The source PDF, expert JSON, and configured predecessor output all contain
literal period-style markers `a.`, `b.`, and `c.`. Their top-left PDF-point
boxes are:

| Marker | x | y | width | height |
|---|---:|---:|---:|---:|
| `a.` | 180.000 | 169.644 | 8.280 | 12.000 |
| `b.` | 180.000 | 319.644 | 9.000 | 12.000 |
| `c.` | 180.000 | 598.524 | 8.280 | 12.000 |

The authoritative custody identities are:

- source PDF: 164,483 bytes,
  `adaaf7578748ec1c215ebdfd9601a9938ec1bee918316122c56b22212a3595bc`;
- expert JSON:
  `cca63534b7853e8ea64ce106dc82629ce3172bfdaba8353cf7b7881d7af137ae`;
- reviewed current-value evidence
  (`tracker/benchmarks/llamaparse-15/runs/baseline-20260728-current/settlement-agreement/our-output.json`):
  `617cb996ee2820bb9264a861c538964121ad706c195703f19f4855bcbc8eb07c`;
- P03-US07 machine oracle semantic SHA-256:
  `e3bddd0ce86ccbf1089b2e667b4b42922b41daaa20c5051634d21646d4f58bc5`.

Inline `(i)`–`(iv)` expressions within clause `a.` remain ordinary inline
prose and are not separate outline nodes. The percentage table remains a
table between clauses `b.` and `c.` and is never itself a clause.

## Precedence

For P03-US07 marker shape, bbox, ordinal, ownership, recomposition, tests, and
metrics, this addendum and the machine oracle supersede only the historical
parenthesized marker shorthand in the two frozen records. This addendum does
not rewrite Phase 00 evidence or expand the Phase 03 story scope.

The rollback target is the configured predecessor with every non-US07 flag
left unchanged. When forms are enabled that target is the accepted US06
output; when forms are disabled it is the same configured pipeline without
US07. The reviewed current-value file above is source custody evidence, not a
claim that every flag combination serializes to that retained file.
