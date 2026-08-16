# Phase 07 Regression Plan

## Release-first validation

For the current release, each adapter requires a minimal valid file, one
ordinary malformed/unsupported file, public output/serialization, and flag-off
unsupported-format rollback. OOXML traversal/absolute-path rejection,
non-execution, no implicit external fetch, and configured size/time limits are
required. Large hostile corpora, semantic-twin campaigns, detailed RSS/latency,
and exhaustive conformance mutants below are deferred.

Run Phase 00–07 regressions for each enabled adapter and the full API/schema
contract.

Required modes:

1. all Phase 07 flags disabled;
2. registered PDF and direct-image adapters through the conformance harness;
3. direct-image/PDF-render semantic twins;
4. valid and hostile OOXML package intake;
5. DOCX, PPTX, and XLSX native-only paths;
6. valid, missing, stale, and conflicting native Office chart evidence;
7. bounded Office visual fallback and renderer failure;
8. conforming and deliberately nonconforming future-adapter test doubles.
9. missing-M5-fixture readiness failure.

Required assertions:

- capabilities, coordinate systems, transforms, versions, and limits are declared;
- element/evidence/relationship IDs and source locators are stable;
- native evidence precedes render/OCR/model fallback;
- duplicate content does not appear when native and rendered paths coexist;
- visibility, notes, hidden content, and unsupported features follow policy;
- formulas, macros, fields, external links, and package content are never executed;
- malicious/oversized archives, XML, parts, and relationships fail closed;
- canonical JSON, Markdown, and text serialize each semantic element once;
- flag-off and unchanged PDF/image fixtures remain compatible.
- physical index and printed page/slide/sheet labels remain separate;
- native embedded, rendered, OCR, and generated assets retain distinct origin;
- each advertised capability has applicable positive, non-target, and negative
  semantic twins before it can pass readiness.

Required M5 fixture controls:

- positive: direct-image/PDF-render photo and scanned text/table twins, DOCX
  legal-formatting twin, PPTX chart/diagram twin, and XLSX dense/financial-table
  twin;
- non-target: declared format-only capabilities and geometry differences remain
  explicit without failing semantic parity;
- negative: invalid transform, wrong page label, native/render duplicate,
  generated-as-source origin, hidden-content leak, and missing twin class.

Cross-format semantic twins should produce equivalent element graphs within
format-specific geometry tolerances. No CI test may require Microsoft Office,
live network access, external relationship fetches, or billable inference.
Required paired Llama service samples are captured by a separately authorized,
retained benchmark run outside CI and then consumed as gate evidence.
Parity and fallback p50/p95 are recorded per twin for diagnosis, while RSS is
checked against its independent resource budget; performance normalization
must not remove semantic differences.

The sole operative latency gate is
[`latency-reference-v1.md`](../benchmarks/llamaparse-15/latency-reference-v1.md).
Before Definition of Done or phase exit, each semantically comparable case
requires at least five interleaved candidate/Llama samples; candidate p50 and
nearest-rank p95 must each be no greater than the paired Llama values for that
same case. Do not drop failures or mask a slow case with a corpus average, and
do not reduce required quality/reliability. DOCX/PPTX/XLSX twins without a
comparable Llama path remain `Unmeasured/Blocked`; local timing cannot
substitute. Security, processing-time/timeout, RSS/resource, compatibility,
output, default-off, and rollback assertions remain independently blocking.
