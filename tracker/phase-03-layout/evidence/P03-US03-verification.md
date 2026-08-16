# P03-US03 Verification Evidence

Date: 2026-07-31  
Status: Pass

## Scope and compatibility

- `PARSER_LAYOUT_SOURCE_NOTES_ENABLED` is default off and requires shared IR
  normalization.
- Enabled output adds only source-grounded `source_note`/`footnote` items,
  exact typed relationships/backlinks, bboxes, provenance, and sanitized
  evidence concerns. Schema version `1.0` and all endpoints are unchanged.
- Disabled projection restores canonicalized predecessor relationships and
  leaves independently extracted text unchanged.
- The frontend consumes the additive relationship contract without
  reinterpreting ownership or making source-visible URL text interactive.
- No package, model, network service, runtime download, hosted request, token,
  or cost was added.

## Exact benchmark result

| Case | Reviewed/control inventory | Result |
|---|---|---|
| Catastrophe physical p1 / printed p7 | One Aon source note below Exhibit 8 | Exact OCR text, bbox, chart owner, backlink, order, and canonical occurrence |
| Clinical physical p2 | Three Table 1 notes plus `.t001` | Three reviewed notes and one grounded control, exact unique ownership |
| Clinical physical p3 | Figure 1 `.g001` | Exact visible/annotated link control linked to the unique diagram owner; outside reviewed-note denominator |
| Clinical physical p4 | Four Table 2 notes plus `.t002` | Four reviewed notes and one grounded control, exact unique ownership |
| Health physical p1 | One note and two StatLinks | Three exact related controls; each StatLink target occurs once |
| Finance control | No eligible external note | Zero emitted notes and exact semantic JSON/Markdown flag parity |

Aggregate: **8 expected / 8 matched** reviewed notes, **14/14 exact emitted
records**, five expected links, zero missing controls, unexpected records,
false associations, bbox violations, ordering violations, unresolved
endpoints, duplicate IDs, backlink failures, or dangling canonical
descriptors.

Every note has a positive point bbox below and external to its owner, positive
horizontal alignment, a gap no greater than 72 points, the exact relationship
type, one owner backlink, and exactly the note and owner canonical blocks
carrying its relationship.

The Aon note bbox is
`{x:101.221,y:592.567,width:73.8,height:5.0,unit:"pt"}` and its chart owner is
`{x:100.221,y:437.31,width:444.032,height:149.057,unit:"pt"}`. Its source text
is absent from the raw Docling graph and was recovered only from the bounded
external band.

## Security and resource behavior

- Candidate ownership requires a unique same-page compatible owner through
  declared graph evidence or bounded external geometry. Alternative presented
  owners force ambiguity and no projection.
- Raw evidence and recursively nested provenance are scanned with depth,
  collection, method-count, and byte bounds. Generated/model-derived,
  inherited-only, malformed Unicode, unknown, and over-limit evidence fails
  closed.
- Note text, reference counts, owners, candidates, equivalent-text candidates,
  annotations, OCR bands, URIs, and emitted diagnostics all have explicit
  limits.
- URI targets must be literal source-visible HTTP(S), bounded to 2 KiB, and
  reject credentials, controls, malformed hosts, backslashes, and unsupported
  schemes. No target is fetched.
- PDF annotations are filtered by external owner geometry before cropped text
  extraction. At most 256 annotations/page and 1,024/document are inspected.
- Missing-note OCR is limited to 16 owner-aligned bands/page and a maximum
  36-point band height. The private source-note profile uses one standard PSM 7
  pass; all predecessor OCR callers retain their original standard+sparse
  behavior.
- Projection canonicalizes rejected raw note edges before its rollback
  snapshot. Exceptions restore that exact predecessor IR and append only a
  bounded content-free concern.
- The frontend requires page-wide unique IDs, exact relationship type and
  endpoints, one owner backlink, and the correct note marker. Malformed
  additive relationships fail closed.

Independent adversarial security review reproduced rollback, ambiguity,
recursive provenance, malformed-Unicode, bounded-link, diagnostic, and
frontend-resolver checks and returned **Pass** with no remaining correctness,
security, or compatibility finding.

## Performance, memory, and size

| Measure | Catastrophe | Clinical |
|---|---:|---:|
| Fresh paired samples | 5 | 5 |
| Clipped inclusive p95 overhead | 0.205315 s | 0.407439 s |
| Percent of Phase 02 wall baseline | 2.4155% | 2.9186% |
| Five-percent ceiling | 0.425 s | 0.698 s |
| Maximum enabled peak RSS | 1,438.000 MiB | 1,718.234 MiB |
| Percent of Phase 02 RSS baseline | 100.7356% | 110.0092% |
| Representative JSON size delta | +1,436 bytes | -6,755 bytes |

Both p95 latency gates pass. The five pairs use alternating off/on then on/off
fresh subprocesses; operating-system caches were not explicitly flushed and
no cold-cache claim is made.

Health and finance representative JSON deltas are +1,206 and 0 bytes. Their
enabled peak RSS values are 1,455.125 and 1,975.656 MiB respectively. Finance
semantic JSON and Markdown are byte-equivalent across the flag.

| Isolated layout stage | Result |
|---|---:|
| Warmups / samples / reviewed notes | 5 / 100 / 8 |
| p50 / p95 / max | 12.270 / 13.424 / 13.694 ms |
| Peak traced allocation | 458,305 bytes |
| Projected IR size | 33,904 bytes |
| Absolute guard | 50 ms |

## Test gates

- Final US03 story/evidence/contract/performance/real suite:
  **71 passed**.
- Retained artifact test: **4 passed**.
- Independent performance plus retained recheck: **10 passed**.
- Final US01/US02 plus Phase 02 selective-OCR predecessor gate:
  **169 passed**.
- Final US01/US02 real benchmark regression: **12 passed**.
- Frontend Node 22.18: ESLint, TypeScript, production build, **65 unit tests**,
  and **1 bundle test** passed.
- Targeted Ruff, Python compilation, and dependency integrity: **Pass**.

The existing Starlette/httpx warning and upstream Docling deprecations remain.
No new warning class was introduced. No controllable browser was exposed, so
manual UI click-through is not claimed; automated visible-path, copy/download,
build, and bundle validation passes.

## Retained artifact

Machine-readable final-code, exact input, classification, relationship,
canonical, rollback, paired performance, RSS, output-size, dependency, policy,
environment, and zero-cost evidence is retained in
[P03-US03-source-note-metrics.json](P03-US03-source-note-metrics.json).

- Size: **62,312 bytes**
- SHA-256:
  `c9f0cbbc0071bdf47ad19b00c6ed2996fb9bb80b1bf785bf9ae3e3c128a8ef7f`
- Semantic SHA-256:
  `6f52064c2b7edce268edf2ba5443274019c25ab89a277283fd0fa7ffd1e2987d`

The non-circular retained test pins the raw artifact, recomputes its semantic
digest, verifies all four corpus identities, and binds 22 exact
code/config/frontend/test/policy records. It also retains Docling 2.114.0,
Docling Core 2.88.0, Pydantic 2.13.4, pdfplumber 0.11.10, and the exact
Tesseract 5.5.3 binary. Independent recomputation found no drift.

## Rollback and remaining scope

Set `PARSER_LAYOUT_SOURCE_NOTES_ENABLED=false`. This removes source-note
projection and restores predecessor public relationships while preserving raw
and independently emitted text evidence.

General relationship-aware order, redline/styled runs, forms/key-values,
outlines, and running-region/page identity remain owned by P03-US04–P03-US08.
Semantic citation inference, arbitrary note repair, chart values, and generated
visual descriptions remain out of scope.
