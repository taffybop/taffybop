# P02-US05 Verification Evidence

Date: 2026-07-30  
Status: Pass

## Scope and compatibility

- Numeric-safe OCR cleanup is enabled only by
  `PARSER_OCR_NUMERIC_CLEANUP_V2_ENABLED=true`; it is off by default and has no
  dependency on shared IR or the font/reconciliation flags.
- The enabled path joins only complete uppercase ASCII digest runs with an
  adjacent explicit ASCII label, at least one `A`–`F`, and the exact declared
  MD5/SHA or standard generic-digest length.
- Decimal-only, unlabeled, generic-ID, lowercase, punctuated, partial,
  distant-context, and Unicode-confusable runs remain tokenized.
- Raw OCR token text, geometry, confidence, pass, index, and word count do not
  change. No public diagnostic field is added or removed.
- The disabled path invokes the untouched permissive helper and omits new
  keywords at adapter, pipeline, and selective-render boundaries.

## Acceptance coverage

1. The retained catastrophe diagnostic contains the exact 48-digit legacy join
   at the exact source SHA-256, bbox, and `word_count=12`. Enabled cleanup
   restores `2015 2020 2025` repeated four times as twelve tokens.
2. Synthetic `2010`–`2021` also remains twelve tokens, and no enabled target
   emits a fused 48-digit value.
3. All 35 explicit MD5/SHA and generic
   hash/checksum/digest/fingerprint controls at accepted standard lengths join
   exactly.
4. All 16 numeric and ambiguous identifier non-target controls remain
   byte-equivalent after whitespace normalization.
5. All four over-bound controls fail closed without truncation, a partial join,
   or legacy fallback; exact inclusive bounds remain eligible.

## Independent security and correctness review

The independent review approved the final production snapshot and the separate
final runner/custody snapshot. It verified:

- complete maximal-run evaluation and exact label/length matrices;
- decimal and non-decimal signal separation;
- ASCII-only context authorization and rejection of long-s, dotless-i,
  Cyrillic, and full-width confusables;
- fixed line/token/fragment/candidate bounds and linear traversal;
- embedded-image, rendered-region, direct-raster, selective-span, standard,
  sparse, and pass-reconciliation propagation;
- unchanged raw token/bbox/confidence/pass evidence and public schema;
- exact default-off observer call shapes and output;
- P02-US03 and P02-US04 interaction compatibility; and
- retained input, policy, code, configuration, documentation, test, and prior
  metric custody.

The review initially blocked Unicode-aware `str.upper()` authorization because
some non-ASCII labels folded into allowlisted ASCII. Production now rejects all
non-ASCII label context before case normalization, with independent regression
coverage. It also blocked an evidence-only US04 JSON-level mismatch; the
runner now reads and pins the finalized retained `summary` contract.

## Corpus and performance evidence

The final runner used two warmups and ten measured samples. It exercises the
pure production line cleanup; it does not invoke Tesseract, PDFium, Docling,
the document pipeline, a layout model, or a hosted model. The historical
target is exact retained Phase 0 output; other policy classes are deterministic
controls and are labeled as such.

| Measure | Result |
|---|---:|
| Retained observed year tokens | 12/12 |
| Synthetic sequential year tokens | 12/12 |
| Enabled decimal false joins | 0 |
| Approved digest joins / flag-off compatibility | 35/35 / 35/35 |
| Numeric non-target controls | 16/16 |
| Resource-bound fail-closed controls | 4/4 |
| Healthy cleanup p50 / p95 / max | 0.132667 / 0.142625 / 0.142625 ms |
| Healthy additive p95 overhead | 0.000305% |
| Conservative cumulative Phase 02 p95 ceiling | 3.093762% |
| Maximum isolated peak-RSS increment | 98,304 bytes |
| Semantic output size | 15,671 bytes |
| Hosted requests / tokens / cost | 0 / 0 / $0 |

The cumulative ceiling is an arithmetic reference across independently
measured components, not a paired full-parser percentile.

Machine-readable custody, target/control output, timing, size, RSS, and
compatibility evidence is retained in
[P02-US05-numeric-cleanup-metrics.json](P02-US05-numeric-cleanup-metrics.json),
SHA-256
`5b347a6f98c47d9df3b52cfef40bb5c6bb5824f149cc8da6806cc23d5e3a174c`.
Its deterministic semantic payload SHA-256 is
`e0febf0c4dbf81e7390efd02db5a149370c69c6c82b358ddeef7099741bcc756`.

## Test gates

- Final focused story, contract, regression, independent adversarial,
  performance, and retained-artifact gate: **124 passed**.
- Complete Phase 0–2 story, contract, regression, and performance gate:
  **1,103 passed**.
- Complete backend suite: **1,180 passed, 10 documented opt-in skips**, and one
  existing Starlette/httpx deprecation warning.
- Python compilation: **Pass**.
- Dependency integrity: **Pass**; `pip check` reports no broken requirements.
- Retained JSON identity, custody, and semantic assertions: **Pass**.
- Independent final production/security review: **Pass**.
- Independent final metrics/custody review: **Pass**.

The 10 skips are the existing real image-model, Docling/finance sample, and
shared-analysis integration gates, each requiring its documented opt-in
environment variable. No P02-US05 criterion depends on a skipped test.

## Dependency and rollback

P00-US03 and P02-US01–US04 are Done. No new Python package, OCR engine,
language asset, model, hosted service, network dependency, or runtime download
was added.

Set `PARSER_OCR_NUMERIC_CLEANUP_V2_ENABLED=false` to invoke the exact legacy
cleanup and call shape. Raw token evidence is unchanged either way; rollback
may intentionally restore the known decimal false join.
