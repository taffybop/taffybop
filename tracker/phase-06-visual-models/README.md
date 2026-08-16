# Phase 06 — Optional Visual Models

Status: Release-first complete (2026-08-12)  
Outcome: Grounded local/hosted visual assistance for only low-confidence regions

## Release-first phase policy

Phase 06 follows the
[Phases 04–08 release-first policy](../release-first-phases-04-08.md).
The current optional captioning path is not the provider-neutral grounded model
contract described by these stories. The release scope requires the contracts,
mockable local/hosted adapters, routing, grounding, additive merge, safe
fallback, and default-off rollback. Live/billable model campaigns, hardware
benchmarks, statistical evaluation, exhaustive security testing, and extensive
evidence manifests are deferred. Hosted dispatch remains deny-by-default and
cannot ship enabled without an explicit basic policy configuration.

## Release entry criteria

- The P05 fallback/validation contracts needed by the selected release flow are
  available.
- Local and hosted adapters have deterministic test doubles; any enabled hosted
  path has an explicit deny-by-default policy owner.

## Release exit criteria

- One constrained model contract works for local and hosted adapters.
- Local and hosted paths are disabled by default.
- Routing and adapter selection obey basic configured area, request, cost, and
  data-policy limits.
- Every accepted observation passes independent grounding and structural
  validation.
- Accepted evidence merges additively, while every skip, rejection, or failure
  returns the deterministic result.
- Generated descriptions and identifications remain distinguishable from source
  captions/text; derived values and relationship direction retain evidence,
  method, tolerance, and validation state.
- One local or hosted test-double flow reaches public output additively, and
  every skip/error/rejection returns the deterministic result.

## Benchmark evidence — LlamaParse-15

- `uber-earnings` page 1 has no source caption, yet generated/false OCR prose can
  look caption-like; page 2 exposes a New Zealand-versus-Australia identity hard
  negative and printed-versus-vector-derived chart values; page 3 has visible
  associations without arrowheads.
- The generalized gate is: model output is supplemental, origin-labeled,
  region/evidence-grounded, independently validated, and rejected to the
  deterministic fallback when exact value or direction is unsupported.
- Acceptance and regression controls cover positive explicit labels/endpoints,
  non-target complete deterministic regions, and negative false captions,
  visual identities, ungrounded values, and directed edges. Routing,
  validation, merge, and fallback timings are retained for attribution only;
  area, cost, timeout, and resource safety limits remain independently
  blocking.
- Governing gaps: `GAP-VISUAL-001`, `GAP-CHART-002`,
  `GAP-DIAGRAM-001`, `GAP-BBOX-001`, `GAP-PROVENANCE-001`,
  `GAP-DIAGNOSTICS-001`, and `GAP-SERIALIZATION-001`.

## Post-release hardening latency contract

The following historical contract is retained for post-release hardening and
does not block release-scoped completion. The pinned reference is LlamaCloud
Parse v2 using Agentic mode at 10 credits/page, cost optimizer off, cache
disabled, and provider-UI Total Latency. Its initial 2026-08-08 one-sample
values are planning/reference ceilings only. Before any story Definition of
Done or phase exit, refresh each applicable case with at least five interleaved
candidate/Llama samples: candidate p50 and nearest-rank p95 must each be less
than or equal to the paired Llama p50/p95 for that case, with no corpus-average
masking and no dropped failures. Required quality and reliability must remain
unchanged. A case without semantically comparable Llama input and output is
`Unmeasured/Blocked`; an older local baseline may not substitute. Local stage,
component, routing, validation, merge, and fallback timings are diagnostics
only and cannot independently pass, fail, or waive the latency gate.

Phase-applicable initial reference rows (2026-08-08; one sample each):

| Canonical case row | LlamaParse job ID | Provider-UI Total Latency | Use |
|---|---|---:|---|
| `ny-timetable` | `pjb-7ljh3v6chmcbpp7qriuwvbbglpat` | 45.6 s | Planning/reference ceiling only |
| `postal-10k` | `pjb-0qtz3dizelo6pu7gv0f4ur8g1bij` | 25.3 s | Planning/reference ceiling only |
| `uber-earnings` | `pjb-g8gebswwjtgtx77b2wmqpc48sjox` | 23.3 s | Planning/reference ceiling only |

Each row is an explicit reference to the same named case row in the canonical
latency document. These values cannot satisfy Definition of Done without the
required paired refresh.

## Stories

1. [P06-US01](stories/P06-US01.md) — Done — Define grounded visual-model contracts
2. [P06-US02](stories/P06-US02.md) — Done — Add an optional local visual-model adapter
3. [P06-US03](stories/P06-US03.md) — Done — Add a policy-controlled hosted adapter
4. [P06-US04](stories/P06-US04.md) — Done — Route eligible regions and select a visual-model adapter
5. [P06-US05](stories/P06-US05.md) — Done — Ground and validate model observations
6. [P06-US06](stories/P06-US06.md) — Done — Merge accepted evidence and guarantee deterministic fallback

## Release-first completion

All six stories are implemented in dependency order and validated with
deterministic adapters. Local and hosted paths remain off by default; hosted
dispatch remains denied unless policy, data, minimization, retention, identity,
region, and positive budget controls are all explicit. Only evidenced Phase 05
fallback regions route, every observation is independently grounded, and model
evidence is additive and origin-labelled. Every non-accepted path restores the
unchanged Phase 05 result. Deferred benchmark, live-model, evidence-manifest,
performance, hardware, and security campaigns were not created or run. Phase
07 has not been started.
