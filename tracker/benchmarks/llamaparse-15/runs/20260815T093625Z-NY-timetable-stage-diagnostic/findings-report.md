# NY timetable latency finding

## Outcome

The current-tree slowdown is reproduced and localized. It is not caused by the P04 table budget, Docling alone, response serialization, or Tesseract timeouts. The dominant cost is item-wise visual source-text recovery.

In both attempts, `apply_visual_semantics` processed 1,778 page items even though the final response contains zero image, chart, or diagram items. Before `_declared_visual_kind` rules out each non-visual item, the loop calls `recover_pdf_visual_source_text`. That function reopens the same PDF with `pdfplumber` and executes `page.extract_words` on every call.

| Evidence | Cold | Warm |
|---|---:|---:|
| End-to-end request | 336.839 s | 322.286 s |
| `processing.duration_ms` | 55.066 s | 47.091 s |
| Visual semantics | 273.623 s | 267.314 s |
| PDF visual-source recovery | 273.458 s | 267.156 s |
| Recovery calls | 1,778 | 1,778 |
| Recovery share of request | 81.18% | 82.89% |
| Recovery share of visual stage | 99.94% | 99.94% |
| Docling conversion | 35.418 s | 27.487 s |
| Rendered OCR | 14.533 s | 14.753 s |
| Tesseract passes/timeouts | 6 / 0 | 6 / 0 |
| API JSON boundary | 0.447 s | 0.329 s |

The 1,778 recovery calls exactly equal the response item count: 1,745 text items, 27 headings, three tables, and three footers. `_declared_visual_kind` also ran 1,778 times but consumed only 11.38 ms cold and 10.46 ms warm. The expensive work therefore occurs before the inexpensive eligibility decision.

The relevant call order is visible at [visual_semantics.py](../../../../../app/services/visual_semantics.py): the page-item loop begins around line 967, PDF recovery is called around lines 992–1003, and `_declared_visual_kind` follows around line 1015. [visual_source_text.py](../../../../../app/services/visual_source_text.py) opens the PDF around line 1904 and extracts all page words around line 1913 for each invocation.

## What the evidence rules out

- OCR scheduled three rendered page requests and six PSM 3/11 Tesseract passes per attempt. Every pass succeeded in 13.70–13.93 seconds total; none approached the 30-second timeout.
- Docling improved from 35.42 seconds cold to 27.49 seconds warm, but the warm request still took 322.29 seconds because the 267.16-second recovery loop remained.
- JSON encoding, public result validation, model dump, and response construction together remained under 0.45 seconds.
- The production P04 limits stayed at 5.000 seconds/document and 0.500 seconds/page. Terminal table authority did not execute, and the observed custody-validator implementation time was below 1 ms. The emitted tables nevertheless passed all retained 52-row × 13-column row identities.

## Validity and scope

Both no-retry attempts succeeded, closed exactly against the observer clock, and produced equal stable semantic, table-row, and canonical hashes. The `app/` aggregate, model stat inventory, profile script, dependency locks, and frontend variables were unchanged.

The original report is only a frontend line—`POST /api/parse?output_format=json 200 in 315.9s`—without a response, stage trace, timestamp, or code/configuration fingerprint. This controlled 322–337 second reproduction is strongly consistent with the same behavior, but it cannot prove the earlier event's cause retroactively.

The host was not exclusive. That limits clean baseline comparisons, but it does not explain two exact 1,778-call loops or their direct 267–273 second inclusive measurements. No production fix was made in this run.

Detailed evidence is retained in each attempt's `stage-summary.json`, `supplemental-stage-trace.json`, `observer-manifest.json`, `attempt.json`, and raw `response.json`.
