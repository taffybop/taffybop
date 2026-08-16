# Phase 07 — Cross-format Adapters

Status: Release-first complete (2026-08-12); post-release campaigns deferred  
Outcome: PDF, image, DOCX, PPTX, XLSX, and future adapters feed one semantic IR

## Release-first phase policy

Phase 07 follows the
[Phases 04–08 release-first policy](../release-first-phases-04-08.md).
The release-first scope is complete. The common adapter contract, image parity
path, bounded OOXML intake, DOCX/PPTX/XLSX native adapters, Office chart path,
bounded visual fallback, and future-adapter registration gate are implemented
behind default-off rollback flags. Release validation used minimal valid and
ordinary invalid or unsupported fixtures, public-output compatibility checks,
and exact flag-off checks. Cross-format benchmark, performance, security,
evidence, and large semantic-twin campaigns were not run and are not claimed;
they remain post-release work. Core ZIP/XML/path bounds and
macro/formula/external-content non-execution remain required product behavior.

## Release-first completion record

- Completed on 2026-08-12 with all 9 of 9 stories marked Done.
- The full Phase 07 story suite passed: 103 passed, 0 failed, 0 skipped, with
  1 existing `StarletteDeprecationWarning` from FastAPI's `TestClient` import.
- Phase 07 capabilities remain default off, and flag-off validation preserves
  the predecessor PDF/image behavior and unsupported Office fallback.
- No deferred Phase 07 cross-format benchmark, performance, security,
  evidence, or large semantic-twin campaign was executed or used for this
  completion record.

## Release entry criteria

- Shared IR, relationships, reading order, and canonical serialization needed
  by the adapters are available.
- Minimal valid DOCX, PPTX, and XLSX fixtures and ordinary malformed fixtures
  are locally available; the large M5 semantic-twin bundle is not required for
  this release.
- The OOXML boundary uses the Python standard library, and the bounded visual
  fallback uses an application-injected renderer abstraction; Phase 07 does
  not bundle or claim qualification of a renderer dependency.

## Release exit criteria

- One reusable adapter contract and conformance harness governs every enabled
  format.
- A representative direct image/PDF-render flow uses the same visual contract.
- OOXML packages are bounded and safely inspected before format-specific parsing.
- DOCX, PPTX, and XLSX preserve native evidence before rendered fallback.
- Embedded chart data takes priority over visual measurement.
- Native and visual evidence reconcile without duplicate canonical content.
- Every enabled adapter passes the lightweight common conformance and canonical
  serializer checks.
- Page index versus printed label, asset/content origin, and coordinate
  transforms remain explicit across every enabled adapter.
- One representative DOCX, PPTX, and XLSX request completes through the public
  API, and flag-off restores unsupported-format behavior.

## Deferred benchmark evidence — LlamaParse-15

- The current benchmark establishes PDF-side failures on `ny-timetable`
  tables, `postal-10k` financial/glossary tables, `purchase-agreement`
  redlines, and `uber-earnings` photos/flags/charts/diagrams.
- It has no direct-image, scanned-image/PDF, DOCX, PPTX, or XLSX semantic twins,
  so it cannot prove cross-format equivalence or Office native-first fallback.
  This is the M5 readiness blocker `GAP-COVERAGE-001`.
- Required generalized coverage pairs the same semantics across formats:
  raster/photo and scanned controls, DOCX legal formatting, PPTX
  chart/diagram slides, and XLSX dense/financial tables. Each twin preserves
  origin, page/slide/sheet label, transforms, relationships, concerns, and one
  canonical presentation.
- A future full hardening claim must include positive equivalence,
  non-target capability differences, negative transform/origin/duplication
  controls, diagnostic local adapter timing, independent RSS/resource gates,
  and the paired LlamaParse latency gate where semantically comparable. Until
  the M5 bundle exists, Phase 07 cannot claim completion of the deferred
  cross-format campaign; this does not block the completed release-first scope.
- Related gaps: `GAP-COVERAGE-001`, `GAP-VISUAL-001`,
  `GAP-CHART-001`, `GAP-CHART-002`, `GAP-DIAGRAM-001`,
  `GAP-BBOX-001`, `GAP-PROVENANCE-001`,
  `GAP-SERIALIZATION-001`, and `GAP-PAGE-001`.

## Post-release hardening latency contract

The following historical contract is retained for post-release hardening and
does not block release-scoped completion. It pins LlamaCloud Parse v2, Agentic
mode at 10 credits/page, cost optimizer off, cache disabled, and provider-UI
Total Latency. The 2026-08-08 one-sample/case values below are planning/reference
ceilings only:

| Canonical case row | LlamaParse job ID | Provider-UI Total Latency | Use |
|---|---|---:|---|
| `ny-timetable` | `pjb-7ljh3v6chmcbpp7qriuwvbbglpat` | 45.6 s | Planning/reference ceiling only |
| `postal-10k` | `pjb-0qtz3dizelo6pu7gv0f4ur8g1bij` | 25.3 s | Planning/reference ceiling only |
| `purchase-agreement` | `pjb-tejko7iocgaav1wtj7z5tm5lugju` | 48.8 s | Planning/reference ceiling only |
| `settlement-agreement` | `pjb-ha1zlpsbx1ebb4910oipib1dah3d` | 1.4 min (84.0 s display-equivalent) | Planning/reference only |
| `uber-earnings` | `pjb-g8gebswwjtgtx77b2wmqpc48sjox` | 23.3 s | Planning/reference ceiling only |

The 84.0-second settlement value is only the exact unit conversion of the UI's
rounded `1.4m` display and does not claim sub-minute precision.

Each named row refers to the same canonical-document row. Before any future
claim of full hardening or campaign completion, refresh each applicable case
with at least five interleaved candidate/Llama samples. Candidate p50 and
nearest-rank p95 must each be no greater than the paired Llama value for that
same case, with no corpus-average masking, no dropped failures, and unchanged
required quality/reliability. Local adapter/stage timings are diagnostic only.
DOCX, PPTX, XLSX, or another path without semantically comparable Llama input
and output remains `Unmeasured/Blocked`; neither the PDF values above nor an
older local benchmark may substitute. All security, processing-time/timeout,
RSS/resource, compatibility, output, custody/hosted-use, default-off, and
rollback gates remain independently blocking for that post-release claim.

## Stories

1. [P07-US01](stories/P07-US01.md) — Done — Define adapter contract and reusable conformance harness
2. [P07-US02](stories/P07-US02.md) — Done — Prove PDF/direct-image semantic parity
3. [P07-US03](stories/P07-US03.md) — Done — Add bounded and secure OOXML package intake
4. [P07-US04](stories/P07-US04.md) — Done — Add a DOCX native-evidence adapter
5. [P07-US05](stories/P07-US05.md) — Done — Add a PPTX native-evidence adapter
6. [P07-US06](stories/P07-US06.md) — Done — Add an XLSX native-evidence adapter
7. [P07-US07](stories/P07-US07.md) — Done — Extract native Office chart evidence
8. [P07-US08](stories/P07-US08.md) — Done — Reconcile Office native evidence with bounded visual fallback
9. [P07-US09](stories/P07-US09.md) — Done — Add future-adapter conformance gates
