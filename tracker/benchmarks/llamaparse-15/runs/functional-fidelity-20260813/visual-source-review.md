# Source-grounded OCR and visual fidelity review

Scope: image, OCR, chart, and diagram signals in the 15-PDF functional-fidelity
run. This review does not evaluate latency, CPU, memory, or model creativity.

## Method

LlamaParse remains the requested comparison baseline, but the PDF is the truth
authority for claims about printed OCR, values, geometry, and relationships.
Each adjudication used the hash-bound source PDF and retained page render, then
cross-checked LlamaParse raw Markdown/full JSON/rendered DOM against service raw
Markdown/full JSON/rendered DOM.

The following are not treated as source OCR or established facts unless visibly
supported by the page:

- model-generated prose image descriptions;
- chart values interpolated from bar heights or plotted paths;
- semantic identities not printed in the image;
- directed graph edges when the source has no visible arrowhead;
- raw image-fragment counts when one system groups a region and the other
  exposes several fragments.

The analyzer's aggregate `visual-origin text proxy` is therefore diagnostic. It
currently compares Llama semantic descriptions and reconstructed chart tables
against service raw OCR, sometimes across different page scopes. Region review
is required before any such signal is release-blocking. Exact source/hash/status
records are in [visual-source-adjudication.json](visual-source-adjudication.json).

## Resolved production defects

| Case(s) | User-visible defect | Correction | Public validation |
|---|---|---|---|
| `uber-earnings` p1 | Classifier-unavailable natural-photo OCR leaked gibberish into Markdown/UI. | Require reliable aggregate OCR at the classification confidence floor; preserve rejected OCR as diagnostics. | Fresh service JSON/Markdown HTTP 200, 3/3 DOM; fresh Llama job `pjb-skyvq5noznjko41p3fs2vxgfgptg`. |
| catastrophe, clean-energy, clinical, eGov, health, manufacturing | Source-captioned charts/flowchart stayed generic images when the optional classifier was unavailable. | Route only unique graph-declared caption/geometry matches with reliable OCR; retain source IDs and emit no unproved series, values, nodes, or connectors. | Six JSON and six Markdown responses HTTP 200; 11/11 service DOM; fresh Llama 6/6 JSON+Markdown and 11/11 DOM+PNG. |

The routing negatives explicitly cover photographs, board/generic-image
captions, sparse OCR, low-confidence OCR, table-like regions, missing captions,
and invalid caption geometry. Exact before/after/job/test hashes are in
[visual-resolution-ledger.json](visual-resolution-ledger.json).

## Source-grounded case results

| Case | Adjudication | Remaining functional gap |
|---|---|---|
| catastrophe | Llama's exhaustive annual-loss matrix is not fully printed; service correctly withholds inferred values. Chart detection and explicit label evidence are fixed. | Normalize explicit legend/axis/year structure. |
| clean-energy | Several Llama values are bar-height reconstructions and some disagree with source geometry. Chart detection/placement are fixed. | Panel/axis semantics and noisy rotated OCR. |
| clinical | Llama image count and service diagram count refer to the same page-3 region. Diagram detection, 184 source label occurrences, and once-only approved OCR presentation are fixed without fabricated topology; the external caption remains separate. | Explicit connector topology remains safely unresolved. |
| component datasheet | Llama board/pinout prose contains unprinted semantic interpretation and is an acceptable difference. | Page-2 pin labels and spatial diagram structure remain incomplete; the source has no declared picture caption, so conservative caption routing correctly does not guess. |
| eGov | Bar labels/counts/percentages are printed source truth. Chart detection/geometry are fixed. | Correct remaining OCR characters and organize labels by year/category. |
| ESG | Two small printed charts are real, but the aggregate proxy mixes chart and surrounding content. | No conservative type evidence exists yet; safe chart detection/structure remains open. |
| health | Llama's large matrices include reconstructed values not individually printed. Both source-captioned regions are now charts with no invented points. | Axis/series organization and some label OCR. |
| insurance ACORD | `ACORD logo` is a semantic description; the printed OCR is `ACORD`. Llama's signature interpretation is also inference. | Optional logo semantic description only; not an OCR regression. |
| manufacturing | Five charts are real; many Llama time-series values are interpolation and some conflict with visible marks. Four declared-caption regions are now charts, while the uncaptained first chart retains approved OCR exactly once. | First page-1 chart lacks a declared caption and stays image. Rotated OCR and series organization remain open. |
| Uber | Photo gibberish leak is fixed. Llama's photo sentence is semantic model output, not OCR; page-3 directed Mermaid edges are unsupported because the source lacks arrowheads. | Page-2 chart structure and page-3 undirected grouping remain incomplete. |

## Validation

- Focused routing schema suite: 14 passed.
- Real-corpus routing suite with absolute offline Docling artifacts: 3 passed.
- Combined image quality, P05-US01, P05-US10, Uber real-photo, and real-routing
  slice: 45 passed in 58.06 seconds.
- Production compileall: passed.
- Uber public rerun: JSON/Markdown HTTP 200 and 3/3 rendered DOM.
- Caption-routing public rerun: JSON/Markdown HTTP 200 for all six cases and
  11/11 rendered DOM.
- Final bounded crop-coordinate validation: P03 suite 64 passed; exact-profile
  clinical/manufacturing/Uber real slice 3 passed in 57.07 seconds; final
  clinical and manufacturing public JSON/Markdown were HTTP 200 on both
  surfaces and 7/7 rendered pages were recaptured.
- Fresh Llama routing references: six completed Agentic jobs, all six raw
  Markdown/full JSON, and 11/11 rendered DOM/PNG.

## Release interpretation

Visual fidelity is materially improved but not fully release-equivalent. The
remaining source-visible gaps are explicit chart organization/OCR in eGov,
clean-energy, health, ESG, and manufacturing; component pinout OCR/topology;
clinical connector topology; and Uber chart/grouping structure. Baseline
descriptions, interpolated values, unsupported arrows, and fragment-count-only
signals are accepted or diagnostic differences rather than service regressions.
