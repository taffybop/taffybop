# Phase 02 Metrics

| Metric | Before | Target | After |
|---|---:|---:|---:|
| Catastrophe damaged sentence exact match | Fail | Pass | P02-US02: exact once in projected and canonical JSON/text/Markdown |
| Bad-font detection recall | Absent | 100% on curated bad-font fixtures | P02-US01: 2/2 malformed catastrophe font subsets detected with stable reason codes (100%) |
| Healthy-font false-positive rate | Unmeasured | 0% on phase fixtures | P02-US01: 0/14 approved healthy corpus cases across 29 pages, plus all registered synthetic healthy controls (0%) |
| Repaired spans with evidence/provenance | 0% | 100% | P02-US02: 150/150 recovered glyphs grounded with unique font/CID/glyph/bbox/method evidence |
| Whole-page OCR on otherwise healthy catastrophe page | Not run | Not run | P02-US03: 0 broad-page renders; 25 healthy same-page spans and 14/14 healthy controls remained render-free |
| Selective OCR area | N/A | Only unresolved bbox + bounded padding | P02-US03 real path: 4 crops, 958.16 pt², 0.197679% cumulative page area, 23,954 pixels |
| Repeated year positions preserved | Lost in primary item | 12/12 | P02-US06: 12/12 exact text/bbox/confidence occurrences have stable distinct IDs and selected-primary state |
| Pure-year hex-join false positives | 1 observed run | 0 | P02-US05: 0; exact retained `2015 2020 2025` ×4 and synthetic `2010`–`2021` each remain 12 tokens |
| Unsupported semantic completions | 0 by policy | 0 | P02-US04: 0 across all actual and deterministic control outcomes |
| p95 text-integrity overhead on healthy PDFs | 0 baseline | ≤ 10% | Phase exit: source-alignment worst healthy component p95 400.882292 ms / 0.857318845%; cumulative conservative ceiling 3.952645047% (retained P02-US06 ceiling 3.095326201% + source alignment); independently measured components, not a paired full-parser percentile |
| Reviewed Unicode/font target spans | Corrupt in catastrophe-recap p1; unflagged | 100% audited; deterministic recovery or explicit unresolved concern | P02-US02: exact target sentence, 24/24 reviewed regions, 2 fonts/29 runs/150 grounded glyphs; unsafe cases explicit refusals |
| Reviewed word-boundary/symbol targets | Failures in clinical-study pp1/4, esg-metrics p1, purchase-agreement p1, and settlement-agreement p1 | 100% exact on approved target spans; 0 healthy-control rewrites | Phase exit: 5/5 affected cases pass with 5 clinical, 5 ESG, 2 postal, 1 purchase-agreement, and 1 settlement-agreement source-bound selections; catastrophe exact target also passes; 0 non-target selections and 0 non-target page changes |
| False/duplicate OCR admitted to primary text | Confirmed in clean-energy, clinical-study, egov-survey, health-report, manufacturing-report, ny-timetable, postal-10k, and uber-earnings | 0 reviewed false/duplicate candidates in primary text; alternatives remain attributable | P02-US04: 0 canonical duplicate identities, 0 alternate leaks, and 0 selection-surface disagreements; the corpus lacks a reviewed typed candidate registry, so historical candidate-level closure remains explicitly unclaimed |
| Selective OCR terminal and evidence coverage | 0 | 100% terminal outcomes and complete attributable candidate evidence | P02-US03: 8/8 target outcomes terminal; 4/4 real candidates and 4/4 real tokens complete and unique |
| Candidate selections with method/bbox/reason | Ad hoc | 100% | P02-US04: evidence, reason, schema, and alternative coverage each 100%; 0 unretained decision evidence IDs |
| Unsupported OCR-driven semantic completions | 0 by policy | 0 | P02-US04: 0 |
| Corpus performance reference | p50 9.06 s; p95/max 46.76 s; median/max RSS 1,437/2,590 MiB | Record per-case deltas; healthy-PDF p95 overhead ≤ 10% | Phase exit: exact 2 warmups + 10 samples per healthy case; worst case `ny-timetable` p95/max 400.882292 ms, 0.857318845%; cumulative conservative ceiling 3.952645047%; maximum process high-water RSS increment 0 bytes and hosted requests/tokens/cost 0/0/$0 |

The retained phase-exit artifact is 439,414 bytes with SHA-256
`6fdd74cb7adece95ae4a67cc98d1d02e3ca071f9166d4c8c26150768114dbacb`;
its 418,996-byte semantic payload has SHA-256
`fcc2bf63c145347f8a7a40876dd60247e684e2d3616860b479f74c7d8240b558`.
The zero RSS increment means the measured operations did not exceed the
process's already-established lifetime high-water mark; it does not mean zero
memory use. With ten observations, nearest-rank p95 is the observed maximum.
