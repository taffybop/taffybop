# LAT-US03 — Reuse immutable document evidence within a request

Status: **Proposed — paused for release-first Phase 04–08 delivery**  
Story points: 5  
Phase: Phase Latency — Latency Improvement  
Priority: Critical  
Dependencies: LAT-US02  
Feature flag: `parser.latency.shared_evidence_context.enabled` (default off)

## User story

As a parser consumer, I want each source page, render, and extraction result
computed once per request, so that duplicate work is removed without discarding
independent evidence.

## In scope

- A request-scoped immutable context for source bytes, page handles, native
  text/objects, coordinate transforms, renders, and identical OCR evidence.
- Exact cache keys that include source, page/region, transform, resolution,
  engine/options, language assets, and version identities.
- Bounded lifetime, memory accounting, deterministic release, and explicit
  ownership across existing stages.

## Out of scope

- Cross-request or tenant-shared result caching.
- Treating different engines/options/crops as interchangeable.
- Changing evidence precedence, accepted output, or public schemas.

## Delivery validation policy

Completion is based on production implementation plus basic representative
end-to-end validation. The enabled flow must work, preserve the public output
contract on representative inputs, stay within the story's configured bounds,
and cleanly return to the default-off predecessor path. Hosted campaigns,
all-corpus performance qualification, exhaustive RSS/process-lineage evidence,
independent security/custody review, and broad adversarial matrices are
deferred to a later hardening phase and do not block this story.

## Acceptance criteria

1. Identical in-request work is executed once and all consumers receive an
   immutable result with the same source/evidence identity.
2. Different engine, option, crop, transform, page, resolution, artifact, or
   source identities never collide.
3. Representative Docling, PDFium, pdfplumber, and Tesseract paths remain
   separately addressable and retain their existing output semantics.
4. A basic failure/cancellation check confirms failed work is not cached as a
   successful result and request-scoped resources are released.
5. Representative enabled JSON and Markdown outputs match the predecessor.
6. Disabled behavior is exact predecessor parity with no context allocation.
7. A lightweight latency and memory smoke check shows no obvious regression or
   unbounded growth on the representative flow.

## Dedicated tests

- `tests/stories/phase_latency/test_lat_us03_shared_evidence_context.py`
- Representative reuse/key-separation, output-parity, failure cleanup, and
  default-off rollback tests.

## API/schema and compatibility

Internal execution context only. No public API/schema/serializer/frontend
change and no cross-request custody.

## Rollback

Set `PARSER_LATENCY_SHARED_EVIDENCE_CONTEXT_ENABLED=false`; create no shared
context and execute the exact predecessor paths.

## Definition of Done

Production code is complete and reviewed; focused tests and one representative
end-to-end enabled flow pass; public output compatibility, basic cleanup,
configured bounds, and default-off rollback are confirmed; and no known
blocking functional defect remains. Deeper security, performance,
process-lineage, evidence-custody, corpus-wide, and adversarial validation is
deferred to later hardening.
