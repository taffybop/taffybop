# P03-US03 Completion Report

Status: Done  
Story: Associate source notes and footnotes  
Points: 5  
Started: 2026-07-31
Completed: 2026-07-31

## Definition of Ready

| Requirement | Result |
|---|---|
| Scope and non-scope explicit | Pass — source notes/footnotes and grounded external links only; no semantic citation inference, global crop expansion, or text repair |
| Points at most 5 | Pass — 5 |
| Dependencies Done | Pass — P03-US01 and P03-US02 |
| Acceptance measurable | Pass — exact 8-note denominator, own-bbox/owner/order/link invariants, zero false associations, exact rollback |
| Dedicated tests identified | Pass — unit, story, contract, PDF/image-layout, negative, real corpus, performance, custody, frontend, and regression paths |
| Fixtures available and authorized | Pass — immutable catastrophe, clinical, health, and finance PDFs plus in-memory direct-image layouts |
| API/frontend impact documented | Pass — additive distinct note items, typed relationships/backlinks, sanitized link descriptors, and visible note rendering |
| Feature flag identified | Pass — `PARSER_LAYOUT_SOURCE_NOTES_ENABLED`, default off |
| Rollback defined | Pass — disable one flag for exact predecessor relationships while independently emitted text remains |
| Quality/performance specified | Pass — 8/8 reviewed recall, zero false association, grounded links, 5% p95 ceiling, latency/RSS/output metrics |

Definition-of-Ready result: **10/10 Pass**. P03-US03 is the sole story in
progress. P03-US04 remains Proposed. The accepted policy is retained in
[P03-source-note-association-policy.md](../decisions/P03-source-note-association-policy.md).

## Implementation

The default-off source-note stage now combines only bounded, source-grounded
evidence:

- declared graph note references with trusted native/OCR provenance;
- same-page external geometry below a unique table, image, chart, or diagram;
- source-visible PDF URI annotations with strict HTTP(S) target validation; and
- selective OCR of at most 16 narrow missing-note bands per page.

Accepted notes remain distinct page items with their own bbox, stable public
ID, `source_note_of` or `footnote_of` relationship, exact owner backlink, and
owner/note canonical relationship descriptors. The projector orders each note
after its owner without changing the owner bbox or flattening note text into
the owner.

The Aon note is recovered from one owner-aligned 36-point band using a
single-line standard OCR profile. The shared OCR default remains unchanged for
all predecessor callers. Clinical table notes use declared raw graph evidence;
the exact `.t001`, `.g001`, and `.t002` controls and both health StatLinks use
bounded, visible PDF annotation evidence. The Figure 1 `.g001` record is an
independently reviewed visual-link control and is not added to the fixed
eight-note numerator.

Ambiguous, orphaned, distant, overlapping, untrusted, generated, malformed,
over-limit, or unsafe-link candidates fail closed. Projection exceptions
restore the canonicalized predecessor IR and add only a sanitized bounded
concern. Evidence planning records content-free diagnostics in a bounded
ledger and never copies document text into diagnostic payloads.

The frontend resolves note relationships only when page-wide IDs, exact type
and endpoints, the owner marker, and one backlink all agree. It renders escaped
note text as a separate non-interactive milestone, while normalized JSON,
canonical/page Markdown, copy, and download retain backend-authoritative bytes.

## Verification

### Acceptance result

1. Aon source note appears once and links to the chart: **Pass**.
2. Note bbox remains outside the chart bbox: **Pass** — note
   `[101.221, 592.567, 73.8, 5.0]`, owner
   `[100.221, 437.31, 444.032, 149.057]`.
3. Unrelated footer/prose is not linked: **Pass** — zero false associations
   across positive, related-control, and finance negative fixtures.
4. Multiple plausible owners produce ambiguity: **Pass** — no relationship is
   emitted and the bounded concern is retained.
5. Note survives an owner crop that excludes it: **Pass** — bounded external
   source evidence recovers the exact Aon text.

The generalized result is **8/8 reviewed notes** (Aon 1, Clinical Table 1
three, Clinical Table 2 four), **14/14 exact emitted note/control records**,
five grounded links, zero missing controls, zero unexpected records, and zero
relationship, backlink, bbox, or order violations. Finance preserves exact
semantic JSON and Markdown flag parity.

### Test and compatibility gates

- Final US03 focused/adversarial/contract/performance/real gate:
  **71 passed**.
- Final retained custody gate: **4 passed**; independent performance plus
  retained recheck: **10 passed**.
- Final predecessor caption/visual/selective-OCR gate: **169 passed**.
- Final US01/US02 real benchmark regression: **12 passed**.
- Frontend Node 22.18: lint, typecheck, production build, **65/65 unit tests**,
  and **1/1 bundle test**.
- Targeted Ruff, Python compilation, and dependency integrity: **Pass**.

Only the existing Starlette/httpx and upstream Docling deprecation warnings
were observed. No endpoint, schema version, package, model, runtime download,
hosted request, token, or cost was added.

### Performance, memory, and size

Five alternating fresh-process pairs produced clipped inclusive p95 overhead
of **0.205315 s** for catastrophe (**2.4155%**, ceiling 0.425 s) and
**0.407439 s** for clinical (**2.9186%**, ceiling 0.698 s). Both accepted
five-percent gates pass.

The isolated stage recorded p50 **12.270 ms**, p95 **13.424 ms**, max
**13.694 ms**, and peak traced allocation **458,305 bytes** for eight notes.
The p95 is below the 50 ms absolute guard.

Maximum enabled peak RSS was **1,438.000 MiB** for catastrophe
(100.7356% of its retained Phase 02 baseline) and **1,718.234 MiB** for
clinical (110.0092%); RSS is recorded rather than used as the story's latency
gate. Representative on/off snapshot deltas were +55.828 MiB catastrophe,
+13.047 MiB clinical, +8.766 MiB health, and +2.891 MiB finance. JSON size
deltas were +1,436, -6,755, +1,206, and 0 bytes respectively.

The retained artifact is
[P03-US03-source-note-metrics.json](../evidence/P03-US03-source-note-metrics.json),
62,312 bytes, with raw SHA-256
`c9f0cbbc0071bdf47ad19b00c6ed2996fb9bb80b1bf785bf9ae3e3c128a8ef7f`
and semantic SHA-256
`6f52064c2b7edce268edf2ba5443274019c25ab89a277283fd0fa7ffd1e2987d`.
It binds 22 code/config/frontend/test/policy paths, all four input PDFs, the
Python package versions, and Tesseract 5.5.3 binary identity. Independent
security and metrics/custody reviews both returned **Pass** with no remaining
finding.

Detailed evidence is in
[P03-US03-verification.md](../evidence/P03-US03-verification.md).

## Frontend milestone

Automated tests cover canonical and legacy note rendering, exact relationship
resolution, non-interactive escaped link text, physical page mapping,
normalized JSON, canonical/page Markdown, copy/download, default-off behavior,
the production build, and the emitted bundle. No controllable browser was
available, so manual click-through is not claimed and remains a Phase 03 exit
retry.

## Known limitations

- This story associates source-visible notes; it does not infer semantic
  citations or repair arbitrary note text.
- The clinical `.t001` and `.g001` URL strings each occur twice in the full
  presentation because separate source-visible context is preserved. Each
  owned note record and relationship is uniquely classified.
- The selective Aon recovery is local Tesseract evidence and remains
  default-off with the story flag.
- General relationship-aware order, redlines, forms, outlines, and running
  regions remain owned by P03-US04–P03-US08.

## Definition of Done

| Requirement | Result |
|---|---|
| Implementation and acceptance complete | Pass — 5/5 criteria |
| Dedicated and adversarial tests pass | Pass |
| Impacted regressions and real benchmarks pass | Pass |
| API/schema and canonical compatibility pass | Pass |
| Frontend visible-path compatibility passes | Pass — automated milestone; browser unavailability recorded |
| Security/resource bounds pass | Pass — owner/candidate/reference/text/URI/annotation/band/diagnostic caps |
| Final-code metrics and exact input custody retained | Pass |
| Configuration, policy, tracker, and rollback current | Pass |
| Independent review complete | Pass — security and metrics/custody approved |
| No concurrent next story | Pass — P03-US04 did not start before this checkpoint |

Definition-of-Done result: **10/10 Pass**. P03-US03 is Done. P03-US04 is the
next dependency-ready Phase 03 story but remains Proposed until its separate
readiness gate passes. No Phase 04 work has started.
