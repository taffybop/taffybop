# Phase 01 Regression Plan

Run:

- `tests/stories/phase_01/`
- `tests/regression/phase_01/`
- `tests/regression/phase_00/`
- `tests/contract/`
- existing backend serializer, image, table, and API suites
- frontend serializer and normalizer suites on the supported Node version

Assert stable IDs, element order, bbox units/transforms, provenance links,
confidence dimensions, concern codes, v1 compatibility, and byte-equivalent
canonical Markdown between server and client.

Required LlamaParse-15 fixture classes:

- positive: finance-10k pp1–3 tables and settlement-agreement p1 prose/table
  round-trip without text, order, geometry, or source loss;
- ownership/link targets: catastrophe-recap p1 Exhibit 7 caption/source note,
  clinical-study pp2–4 captions/footnotes, health-report p1 chart captions and
  two StatLink annotations, and manufacturing-report pp1–3 chart sources;
- duplicate/alternate targets: clean-energy p1 chart native/OCR overlap,
  health-report p1 false table over Figure 3.10, esg-metrics p1 chart text
  duplication, and uber-earnings pp1–3 false caption/chart/logo duplication;
- non-target: preserve conservative refusal of unprinted chart values and do not
  turn visible, unannotated esg-metrics navigation into a sourced URL;
- negative: dangling/cyclic relationships, caption text outside its only bbox,
  derived images labeled native, frontend evidence loss, footer omission, and
  a semantic element emitted twice.

No phase exit is allowed with an unexplained output difference. Intended additive
differences require an evidence record and compatibility decision. Measure
serialization overhead against the P00-US10 reference run and keep phase p95
overhead at or below 5%.

## Final completed gate

P01-US04 and Phase 1 closed on 2026-07-29:

- cross-language canonical/legacy/additive/negative parity passed 49 tests,
  and the retained Phase 0 frontend projection brought the combined gate to 50;
- the full backend passed 804 tests with 10 documented opt-in skips;
- supported-Node lint, typecheck, five-stage production build, 42 unit tests,
  and one built-output test passed;
- all 15 documents and 30 pages use byte-identical stored canonical Markdown
  and ordered semantic text, while all 15 flag-off documents retain frozen
  legacy Markdown;
- JSON evidence is preserved and canonical data appears exactly once in
  normalized output;
- independent differential review matched Python across all 15 real contracts
  and 239 adversarial mutations; independent UI/API review also passed;
- cumulative Phase 1 p95 overhead is 1.402480%, below the 5% ceiling;
- all seven phase exit criteria pass.
