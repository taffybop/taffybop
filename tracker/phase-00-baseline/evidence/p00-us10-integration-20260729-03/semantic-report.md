# P00-US10 Immutable Corpus Semantic Report

- Run: `p00-us10-integration-20260729-03`
- Cases/pages: 2/2
- Reviewed masks: 29 claims; 16 literal; 25 semantic; 4 unsupported exclusions
- Automated semantic scoring: 0; diagnostic-only eligible claims: 25
- Stable JSON/Markdown outputs: `True`
- Hosted/model cost: 0 requests, 0 tokens, USD 0.00

No single aggregate quality score is produced.

## Dimensions

| Dimension | Claims | Semantic eligible | Scored | Diagnostic | Excluded |
|---|---:|---:|---:|---:|---:|
| text | 11 | 11 | 0 | 11 | 0 |
| layout | 7 | 7 | 0 | 7 | 0 |
| reading_order | 2 | 2 | 0 | 2 | 0 |
| table | 1 | 1 | 0 | 1 | 0 |
| chart | 4 | 2 | 0 | 2 | 2 |
| diagram | 0 | 0 | 0 | 0 | 0 |
| markdown | 0 | 0 | 0 | 0 | 0 |
| json | 4 | 2 | 0 | 2 | 2 |
| hallucination | 0 | 0 | 0 | 0 | 0 |
| diagnostics | 0 | 0 | 0 | 0 | 0 |
| performance | 0 | 0 | 0 | 0 | 0 |
| cost | 0 | 0 | 0 | 0 | 0 |

## Performance

- Case latency p50/p95: 8466.604/9365.937 ms
- Peak RSS p50/max: 1343.53/1428.77 MiB
- Frozen-environment comparable / within 25% tolerance: `True` / `True`

## Semantic boundary

Eligible narrative review rows remain diagnostic-only because they do not yet contain executable expected-value predicates. Incorrect, inferred, and unverifiable expert claims remain explicitly excluded and cannot enter a scored denominator.
