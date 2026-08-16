# P02-US06 Verification Evidence

Date: 2026-07-30  
Status: Pass

## Scope and compatibility

- Spatial OCR occurrence preservation is enabled only by
  `PARSER_OCR_SPATIAL_TOKEN_PRESERVATION_ENABLED=true`; it is off by default
  and requires numeric cleanup v2.
- The enabled path adds only `ocr_token_occurrences` and
  `ocr_occurrence_summary`. These fields do not enter the canonical IR child
  collection, Markdown, text, or existing item-selection surfaces.
- Equality is limited to Unicode NFC plus whitespace normalization. Case,
  confusables, punctuation, and recognition hypotheses are never folded.
- Disabled adapter and pipeline boundaries omit the new keyword, and disabled
  items omit both additive keys.

## Acceptance coverage

1. All twelve retained catastrophe year labels have distinct, stable,
   document-scoped occurrence IDs and exact source text, bbox, confidence, and
   selected-primary state.
2. An overlapping standard/sparse equivalent produces one selected primary
   occurrence and one attributable duplicate diagnostic.
3. The exact retained low-confidence `iH` and deterministic `iH`/`1H`
   chart/diagram controls remain selected evidence with bbox and confidence but
   never enter canonical prose.
4. Distant equal headers remain two line values and four distinct selected
   token occurrences.
5. Photo, low-confidence-floor, punctuation, invalid-geometry, non-finite,
   malformed-unit, unsupported-role, and uncorroborated short controls do not
   become short alternatives or canonical text.

## Security, resource, and independent review

Production bounds are 4,096 source tokens, 2,048 retained occurrences, 256
short alternatives, 256 Unicode code points per token, and 1 MiB of serialized
occurrence JSON per item. Invalid geometry and units fail closed; source,
occurrence, short-alternative, and serialized-size limits do not admit partial
or unbounded primary output.

Independent review found and closed:

- rounded-zero geometry, non-finite/unit handling, and fail-closed caller
  omission issues;
- quadratic distant-line comparison and exact-overlap winner-order defects;
- missing raw-text/token-confidence requirements for short alternatives;
- a mismatch between reported and actually retained primary line selection;
- binary-float defects at the inclusive 0.80 overlap and 0.95 containment
  boundaries; and
- metrics gaps for policy identity, exact target summary/confidence/selection,
  output/input collision, and atomic artifact writing.

The final production/security reviewer and the independent metrics/custody
reviewer both approved with no remaining blocker. Randomized overlap-oracle
comparison, 4,000 distant repetitions, two independent final 2-warmup ×
10-sample collections, and exact source/artifact custody all passed.

## Metrics

| Measure | Result |
|---|---:|
| Retained target occurrences | 13/13 |
| Exact selected primary years | 12/12 |
| Exact selected non-primary `iH` alternatives | 1/1 |
| Overlapping selected / diagnostic / duplicate-primary | 1 / 1 / 0 |
| Distant line values / selected tokens | 2 / 4 |
| Grounded short alternatives | 2/2 |
| Negative short promotions / canonical short noise | 0/4 / 0 |
| Enabled / disabled item bytes | 9,990 / 3,537 |
| Target projection p50 / p95 / max | 0.746750 / 0.952583 / 0.952583 ms |
| Healthy projection p50 / p95 / max | 0.668458 / 0.731292 / 0.731292 ms |
| Healthy additive p95 overhead | 0.001564% |
| Conservative cumulative Phase 02 ceiling | 3.095326% |
| Maximum isolated peak-RSS increment | 1,032,192 bytes |
| Semantic output size | 23,613 bytes |
| Hosted requests / tokens / cost | 0 / 0 / $0 |

The cumulative ceiling is an arithmetic reference across independently
measured components, not a paired full-parser percentile.

Machine-readable custody, exact target/control output, resource bounds,
timing, size, RSS, compatibility, and zero-cost evidence is retained in
[P02-US06-spatial-token-metrics.json](P02-US06-spatial-token-metrics.json),
SHA-256
`3d13129a80bdd24e01cb1f9f41b3fe3286d5662fd797a58760a647d6d79d5900`.
Its deterministic semantic payload SHA-256 is
`5deccf8a57f0e97ba119228c9709d537c92ef0b2df186acce87d34742588d7c5`.

## Test gates

- Final focused story, contract, regression, performance, and retained-artifact
  gate: **56 passed**.
- Complete Phase 0–2 story, contract, regression, and performance gate:
  **1,159 passed**.
- Complete backend suite: **1,236 passed, 10 documented opt-in skips**, and one
  existing Starlette/httpx deprecation warning.
- Python compilation and dependency integrity: **Pass**.
- Retained artifact identity, policy/source/prior-artifact custody, exact
  default-off parity, and atomic runner output: **Pass**.

The ten skips are the existing real image-model, Docling sample/finance, and
shared-analysis integration gates. No P02-US06 criterion depends on a skipped
test.

## Dependency and rollback

P02-US04 and P02-US05 are Done. No new package, OCR engine, language asset,
model, hosted service, network dependency, or runtime download was added.

Set `PARSER_OCR_SPATIAL_TOKEN_PRESERVATION_ENABLED=false` to omit the new
keyword and additive fields and restore the exact completed P02-US05 call and
projection path. Numeric cleanup v2 may remain enabled independently.
