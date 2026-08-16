# Phase Impact Summary

Status: Historical tracker-impact snapshot; canonical P00-US04 is now Done

> **2026-07-29 supersession:** The approved Phase 0 split changes the canonical
> portfolio to 69 stories/322 points and Phase 0 to 10 stories/44 points. The
> table below is retained as the original 2026-07-28 impact snapshot. See
> [`P00-US04-scope-split.md`](../../../phase-00-baseline/decisions/P00-US04-scope-split.md).

> **2026-08-01 estimate update:** P03-US07 and P03-US08 were each re-estimated
> from 3 to 5 points after independent Definition-of-Ready audits. The current
> Phase 03 plan is 8 stories/38 points and the canonical portfolio is 69
> stories/326 points. The table below remains the historical 2026-07-28
> snapshot.

> **2026-08-08 latency supersession:** Any latency language in this historical
> snapshot is non-operative for Phases 04–08. Their sole current comparator is
> [`latency-reference-v1.md`](../latency-reference-v1.md); non-latency evidence
> remains unaffected.

## Portfolio impact

| Phase | Previous | Proposed | Benchmark impact |
|---|---:|---:|---|
| 00 — Baseline | 3 stories / 13 pts | 5 / 23 | Add reviewed corpus registration and immutable semantic runner |
| 01 — Shared IR | 4 / 20 | 4 / 20 | Add field-level provenance, links, asset origin, bbox roles, and body/full serialization evidence |
| 02 — Text Integrity | 6 / 25 | 6 / 25 | Expand bad-map, symbol, boundary, numeric, short-token, OCR-noise, and dedup controls |
| 03 — Layout | 4 / 18 | 8 / 34 | Add redlines, forms/key-values, outlines, and running-region/page identity stories |
| 04 — Tables | 3 / 13 | 4 / 20 | Add candidate/false-table gate; re-estimate cell/span fidelity 3→5 |
| 05 — Charts & Diagrams | 10 / 48 | 10 / 48 | Add eight chart and three diagram cases, explicit/derived evidence, and hard negatives |
| 06 — Visual Models | 6 / 30 | 6 / 30 | Add generated-vs-source, flag/blank-region, value, and direction grounding |
| 07 — Cross-format | 9 / 43 | 9 / 43 | Add explicit M5 readiness blocker for missing semantic twins |
| 08 — Production Hardening | 12 / 58 | 12 / 58 | Add performance observations, silent-failure calibration, review, origin, and canary gates |
| **Total** | **57 / 268** | **64 / 301** | **7 new stories; one 3→5 re-estimate** |

No new phase is justified. Every confirmed gap fits an existing coherent
capability area.

## Regression impact by phase

- **Phase 00:** validate all 15 hashes/annotations, expert evidence masks,
  immutable run IDs, missing/partial/error cases, and category metrics.
- **Phase 01:** round-trip links, text-run evidence, source/derived assets,
  child geometry, alternatives, body/full Markdown, and duplicate controls.
- **Phase 02:** add catastrophe bad fonts; clinical/ESG/postal/settlement symbol
  spans; visual OCR noise; repeated/short labels; healthy/non-target controls.
- **Phase 03:** add all captions/notes/footnotes, clinical columns, purchase
  redline, ACORD forms, datasheet pairs/lists, legal clauses, and printed pages.
- **Phase 04:** add health false table, ACORD grids, component key-values,
  13-column timetables, clinical tables, and finance/postal positive controls.
- **Phase 05:** add vector/raster, multi-panel, stacked, bubble, callout,
  time-series, pinout, flowchart, and undirected-association cases.
- **Phase 06:** add New Zealand/Australia, blank signature, unmarked description,
  unsupported chart value and direction, and no-model fallback controls.
- **Phase 07:** no exit until direct-image, image-only-PDF, embedded-image,
  scanned, and Office semantic twins exist and pass.
- **Phase 08:** add `ny-timetable` latency, `uber-earnings` RSS, zero-warning
  silent failures, confidence hard negatives, review packets, asset origins, and
  full-corpus canary thresholds.

Every affected behavior story requires:

1. its cited target case;
2. a related positive case;
3. a non-target regression case;
4. a negative or ambiguous control;
5. JSON/Markdown assertions and API contracts;
6. bbox/provenance/confidence/concern assertions where applicable;
7. phase and prior-phase regressions;
8. before/after quality and resource evidence.

## Feasibility assessment

| Assessment | Capabilities |
|---|---|
| Feasible with current stack | Benchmark contracts/runs; caption/note/link relationships; printed pages; redline vector-rule association; static forms; outlines; table validation; coordinate-aware OCR reconciliation; canonical serialization; vector chart labels/marks; basic diagram topology; telemetry |
| Feasible but costly | Raster chart measurement; dense-table alternatives; complex diagram CV; multi-language OCR assets; confidence calibration/review operations; optional local models; full cross-format adapters |
| Optional hosted/local model may help | Open-ended image descriptions, fine-grained icon/flag identity, ambiguous raster diagram/chart structure |
| Not reliably achievable from source alone | Exact hidden chart datasets; exact values with no printed/embedded evidence; direction without arrowheads/semantics; absent continuation pages; blank signatures/values; unsupported URL targets |
| Currently unknown or blocked | Source redistribution/custody; expert sidecars/datasets; acceptable performance budgets; M5 twin availability; hosted privacy/residency/vendor policy; production confidence calibration sample size |

## Product-flow safety

- New behavior remains default-off where risky.
- Existing public fields are not removed.
- Canonical and legacy projections coexist until compatibility approval.
- Every chart/model story must fall back without fabricated values.
- Every new capability has a narrower feature flag or benchmark-only boundary.
- One story is implemented, tested, reported, and approved before another begins.
