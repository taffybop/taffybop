# Current-Parser Baseline Summary

Run: `baseline-20260728-current`  
Status: Complete - 15/15 cases parsed successfully

## Reproducibility record

- Invocation: direct `app.services.pipeline.parse_document`, one isolated cold
  worker process per case.
- Application version: `0.1.0`.
- Source-tree SHA-256:
  `ff2e4656dcb9f6eefb5c2e3b94919c5eb080aad7a8cf6dc09463e9f86d87d98c`.
- Python: `3.13.5`.
- Platform: `macOS-26.5-arm64-arm-64bit-Mach-O`.
- Logical/physical CPUs: `10 / 10`.
- System memory: `32 GiB`.
- Docling: `2.114.0`; docling-core: `2.87.1`.
- PDFium: `5.12.1`; pdfplumber: `0.11.10`.
- Tesseract: `5.5.3`; languages: `eng`.
- Operating mode: local deterministic core; PDF visual analysis enabled;
  image captioning and optional models disabled.
- Network services: disabled.
- Run window: `2026-07-28T13:47:05Z` to `2026-07-28T13:50:55Z`.

The exact settings and environment are in
[`run-metadata.json`](runs/baseline-20260728-current/run-metadata.json), and the
reproduction command is in
[`command.txt`](runs/baseline-20260728-current/command.txt).

## Aggregate result

| Measure | Baseline |
|---|---:|
| Successful cases | 15 / 15 |
| Successful pages | 30 / 30 |
| Top-level elements | 291 |
| Detected image regions | 63 |
| Document warnings | 0 |
| Sum of isolated parse times | 212.67 s |
| Mean / median parse time | 14.18 s / 9.06 s |
| Nearest-rank p95 / maximum parse time | 46.76 s / 46.76 s |
| Median peak RSS | 1,437 MiB |
| Nearest-rank p95 / maximum peak RSS | 2,590 MiB / 2,590 MiB |
| Generated JSON | 5,289,462 bytes |
| Generated Markdown | 116,260 bytes |

Successful execution is not a quality pass. Manual source review and the
per-case comparisons confirm omissions, false classifications, fragmented text,
weak table structure, unsupported chart/diagram semantics, and serialization
differences despite the absence of document-level warnings.

The zero-warning count is also incomplete diagnostics evidence, not proof of a
clean run. `uber-earnings/stderr.log` records three Tesseract orientation
detection failures and a deprecation warning that are absent from structured
document warnings. This is mapped to `GAP-DIAGNOSTICS-001`; the case still
completed and retained its outputs.

## Per-case execution

| Case | Status | Seconds | Peak RSS (MiB) |
|---|---|---:|---:|
| catastrophe-recap | Success | 8.50 | 1,427.5 |
| clean-energy | Success | 7.89 | 1,427.7 |
| clinical-study | Success | 13.96 | 1,561.9 |
| component-datasheet | Success | 10.56 | 1,840.3 |
| egov-survey | Success | 6.85 | 1,427.0 |
| esg-metrics | Success | 7.78 | 1,423.3 |
| finance-10k | Success | 20.15 | 1,802.7 |
| health-report | Success | 7.92 | 1,437.0 |
| insurance-acord | Success | 9.06 | 1,401.1 |
| manufacturing-report | Success | 11.58 | 1,825.8 |
| ny-timetable | Success | 46.76 | 1,944.0 |
| postal-10k | Success | 19.84 | 1,917.7 |
| purchase-agreement | Success | 6.18 | 1,401.0 |
| settlement-agreement | Success | 6.48 | 1,410.7 |
| uber-earnings | Success | 29.15 | 2,589.5 |

`ny-timetable` is the latency maximum and `uber-earnings` is the memory maximum
in this run. Both must remain explicit performance fixtures at later milestones.

## Element inventory

| Our top-level type | Count |
|---|---:|
| Text | 161 |
| Heading | 38 |
| Footer | 28 |
| Table | 17 |
| Image | 16 |
| Chart | 14 |
| Header | 13 |
| Diagram | 2 |
| List | 2 |

The expert output contains 31 table items versus our 17, but that difference is
not automatically a table-recall defect. Several expert "tables" are
source-grounded reconstructions of charts; their numeric cells must be
classified as explicit, vector-measured, pixel-estimated, model-inferred, or
unverifiable before they can be used as truth.

## Cross-output structural inventory

These counts describe field presence, not correctness. In particular, a
region-level bbox or confidence cannot validate a table cell, chart value, or
diagram edge.

| Field | Expert | Current parser | Source-reviewed interpretation |
|---|---:|---:|---|
| Top-level items | 279 | 291 | Different segmentation and duplicate/omission behavior make count parity non-diagnostic |
| Items with bbox | 277 (99.28%) | 291 (100%) | Both need child/cell/mark/edge geometry and clearer bbox roles |
| Items with confidence | 232 (83.15%) | 67 (23.02%) | Neither confidence family is calibrated to source correctness |
| Items with explicit producing-path provenance | 0 (0%) | 291 (100%) | Current provenance is useful but usually stage-level, not field-level |
| Item concerns | 38 | 24 | Both contain false, missing, or insufficiently localized concerns |

## M0 category measurements

This is a category dashboard, not a single quality score. Percentages that use
the native PDF text layer are diagnostic proxies only; the page reviews and
verified annotations remain authoritative.

| Category | M0 measurement | Interpretation |
|---|---:|---|
| Text | 75.81% macro token F1 against native-text proxy | Useful for drift screening, but invalid as truth where mappings, rotation, or charts damage native extraction |
| Layout | 100% top-level bbox coverage | Presence of a bbox did not prevent wrong ownership, overlap, merged regions, or misordered columns |
| Reading order | Source-reviewed failures present | Confirmed on multi-column, repeated-title, and redline/header cases; a numeric gate awaits reviewed pair annotations |
| Tables | 17 canonical tables | Source review confirms both strong financial tables and material dense-grid, span, cell, and false-table failures |
| Charts | 14 chart items; 0 with structured series/values | Labels are often flattened or duplicated; no unprinted numeric value is fabricated |
| Diagrams | 2 diagram items; 0 with structured nodes/edges | Both carry an explicit unstructured-relationship concern |
| Markdown | 15/15 exact projections of ordered JSON item Markdown | Serializer parity is strong, but semantic/OCR defects in JSON propagate unchanged |
| JSON bboxes / provenance | 100% / 100% top-level coverage | Provenance records the producing path, but not every cell, chart mark, text run, or relationship |
| JSON confidence | 23.02% top-level coverage | Scores are concentrated on visual/OCR items and do not express structure/value correctness |
| Parse concerns | 24 item concerns; 0 document warnings | Several reviewed material failures—and Uber OCR orientation failures recorded only on stderr—have no targeted concern or document warning |
| Hallucination safety | 0 structured chart values emitted | Safer than copying unsupported expert values; canonical OCR noise and false classification still fail the source-grounded gate |
| Performance | p50 9.06 s; nearest-rank p95 46.76 s; peak RSS max 2,590 MiB | `ny-timetable` and `uber-earnings` are mandatory performance fixtures |
| External model cost | 0 | Local deterministic run; optional image descriptions and hosted/local visual models were disabled |

The text proxy macro F1 is 64.42% for the expert output and 75.81% for ours.
That does **not** establish that ours is globally more accurate: Markdown tags,
reconstructed visual values, rotated text, and malformed native mappings distort
the comparison. It is retained solely as a reproducible semantic-drift signal.

## Per-case source-grounded disposition

| Case | Verified current-parser strength | Material current-parser gap |
|---|---|---|
| catastrophe-recap | Exhibit 7 table exact; chart values safely withheld | Damaged named event/amount, missing caption/source, noisy chart labels |
| clean-energy | Main text/growth labels present; values safely withheld | Duplicated/fused chart OCR, wrong logo/license OCR, weak panel structure |
| clinical-study | 6- and 9-column table topology is more faithful than expert | Captions/footnotes lost, one numeric punctuation error, flowchart unstructured/duplicated |
| component-datasheet | Ordinary text/symbols broadly retained; inferred descriptions avoided | Pin diagram unusable, visual OCR noise, list nesting/key-value groups flattened |
| egov-survey | Narrative and most explicit labels retained | 24 printed chart values unstructured; `40`/`44` corrupt |
| esg-metrics | Main explicit table exact; title bbox better than expert | Superscripts corrupt, chart text duplicated/noisy, two-column order wrong |
| finance-10k | Source-faithful tables, spans, wrapped row, and currency presentation | Sparse table confidence/cell provenance; repeated header typing/page labels |
| health-report | Unsupported exact chart tables safely withheld | Rotated labels lost, bubble chart duplicated as false table, link semantics flattened |
| insurance-acord | No fabricated signature; tight main-grid bbox and full footer | Static form/control semantics absent; both tables structurally unusable; late contact OCR |
| manufacturing-report | Five charts correctly typed and unsupported exact rows withheld | Explicit labels/values unassociated, duplicate OCR, caption/header ownership errors |
| ny-timetable | All three table regions found | 13→12 columns and 50→49 rows per page; shifts, false OCR, late title |
| postal-10k | Financial headers/currency are often more faithful than expert | FERS definition lost, false `ClO`, local text/diagnostic gaps |
| purchase-agreement | Visible character tokens broadly complete | Redline meaning lost and top redline material moved after body |
| settlement-agreement | Percentage table and legal text source-faithful | `Look-Back` hyphen lost; clause hierarchy absent |
| uber-earnings | Unsupported expert values/directions not asserted | False photo/hidden construction OCR, charts/diagrams unstructured, duplicates/page metadata |

## Output locations

Each case directory under
`runs/baseline-20260728-current/<case-id>/` contains:

- `our-output.json`
- `our-output.md`
- `diagnostics.json`
- `stdout.log`
- `stderr.log`
- `comparison-metrics.json`
- `comparison-report.md`

The comparison metrics use the native PDF text layer only as a diagnostic
proxy. The rendered page and case report remain authoritative where text maps,
visual values, layout, or relationships are involved.
