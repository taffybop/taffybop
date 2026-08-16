# LAT-US05 — Reduce redundant output materialization

Status: **Proposed — paused for release-first Phase 04–08 delivery**  
Story points: 3  
Phase: Phase Latency — Latency Improvement  
Priority: Medium  
Dependencies: LAT-US04  
Feature flag: `parser.latency.output_path.enabled` (default off)

## User story

As an API consumer, I want canonical responses materialized with one strict
typed trust boundary, so that duplicate validation and copies do not add
latency or memory pressure.

## In scope

- Inventory and remove only proven-redundant encoding, validation, dumping,
  and body-copy operations after a strict typed result boundary.
- Bounded JSON and Markdown materialization with exact serializer options,
  error semantics, content types, and output identities.

## Out of scope

- Weakening validation or accepting untrusted mappings as typed results.
- Changing public schemas, unset/default behavior, canonical ordering,
  Markdown semantics, or introducing a streaming API contract.

## Delivery validation policy

Completion requires production implementation and basic representative
end-to-end validation of JSON and Markdown response materialization. Public
bytes, status, headers, ordinary errors, output bounds, and default-off
rollback must work within basic targets. Exhaustive malformed/adversarial
matrices, full-corpus byte comparisons, strict performance/RSS qualification,
and independent security/custody review are deferred to later hardening.

## Acceptance criteria

1. Exactly one documented strict validation boundary remains between untrusted
   internal data and each public response.
2. Representative JSON/Markdown bytes, status, headers, ordinary errors, and
   public schemas match the predecessor.
3. Basic malformed and oversized inputs fail without a partial response.
4. A focused check confirms serialization does not mutate the typed result.
5. Disabled behavior uses the exact predecessor output path.
6. A lightweight output-size, memory, and latency smoke check shows the
   representative flow remains within configured targets.

## Dedicated tests

- `tests/stories/phase_latency/test_lat_us05_output_path.py`
- Representative API/schema/golden JSON/Markdown, basic malformed/oversized,
  mutation, output-bound, and rollback tests.

## Rollback

Set `PARSER_LATENCY_OUTPUT_PATH_ENABLED=false`; restore the exact predecessor
validation and materialization sequence.

## Definition of Done

Production code is complete and reviewed; focused tests and representative
end-to-end JSON/Markdown flows pass; the public contract, basic bounds, error
handling, and default-off rollback are confirmed; and no known blocking
functional defect remains. Exhaustive security, performance, corpus-wide,
evidence, and adversarial validation is deferred to later hardening.
