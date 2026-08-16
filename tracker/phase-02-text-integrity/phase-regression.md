# Phase 02 Regression Plan

Run Phase 00–02 regression, API/schema contracts, serializer parity, and all
existing OCR/PDF/image suites.

Required fixture classes:

- wrong-but-present `/ToUnicode`;
- missing `/ToUnicode`;
- healthy Type0 and WinAnsi fonts;
- non-identity CID-to-GID negative control;
- no embedded font;
- multilingual/Unicode text;
- scanned-only text;
- repeated numeric chart labels;
- genuine long hexadecimal identifiers;
- short low-confidence tokens with and without corroborating geometry.

LlamaParse-15 fixtures:

- target font/Unicode: catastrophe-recap p1 damaged narrative/chart runs and
  esg-metrics p1 notes 3–7;
- target word/symbol boundaries: clinical-study pp1/4, purchase-agreement p1
  marked opening/date text, and settlement-agreement p1 `Look-Back`;
- target OCR reconciliation: clean-energy p1 chart, clinical-study p3 flowchart,
  egov-survey p1 chart, ny-timetable pp1–2 `ew`/`741`, postal-10k p1
  `CIO`/`ClO`/`FERS`, and uber-earnings pp1–2 image/chart text;
- positive healthy controls: finance-10k pp1–3 native financial tables and
  source-supported prose/tables in settlement-agreement;
- non-target controls: unsupported expert chart values stay absent, distinct
  repeated labels stay distinct, and visible native construction text is not
  repaired by guessing;
- negative controls: ambiguous/missing/non-identity font maps, off-page/oversized
  crops, OCR timeout, conflicting scripts, identical overlapping OCR, isolated
  short noise, decimal sequences, and genuine split-hex identifiers.

Gates:

- no healthy-text rewrite;
- no ungrounded semantic completion;
- every repair has bbox/method/evidence;
- page OCR area and latency stay within target;
- all reviewed target spans are exact or explicitly unresolved, with 0
  source-incorrect OCR candidates admitted to canonical text;
- v1 JSON/Markdown compatibility remains explained and tested.

Compare p50/p95 latency and peak RSS to P00-US10 (p50 9.06 s, p95/max
46.76 s, median/max RSS 1,437/2,590 MiB); healthy-PDF p95 overhead must remain
at or below 10%.

## P02-US01 completed gate

P02-US01 closed on 2026-07-30:

- the focused story/adversarial/structural/anomaly/contract/regression/corpus/
  performance gate passed 34 tests;
- the complete Phase 0–2 story, contract, regression, and performance gate
  passed 761 tests;
- the complete backend passed 838 tests with 10 documented opt-in skips and one
  existing Starlette/httpx deprecation warning;
- all 15 corpus cases/30 pages matched their exact registered font-audit
  expectations: 2/2 malformed target subsets and 0/14 healthy-case false
  positives;
- output was deterministic for 15/15 cases, cache reuse was 83/178, and healthy
  additive p95 overhead was 2.461017%, below 10%;
- compilation, dependency integrity, retained JSON validation, flag-off parity,
  and two independent reviews passed.

## P02-US02 completed gate

P02-US02 closed on 2026-07-30:

- the final focused story/adversarial/contract/regression/corpus/metrics/
  performance gate passed 39 tests;
- the complete Phase 0–2 story, contract, regression, and performance gate
  passed 800 tests;
- the complete backend passed 877 tests with 10 documented opt-in skips and one
  existing Starlette/httpx deprecation warning;
- all 15 corpus cases were deterministic, all 14 healthy cases short-circuited
  with zero rewrites, and the catastrophe recovered 2 fonts/29 runs/150
  uniquely grounded glyphs;
- the exact target sentence and 24/24 reviewed chart/source regions passed;
- the conservative audit-plus-recovery healthy p95 ceiling was 2.472635%, below
  10%, with a maximum isolated recovery peak-RSS increment of 5,242,880 bytes;
- exact-PDF audit binding, Unicode `Cf` refusal, bounded live-glyph state,
  document-wide cmap budget, inner-loop deadlines, compilation, dependency
  integrity, retained JSON validation, flag-off parity, and independent
  code/security and corpus/performance reviews passed.

## P02-US03 completed gate

P02-US03 closed on 2026-07-30:

- the final focused story, contract, regression, and performance gate passed 62
  tests;
- the complete Phase 0–2 story, contract, regression, and performance gate
  passed 862 tests;
- the complete backend passed 939 tests with 10 documented opt-in skips and one
  existing Starlette/httpx deprecation warning;
- all 4 exact-source-bound unresolved target spans produced bounded real
  PDFium/Tesseract crops, candidates, and tokens with complete affine/pass/cost
  evidence;
- 25 healthy same-page neighbors and all 14 healthy corpus controls produced
  zero selective renders;
- healthy selective-planning p95 overhead was 0.010887%; the conservative
  audit + recovery + selective ceiling was 2.483522%, below 10%;
- pre-allocation and realized resource bounds, deadlines, IPC/process cleanup,
  recovery-provenance checks, compilation, dependency integrity, retained JSON
  validation, default-off/canonical parity, and independent final
  security/correctness review passed.

## P02-US04 completed gate

P02-US04 closed on 2026-07-30:

- the final focused story, adversarial, contract, regression, performance, and
  retained-artifact gate passed 117 tests;
- the complete Phase 0–2 story, contract, regression, and performance gate
  passed 979 tests;
- the complete backend passed 1,056 tests with 10 documented opt-in skips and
  one existing Starlette/httpx deprecation warning;
- all 15 exact corpus inputs passed flag-off parity, flag-on round-trip parity,
  presentation preservation, and exact re-entry;
- the catastrophe retained 29 source-bound terminal groups: 2 already-primary
  prose runs unchanged, 24 owner-linked chart runs unresolved, and 3 ownerless
  runs unresolved, with zero ownerless selections;
- evidence, reason, schema, and alternative coverage were 100%; canonical
  duplicates, alternate leaks, surface disagreements, unretained evidence, and
  semantic completions were zero;
- healthy reconciliation p95 overhead was 0.609935%, and the conservative
  cumulative Phase 02 ceiling was 3.093457%, below 10%;
- compilation, dependency integrity, manifest re-entry authentication,
  transactional forged-state quarantine, retained artifact custody,
  default-off parity, and independent production/security and metrics/custody
  reviews passed.

## P02-US05 completed gate

P02-US05 closed on 2026-07-30:

- the final focused story, contract, regression, independent adversarial,
  performance, and retained-artifact gate passed 124 tests;
- the complete Phase 0–2 story, contract, regression, and performance gate
  passed 1,103 tests;
- the complete backend passed 1,180 tests with 10 documented opt-in skips and
  one existing Starlette/httpx deprecation warning;
- the exact retained 12-label catastrophe line and synthetic sequential-year
  control each remained 12 tokens with zero enabled-path decimal false joins;
- 35/35 approved labeled digest controls joined, 16/16 numeric/ambiguous
  controls remained unchanged, and 4/4 resource-bound cases failed closed;
- raw OCR token text, bbox, crop bbox, confidence, pass, index, and word count
  remained exact across flag states;
- healthy cleanup p95 was 0.142625 ms / 0.000305%, and the conservative
  cumulative Phase 02 ceiling was 3.093762%, below 10%;
- compilation, dependency integrity, exact default-off call/output parity,
  retained code/config/docs/test custody, and independent production/security
  and metrics/custody reviews passed.

## P02-US06 completed gate

P02-US06 closed on 2026-07-30:

- the final focused story, contract, regression, performance, and
  retained-artifact gate passed 56 tests;
- the complete Phase 0–2 story, contract, regression, and performance gate
  passed 1,159 tests;
- the complete backend passed 1,236 tests with 10 documented opt-in skips and
  one existing Starlette/httpx deprecation warning;
- all 12 retained catastrophe year positions have exact text, bbox,
  confidence, stable IDs, and selected-primary state;
- overlapping equivalents retain one selected winner and one diagnostic with
  zero duplicate primary occurrences; distant equal text remains distinct;
- exact `iH` evidence and grounded short controls remain attributable and
  presentation-inert, with zero negative promotions or canonical short noise;
- healthy projection p95 was 0.731292 ms / 0.001564%, and the conservative
  cumulative Phase 02 ceiling was 3.095326%, below 10%;
- resource fail-closed behavior, exact default-off parity, atomic retained
  evidence custody, and independent production/security and metrics/custody
  reviews passed.

## Phase 02 completed exit gate

Phase 02 closed on 2026-07-30 at 6/6 stories and 25/25 points:

- the focused Phase 02 exit gate passed **112 tests**, and the frozen retained
  artifact contract passed **3 tests**;
- the complete backend passed **1,351 tests with 10 documented opt-in skips and
  one existing warning in 69.22 seconds**;
- the Node 22.18 frontend `npm run check` gate passed lint, typecheck,
  production build, 42 unit tests, and 1 bundle test;
- all 15 enabled/predecessor full-parser pairs passed exact worker custody,
  source/input identity, public-result recomputation, and offline/zero-hosted
  checks;
- all five affected target cases passed: clinical-study selected 5 owners,
  esg-metrics 5, postal-10k 2, purchase-agreement 1, and
  settlement-agreement 1; the catastrophe exact target also passed;
- non-target selection and change counts were zero; all paired control
  canonical-text, Markdown, and public-result parity checks passed;
- approved owner drift passed for all 15 cases, and every component flag-off
  projection remained exact;
- the exact 2-warmup × 10-sample component screen recorded
  `ny-timetable` as the worst healthy case at 400.882292 ms /
  0.857318845%, producing a conservative cumulative Phase 02 ceiling of
  3.952645047%, below 10%;
- hosted requests, tokens, and cost were zero, and the maximum process
  high-water RSS increment was zero bytes. This means no new lifetime
  high-water mark, not zero memory consumption;
- the source-alignment flag remains default off, one-flag rollback restores the
  completed P02-US06 path, and no package, model, hosted service, network
  dependency, or runtime download was added.

The retained artifact is
`evidence/P02-source-text-alignment-metrics.json` (439,414 bytes), SHA-256
`6fdd74cb7adece95ae4a67cc98d1d02e3ca071f9166d4c8c26150768114dbacb`,
with semantic SHA-256
`fcc2bf63c145347f8a7a40876dd60247e684e2d3616860b479f74c7d8240b558`.
All Phase 03 stories remain Proposed and no Phase 03 implementation has
started.
