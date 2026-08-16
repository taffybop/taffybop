# P00-US10 Immutable Corpus Semantic Report

- Run: `lat-us01-current-runtime-baseline-20260809-r01`
- Cases/pages: 15/30
- Reviewed masks: 210 claims; 109 literal; 162 semantic; 48 unsupported exclusions
- Automated semantic scoring: 0; diagnostic-only eligible claims: 162
- Stable JSON/Markdown outputs: `False`
- Hosted/model cost: 0 requests, 0 tokens, USD 0.00

No single aggregate quality score is produced.

## Dimensions

| Dimension | Claims | Semantic eligible | Scored | Diagnostic | Excluded |
|---|---:|---:|---:|---:|---:|
| text | 77 | 74 | 0 | 74 | 3 |
| layout | 45 | 38 | 0 | 38 | 7 |
| reading_order | 9 | 9 | 0 | 9 | 0 |
| table | 30 | 21 | 0 | 21 | 9 |
| chart | 14 | 8 | 0 | 8 | 6 |
| diagram | 8 | 5 | 0 | 5 | 3 |
| markdown | 0 | 0 | 0 | 0 | 0 |
| json | 27 | 7 | 0 | 7 | 20 |
| hallucination | 0 | 0 | 0 | 0 | 0 |
| diagnostics | 0 | 0 | 0 | 0 | 0 |
| performance | 0 | 0 | 0 | 0 | 0 |
| cost | 0 | 0 | 0 | 0 | 0 |

## Performance

- Case latency p50/p95: 12843.339/50363.145 ms
- Peak RSS p50/max: 1101.06/2134.89 MiB
- Frozen-environment comparable / within 25% tolerance: `False` / `None`

## Semantic boundary

Eligible narrative review rows remain diagnostic-only because they do not yet contain executable expected-value predicates. Incorrect, inferred, and unverifiable expert claims remain explicitly excluded and cannot enter a scored denominator.
