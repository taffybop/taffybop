# Benchmark Milestone Plan

Status: M0/Phase 0 executable baseline complete; later milestones Proposed

## Measurement contract

Every milestone compares four evidence sets:

1. the previous approved parser run;
2. the current candidate run;
3. the LlamaParse output;
4. reviewed source ground truth and its evidence class.

Expert parity is scored only for elements marked Verified or Partially verified
within the verified portion. Potentially inferred, incorrect, and
not-independently-verifiable expert elements are excluded from parity targets
and retained as audit evidence.

No milestone may report only one aggregate score. Report at least:

- text completeness and exact critical-span accuracy;
- layout element and relationship precision/recall;
- reading-order pair accuracy;
- table detection, false-table rate, cell accuracy, spans, and serialization;
- chart labels, structure, values by evidence method, and unsupported claims;
- diagram nodes, connectors, direction, and unsupported claims;
- Markdown semantic completeness/order/duplication;
- JSON type, bbox, provenance, confidence, concern, and compatibility coverage;
- hallucination or unsupported-content count;
- candidate/LlamaParse per-case p50/p95 latency under the canonical
  [latency reference](latency-reference-v1.md), peak RSS, output size,
  optional-model cost, and reviewed regressions.

Each run uses an immutable run directory and records source/output hashes,
configuration, engine/model versions, commands, environment, and case-level
errors.

For unfinished Phases 04–08, LlamaCloud Parse v2 Agentic with cost optimizer
off, cache disabled, and provider Total Latency is the sole latency comparator.
The initial 2026-08-08 rows are planning/reference ceilings only. Each
applicable story/phase gate refreshes at least five interleaved candidate/Llama
samples per case and requires candidate p50 and nearest-rank p95 to be no
greater than the paired Llama values, without quality/reliability loss. Old
local latency thresholds are non-operative; RSS and every other non-latency
gate remain independent.

## M0 - Current baseline

Status: Complete; Phase 0 exit gate passed  
Frozen analysis run: `runs/baseline-20260728-current/`  
Strict completion run:
`../../phase-00-baseline/evidence/p00-us10-corpus-20260729-03/`

Scope: all 15 cases and all 30 pages before parser-quality implementation.

Exit evidence:

- 15/15 cases executed successfully;
- source-tree and fixed configuration recorded;
- JSON, Markdown, diagnostics, performance, and comparison drafts retained;
- source-grounded case review and gap registration completed before M1.

M0 is a measurement baseline, not a release-quality pass. Phase 0 is complete:
P00-US01–P00-US10 are Done after independent review. The strict completion run
records 15/15 cases, 30/30 pages, the 210-claim reviewed-mask ledger, 12
separate dimensions, stable JSON/Markdown identities, performance within the
declared matching-environment tolerance, and zero hosted cost. Corpus custody
is resolved for all 15 triplets and derived annotations with no exceptions.
Later milestone capability and release gates remain separate work.

## M1 - Text-integrity milestone

Primary cases:

- `catastrophe-recap`
- `clean-energy`
- `clinical-study`
- `component-datasheet`
- `egov-survey`
- `esg-metrics`
- `health-report`
- `insurance-acord`
- `manufacturing-report`
- `ny-timetable`
- `postal-10k`
- `settlement-agreement`
- `uber-earnings`

`finance-10k` and `purchase-agreement` are required non-target controls for
source-faithful native text and for preserving redline tokens while text-only
stories run.

Required capabilities:

- damaged Unicode/native-map detection and recovery;
- selective OCR and native/OCR reconciliation;
- wrapped and multiline text reconstruction;
- spatially aware deduplication and short-token preservation;
- punctuation, symbols, formulas, and multilingual/script-safe handling where
  confirmed by the gap register.

Gate: every M1-mapped gap meets its story acceptance target; no critical span,
legal clause, numeric token, or non-target fixture regresses without an approved
decision.

## M2 - Layout milestone

Primary cases:

- `catastrophe-recap`
- `clean-energy`
- `clinical-study`
- `component-datasheet`
- `egov-survey`
- `esg-metrics`
- `finance-10k`
- `health-report`
- `insurance-acord`
- `manufacturing-report`
- `ny-timetable`
- `postal-10k`
- `purchase-agreement`
- `settlement-agreement`
- `uber-earnings`

Required capabilities:

- heading hierarchy and multiline heading reconstruction;
- multi-column, sidebar, caption, source-note, and region ownership;
- header/footer/page-label policy;
- relationship-aware reading order and bbox ownership;
- form label/value and key-value relationships if added to Phase 03.

Gate: approved relationship and pairwise-order targets pass, duplicated
presentation content is zero, and headers/footers remain available without
polluting body order.

## M3 - Table milestone

Primary cases:

- `catastrophe-recap`
- `clinical-study`
- `component-datasheet`
- `esg-metrics`
- `finance-10k`
- `health-report`
- `insurance-acord`
- `ny-timetable`
- `postal-10k`
- `settlement-agreement`
- `uber-earnings`

Required capabilities:

- true/false table detection;
- borderless, ruled, merged-cell, multiline-cell, and dense timetable handling;
- row/column/header and span fidelity;
- native/vector candidate reconciliation;
- cross-page continuation where source evidence supports it;
- consistent HTML, Markdown, CSV, JSON, bbox, and provenance.

Gate: no chart is promoted to a literal table without an explicit reconstruction
method; no false span or false multi-page merge; all critical numeric cells and
legal/form values pass source-grounded assertions.

## M4 - Chart and diagram milestone

Primary cases:

- `catastrophe-recap`
- `clean-energy`
- `clinical-study`
- `component-datasheet`
- `egov-survey`
- `esg-metrics`
- `health-report`
- `manufacturing-report`
- `uber-earnings`

Required capabilities:

- chart/diagram typing and caption/title association;
- axes, ticks, units, legends, series, categories, and printed data labels;
- vector- or pixel-measured values with method and tolerance;
- diagram nodes/connectors/direction where explicitly visible;
- explicit fallback for unsupported or unknowable content;
- zero ungrounded numeric or relationship claims.

Gate: supported structures meet per-type precision/recall and tolerance targets;
unsupported values/relationships emitted as fact remain zero.

## M5 - Cross-format milestone

The current corpus contains PDFs only and has no source-equivalent direct-image,
scanned-PDF, DOCX, PPTX, or XLSX twins. M5 therefore cannot close from these 15
files alone.

Required additions:

- approved page crops submitted as direct images and as image-only PDFs;
- the same pixels embedded as PDF image objects;
- native PDF visual regions;
- where legally and semantically possible, DOCX/PPTX/XLSX semantic twins or
  synthetic equivalents.

Gate: equivalent visible content produces equivalent semantic elements,
relationships, provenance, concerns, and canonical output within declared
geometry tolerance. Native evidence remains preferred when present.

## M6 - Full-corpus release candidate

Scope:

- all 15 benchmark cases;
- every added semantic twin and positive/negative/non-target fixture;
- all dedicated story tests;
- every completed phase regression;
- API/schema, serializer, security, privacy, performance, and rollback gates.

Gate:

- zero unexplained critical or high regression;
- zero fabricated source claims;
- every intended output difference mapped to a Done story and evidence;
- category-specific quality thresholds pass;
- per-case candidate p50/p95 do not exceed paired LlamaParse p50/p95 under the
  canonical latency contract, and peak RSS stays within its independent
  approved resource budget;
- release/rollback evidence is complete;
- explicit approval is recorded before promotion.

## Story completion subset

Between milestones, each story runs only:

1. its dedicated benchmark cases;
2. at least one related positive case;
3. at least one non-target regression case;
4. at least one negative or ambiguous case;
5. affected phase regressions and API/schema contracts.

The next full milestone run occurs only after the defined capability boundary;
it does not replace the approval stop after each story.
