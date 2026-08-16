# LAT-US06 — Route optional work only from sufficient source evidence

Status: **Proposed — paused for release-first Phase 04–08 delivery**  
Story points: 5  
Phase: Phase Latency — Latency Improvement  
Priority: High  
Dependencies: LAT-US05  
Feature flag: `parser.latency.adaptive_routing.enabled` (default off)

## User story

As a parser consumer, I want expensive supplemental work skipped only when
source evidence proves it cannot add accepted content, so that latency improves
without weakening recall or reliability.

## In scope

- A conservative, deterministic pre-routing proof based on source properties,
  existing evidence availability, and closed reason codes.
- Full-path fallback on ambiguity, low confidence, malformed evidence,
  unsupported format, classifier error, or resource uncertainty.
- Retention of routing reasons and representative full-path comparisons for
  the routes changed by this story.

## Out of scope

- Language-plausibility routing, learned/model routing, removal of required
  evidence, or treating a faster self-selected subset as representative.
- Skipping work for tables, charts, forms, damaged text, rotated text, images,
  or other structures without independently sufficient source proof.

## Delivery validation policy

Completion requires production implementation and basic representative
end-to-end validation for one skip path and the conservative fallback path.
Representative outputs must remain compatible, fallback must work when routing
is uncertain, and rollback must restore the full predecessor path. Exhaustive
counterfactual corpora, adversarial false-skip matrices, strict performance/RSS
qualification, lineage proof, and independent security/custody review are
deferred to later hardening.

## Acceptance criteria

1. Every skip has a closed, source-evidence reason; missing or contradictory
   evidence invokes the complete predecessor path.
2. Representative skip/full-path comparisons show no public output or
   provenance loss for the routes implemented in this story.
3. A small ambiguity set, including scanned/image and structured content,
   routes to the full path unless its explicit proof is complete.
4. Representative alternative evidence remains present and is not fabricated,
   flattened, or silently merged by routing.
5. A basic classifier error/timeout check falls back to the full path.
6. Disabled behavior executes the complete predecessor path exactly.
7. A lightweight enabled/predecessor timing and memory smoke check confirms the
   representative flow works within basic targets.

## Dedicated tests

- `tests/stories/phase_latency/test_lat_us06_adaptive_routing.py`
- Representative skip/full-path parity, ambiguity fallback, classifier-error,
  output compatibility, and default-off rollback tests.

## API/schema and compatibility

No public contract change. Internal routing evidence is bounded and not a
substitute for source provenance or public concerns.

## Rollback

Set `PARSER_LATENCY_ADAPTIVE_ROUTING_ENABLED=false`; execute every complete
predecessor stage and remove no evidence.

## Definition of Done

Production code is complete and reviewed; focused tests and representative
skip and fallback end-to-end flows pass; output compatibility, basic bounds,
and default-off rollback are confirmed; and no known blocking functional
defect remains. Exhaustive counterfactual, security, performance, lineage,
corpus-wide, evidence, and adversarial validation is deferred to later
hardening.
