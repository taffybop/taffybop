# Release-first delivery policy — Phases 04–08

Status: Active planning policy as of 2026-08-10  
Scope: Tracker and story acceptance criteria only; this update does not start
or complete production implementation.

## Decision

The remaining latency-focused work is temporarily paused. Phases 04–08 may
resume in dependency order with a release-first completion standard. A story
may be marked Done for the release when its production behavior is complete,
safe to roll back, compatible with existing product behavior, and demonstrated
through lightweight functional validation of a representative end-to-end
flow.

Historical benchmark, evidence, review, and campaign records remain intact.
They are not converted into passes and are not required to complete the
release-scoped versions of these stories.

## Required for release-scoped completion

Each story requires only the validation appropriate to its production change:

1. the production implementation and configuration/feature-flag wiring are
   complete;
2. focused unit or component tests cover the main behavior and one ordinary
   failure or fallback path;
3. at least one representative end-to-end user flow reaches the public output;
4. public API/schema behavior remains compatible or is explicitly additive;
5. flag-off or operational rollback restores the previous behavior; and
6. no known defect blocks the supported flow, cleanup, or safe failure mode.

Safety limits that are intrinsic to the feature remain required. Examples are
upload size limits, archive path validation, formula/macro non-execution,
deny-by-default hosted routing, and bounded request timeouts. These are product
behavior, not optional validation overhead.

## Deferred to post-release hardening

The following do not block release-scoped story completion unless a concrete
defect shows they are necessary for the basic flow:

- detailed latency percentiles or comparisons with LlamaParse;
- peak RSS/GPU, CPU/process-lineage, and exhaustive resource accounting;
- all-corpus, interleaved, campaign-style, soak, stress, or canary runs;
- adversarial/failure-injection matrices beyond one ordinary failure case;
- extensive evidence manifests, immutable custody chains, independent reviews,
  exact-environment proofs, and retained benchmark bundles;
- statistical confidence calibration and exhaustive quality denominators; and
- environment-specific performance/security qualification.

These items move to a dedicated post-release hardening phase. Deferral is not
a claim that they passed.

## Historical 2026-08-10 implementation baseline and planned work

The table below records the pre-implementation baseline captured when this
policy was adopted; it is historical planning context, not the current story
status. Phase 04's current release-first status is maintained in the
[Phase 04 README](phase-04-tables/README.md) and the linked P04 story files.

| Story | 2026-08-10 production state | Planned release-scoped work at policy adoption | Sequencing constraint |
|---|---|---|---|
| P04-US01 | Substantial default-off production implementation exists in settings, pipeline, models, and table semantics. | Resolve any blocking functional defect found by a focused table flow; verify flag-on span fidelity and flag-off rollback. | First Phase 04 delivery; prior P03 dependency exists. |
| P04-US02 | At this baseline, the flag and pipeline hook existed, but reconciliation only copied/validated inputs without choosing or reconciling candidates. | Implement overlap/coverage scoring, deterministic winner/dedup behavior, alternatives, concerns, and provenance preservation. | After P04-US01. |
| P04-US04 | At this baseline, the flag and hook existed, but the gate returned the input table set unchanged. | Implement table/chart/form ownership decisions, structural failure concerns, borderless-table handling, and duplicate suppression. | After P04-US02. |
| P04-US03 | At this baseline, the flag and hook existed, but continuation handling performed validation only and created no merged view. | Implement adjacent continuation scoring, page-preserving derived merge, header handling, serialization, and safe refusal. | After P04-US02 and P04-US04. |
| P05-US01 | Baseline IR recognizes chart/diagram items and safe unstructured concerns; no Phase 05 feature flag or structured contract exists. | Add additive chart/diagram schema, conservative fallback routing, serializer support, and rollback. | Phase 05 foundation after Phase 04 release scope is stable. |
| P05-US02 | Not implemented. | Normalize vector marks, transforms, clipping, panel ownership, IDs, and provenance. | After P05-US01. |
| P05-US03 | Not implemented. | Add linear axes, categories, repeated labels, legend/swatch association, ambiguity handling, and units. | After P05-US02 and existing spatial-token support. |
| P05-US04 | Not implemented. | Measure supported vector bars through grounded axes and emit method/provenance/tolerance without false precision. | After P05-US03. |
| P05-US05 | Not implemented. | Add structural validation, withholding, canonical structured output, one-caption behavior, and fallback. | After P05-US04 and canonical serialization. |
| P05-US06 | Existing OCR is flat; raster chart structure is not implemented. | Associate OCR and geometry with titles, axes, ticks, categories, units, legends, and unresolved concerns. | After P05-US01 and spatial OCR support. |
| P05-US07 | Not implemented. | Detect and measure only supported vertical raster bars with evidence and tolerance, then use P05-US05 validation. | After P05-US06 and P05-US05. |
| P05-US08 | Not implemented. | Trace only supported raster lines/points with evidence and tolerance, then use P05-US05 validation. | After P05-US06 and P05-US05. |
| P05-US09 | Not implemented. | Add a lightweight analysis boundary for input/pixel/time limits, supported-quality checks, safe fallback, and direct-image/PDF normalization. | After P05-US07 and P05-US08. Detailed performance/parity campaigns are deferred. |
| P05-US10 | Baseline emits an unstructured diagram concern; topology is not implemented. | Add supported node/connector extraction, direction evidence, ambiguity handling, serialization, and fallback. | After P05-US01; independent of the raster value branch. |
| P06-US01 | Not implemented; existing optional image captioning is not a grounded provider-neutral contract. | Add bounded request/response and observation/evidence contracts with additive-only semantics. | After P05-US01. |
| P06-US02 | Not implemented. | Add lazy local adapter interface, configured artifact loading, bounded invocation, typed failures, and deterministic test double. | After P06-US01. Model benchmarking/licensing qualification is deferred unless required for the selected release artifact. |
| P06-US03 | Not implemented. | Add mockable hosted transport, deny-by-default policy, minimum crop request, budgets/timeouts, typed failures, and secret-safe logging. | After P06-US01; production vendor enablement still requires an approved policy. |
| P06-US04 | Not implemented. | Add deterministic eligibility and `skip`/`local`/`hosted` selection with one invocation and reason codes. | After both adapters and supported P05 fallback paths. |
| P06-US05 | Not implemented. | Validate returned references, region/bbox grounding, method, and P05 chart/diagram rules; retain accepted/rejected envelopes. | After P06-US04 and P05-US05. |
| P06-US06 | Not implemented. | Transactionally merge accepted observations as additive evidence and return deterministic output for every skip/error/rejection. | After P06-US05. |
| P07-US01 | Not implemented; PDF and direct-image paths exist without a common registration contract. | Add versioned adapter protocol, capability manifest, registry/dispatch, coordinate normalization, and a lightweight reusable conformance test. | Phase 07 foundation. |
| P07-US02 | Not implemented. | Route representative PDF-render/direct-image twins through shared services and normalize semantic/coordinate output. | After P07-US01 and required P05 visual services. Extensive parity matrices are deferred. |
| P07-US03 | Not implemented; uploads currently support PDF and raster images only. | Add bounded OOXML ZIP/XML intake, safe part access, relationship policy, signatures/MIME dispatch, and unsupported/invalid errors. | After P07-US01; required before Office adapters. |
| P07-US04 | Not implemented. | Add DOCX native text/style/list/section/table/media extraction, logical order, provenance, unsupported placeholders, and API dispatch. | After P07-US03 and table reconciliation. |
| P07-US05 | Not implemented. | Add PPTX slide/text/shape/media/table/group-transform extraction, order, provenance, placeholders, and API dispatch. | After P07-US03. |
| P07-US06 | Not implemented. | Add XLSX workbook/sheet/cell/formula-cache/table extraction, visibility policy, sparse bounds, placeholders, and API dispatch. | After P07-US03 and table reconciliation. |
| P07-US07 | Not implemented. | Resolve supported PPTX/XLSX chart relationships and native data into the P05 chart contract with conflicts preserved. | After P07-US05, P07-US06, and P05-US05. |
| P07-US08 | Not implemented. | Add bounded renderer abstraction for unresolved Office regions, native-first reconciliation, transforms, deduplication, and fallback. | After P07-US02 and all three native Office paths. |
| P07-US09 | Not implemented. | Make adapter registration fail closed on a compact capability/compatibility checklist and add one conforming/nonconforming test adapter. | After P07-US08. Exhaustive mutant/resource gates are deferred. |
| P08-US01 | Flags exist individually in `Settings`, but there is no centralized owner/dependency/rollback registry. | Add the registry, dependency validation, safe defaults, and operational disable path. | Can be built as Phase 08 foundation once shipping flags are known. |
| P08-US02 | No shared telemetry/exporter abstraction exists. | Add privacy-safe bounded event primitives, no-op default, exporter isolation, and basic redaction/cardinality rules. | After P08-US01. |
| P08-US03 | Some stages expose ad hoc timings, but no common instrumentation path exists. | Add stage duration/error instrumentation through P08-US02. | After P08-US02. Detailed CPU/RSS/process-lineage accounting is deferred. |
| P08-US04 | No shared quality/fallback/escalation/cost telemetry exists. | Add bounded counters/events and attribution for the shipped deterministic/model paths. | After P08-US02 and P06-US06. Exhaustive reconciliation is deferred. |
| P08-US05 | No statistical calibration implementation exists. | For release, expose conservative typed confidence dimensions and fallback thresholds for text/layout/tables. | After P08-US03/US04. Held-out ECE/Brier calibration is deferred. |
| P08-US06 | No visual/model calibration implementation exists. | For release, expose conservative typed confidence/unsupported decisions for chart/diagram/model output. | After P08-US03/US04 and visual paths. Statistical calibration is deferred. |
| P08-US07 | Not implemented. | Add grounded review-packet schema, bounded routing, recorded outcomes, and deterministic fallback when unavailable. | After P08-US05/US06. Operational scale/SLA analytics are deferred. |
| P08-US08 | No release artifact/license manifest exists. | Generate a versioned manifest for shipped runtime/model/renderer dependencies and expose a basic build/startup verification. | After shipping dependencies are selected; may proceed in parallel with telemetry. |
| P08-US09 | No hosted production policy gate exists. | Enforce deny-by-default vendor/model/region/retention/residency/egress policy before any hosted dispatch. | After P08-US08 and P06 hosted path. Core denial/allow behavior is required; exhaustive security proof is deferred. |
| P08-US10 | No release canary comparator exists. | Add a lightweight known-good versus candidate smoke comparison for required user flows and a blocking functional result. | After P08-US04, US07, US08, and US09. Campaign and percentile gates are deferred. |
| P08-US11 | No versioned release/rollback runbooks exist. | Document owners, ordered enable/disable/deploy/verify steps, and recovery checks in a machine-readable or testable form. | After the release controls in P08-US10 are known. |
| P08-US12 | No rollback drill exists. | Run one lightweight non-production rollback smoke proving flags/artifacts and core flows return to known-good behavior. | After P08-US11. Exhaustive failure injection and recovery-time qualification are deferred. |

## Required validation by story

The story-local release-first section is authoritative for the release. In
general, schema/foundation stories require focused model/serialization tests;
extraction stories require one representative positive, one unsupported or
failure case, public output validation, and flag-off rollback; adapter stories
require one minimal valid file plus one malformed/unsupported input; and Phase
08 operational stories require a smoke path plus disabled/failure behavior.

No story may use this policy to omit an intrinsic data-safety control, silently
change existing output with its flag off, or claim completion before the
production path is usable end to end.
