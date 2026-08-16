# Benchmark Contract Semantics

These test/reporting-only contracts use schema version `1.0`. Every payload must
state that version explicitly; an omitted or unknown version is invalid. They
must never be imported by production parser code.

- `FixtureManifest` records immutable source identity as a lowercase SHA-256,
  source format, and a non-empty custody description. A description records
  state but is not itself a source-rights approval.
- `Annotation` records a reviewed claim and its evidence class. Measured,
  inferred, and unknowable claims cannot be literal/exact-parity targets;
  measured evidence requires a linked `MetricRecord` semantic comparison.
- `MetricRecord` records a finite, non-negative measurement, its explicit unit,
  a finite, non-negative tolerance in that same unit, and a non-empty
  measurement method. Optional fixture and annotation IDs link a measurement
  to the source claim it evaluates.
- `RunRecord` records the parser and model versions, exact commands, hardware,
  fixture hashes, output hashes, elapsed time, and measured metrics.

Supported truth classes are `visible_text`, `native_data`, `embedded_data`,
`measured`, `inferred`, and `unknowable`. Supported metric units are
`2025_USD_billions`, `bytes`, `count`, `MiB`, `ms`, `percent`, and `ratio`; a
metric tolerance uses the same unit as its value. The currency unit is an
additive benchmark-only v1 extension introduced for P00-US02's explicitly
measured 2025-dollar chart geometry. Contracts are serialized through
`canonical_json`, which sorts object keys and uses compact UTF-8 JSON so a
validated record has one deterministic, standards-compliant representation.

## Portable corpus registry

P00-US04 adds a test/reporting-only portable registry for the supplied
LlamaParse-15 corpus. The frozen analysis manifest remains unchanged; the new
registry stores only POSIX workspace-relative paths and receives the workspace
root explicitly when current bytes are verified.

The registry contract requires exactly 15 cases, 30 physical pages, and 45
artifacts. Each case owns one source PDF, one expert Markdown file, and one
expert JSON file, together with category, layout, complex-element, page-map,
and approved custody metadata. Physical pages are one-based and contiguous.
Printed page labels remain strings and may be explicitly `null`; they are never
inferred from physical page numbers. Page width/height are displayed dimensions
in points, while `source_rotation_deg` records raw PDF rotation metadata. This
distinction makes the ESG page `792 × 612` points with raw rotation `90`.

All 15 cases use the six approved boundaries: workspace retention, repository
commit, benchmark redistribution, local validation, private-CI validation, and
committed-CI validation. The registry pins the frozen manifest, custody
decision, and source-rights evidence by portable path and SHA-256. It contains
no timestamp, host name, absolute root, reviewed claim, scoring mask, control
role, parser result, or production schema.

## Reviewed claims and inclusion masks

P00-US05 adds generalized claim contracts while reusing the P00-US01
`TruthClass` vocabulary unchanged. Each `ReviewedClaimRecord` carries a stable
claim and source-review row identity, primary claim type, normalized review
status, explicit reviewer/version, one or more registered page/region locators,
and separate literal/semantic inclusion masks.

Locators use one-based physical pages, the exact reviewed printed label
including explicit `null`, stable region IDs, and top-left
`[x,y,width,height]` points in displayed/post-rotation page space. A bbox may be
omitted for page-wide, ambiguous, derived, or synthetic-control regions; when
present, it must be finite, positive, and wholly inside the P00-US04 page.

Only fully verified `visible_text`, `native_data`, or `embedded_data` claims can
enter literal parity, and literal inclusion always implies semantic inclusion.
Incorrect, potentially inferred, and not-independently-verifiable expert claims
cannot enter either denominator. `measured` evidence is semantic-only and must
carry a non-empty derivation method, finite non-negative tolerance, and
tolerance unit. Verified inferred relationships and unknowable negative
controls can remain semantic expectations without being promoted to literal
truth.

`ReviewBatch` rejects duplicate claim IDs and review rows, noncanonical order,
count drift, mixed schema versions, and registry identity drift. Registry
validation rejects unknown cases/pages, printed-label drift, unsupported
coordinates, and out-of-page geometry. Canonical compact JSON and its SHA-256
provide deterministic batch identity. The backward-read adapter projects all
163 frozen P00-US02 catastrophe claims and projects each one back to the
unchanged P00-US01 `Annotation` contract.

## Reviewed claim inventory — Batch A

P00-US06 registers 71 one-to-one narrative review rows from
`catastrophe-recap`, `esg-metrics`, `finance-10k`,
`manufacturing-report`, and `purchase-agreement`. The inventory builder reads
only the `## Expert element validation` section in each frozen case report,
pins that report's SHA-256, keeps grouped expert item ranges as one row, and
combines the row with an explicit case/page/type/evidence policy. It never
discovers claims from the raw expert Markdown.

The persisted batch contains 44 verified, 17 partially verified, 6
not-independently-verifiable, and 4 incorrect rows. It includes 41 literal and
61 semantic parity claims. Partially verified rows are semantic-only;
incorrect and unverifiable rows enter neither denominator; inferred and
measured evidence never enters literal parity. The one measured row is the
known incorrect catastrophe chart series and retains its vector calibration
method and tolerance.

Every claim has at least one registry-valid locator. The 71 claims use 75
locators because the finance bbox and confidence rows each cover all three
registered pages. Optional bboxes remain `null` where the narrative review
does not establish exact region geometry; the inventory does not fabricate
coordinates. Reload compares the persisted canonical batch with a fresh
source-row build and fails closed on report, policy, registry, or evidence
drift.

P00-US07 adds Batch B without changing Batch A bytes. Its 76 one-to-one rows
cover `clean-energy`, `clinical-study`, `component-datasheet`,
`insurance-acord`, and `ny-timetable`. The reader accepts the four-column
review format and the timetable's five-column format by locating the `Status`
header; it preserves any additional evidence column in claim text. Inline
code-span pipes, bold verdicts, verdict qualifiers, Unicode page ranges, and
grouped multi-page claims remain intact.

Batch B contains 43 verified, 15 partially verified, 8 incorrect, 5
potentially inferred, and 5 not-independently-verifiable rows. Of those, 36
enter literal parity and 58 enter semantic parity. Its 121 locators preserve
the reviewed physical-to-printed page maps. The exact clean-energy bar values
remain inferred and excluded because the source review supplies no
multi-scale derivation or tolerance; Batch B creates no measured evidence or
derivation records.

P00-US08 adds Batch C without changing either prior batch. Its 63 one-to-one
rows cover `egov-survey`, `health-report`, `postal-10k`,
`settlement-agreement`, and `uber-earnings`, closing the 210-row inventory
across all 15 registered cases. The reader preserves health's inline-code pipe
and all grouped/multi-page rows while the explicit policies preserve physical
and printed page identity.

Batch C contains 34 verified, 9 partially verified, 9 incorrect, 6
not-independently-verifiable, and 5 potentially inferred rows. Of those, 32
enter literal parity and 43 enter semantic parity. Its 75 locators bring the
corpus total to 271. Only three Uber chart rows use measured evidence, each
with an explicit vector interpolation method, tolerance, and unit; those rows
remain excluded from both masks. The health bubble-chart row remains incorrect
and inferred without a fabricated tolerance or derivation.

## Benchmark control registry

P00-US09 registers all 25 frozen primary gap owners, one complete four-role
control quartet per owner, and all 109 ordered case-gap rows. The 100
assignments contain 25 targets, 25 related-positive controls, 25 non-target
regression controls, and 25 negative-or-ambiguous controls. Every role and
case row resolves an exact locator in the completed 210-claim corpus.

Positive and non-target roles use only verified or partially verified
semantic evidence. Negative/ambiguous roles use 13 incorrect, 7
not-independently-verifiable, and 5 potentially inferred claims, all excluded
from both masks. An independent 109-row anchor audit replaced 32 weak
vocabulary matches with decisive source-region claims. The only missing
reviewed `page_identity` claim is explicit: the `postal-10k` page row uses an
all-page, mask-false metadata proxy without promoting truth.

The canonical registry semantic SHA-256 is
`d3c734957b507f07508f8eeffe43ac450f50f53d5f42f8cf63e354fe60738fce`;
the newline-terminated evidence file is
`a383938d41d067e0b3e01729d12def7b573764092100ef76228e4c23707c86b5`.
All matrix, report, corpus, and Batch A/B/C identities remain pinned.

## Immutable corpus runner

P00-US10 adds `corpus_runner.py` as test/reporting infrastructure only. Before
reserving a run directory it strictly reloads all 45 corpus artifacts, the
three reviewed-claim batches, the control registry, frozen reference outputs,
fixed settings, application/runner source identities, required local engine
versions, and the reference environment. A run directory is a canonical
`tracker/phase-00-baseline/evidence/<run_id>` child and is never reused.

Each selected case executes in its own enforced-offline subprocess. Raw JSON,
duration-masked semantic JSON, Markdown, logs, timing, CPU, RSS, warnings,
errors, page completion, raw worker record, and coordinator projection are
retained with hash/size bindings. Missing, altered, partial, timed-out,
silently skipped, colliding, or incompletely versioned runs fail closed.

The semantic report always contains the canonical 12 dimensions: text, layout,
reading order, table, chart, diagram, Markdown, JSON, hallucination,
diagnostics, performance, and cost. Provenance is mandatory on claim results
and is not a thirteenth quality score. The 210 reviewed narrative claims keep
their exact 109 literal, 162 semantic, and 48 excluded masks. Eligible claims
without a versioned executable evaluator are `diagnostic_only`, never
automatic passes; unsupported expert claims are explicit exclusions. No
composite quality score is produced.

The final retained run completed 15/15 cases and 30/30 pages. All 15
duration-masked JSON and exact Markdown identities match the frozen reference,
performance is within the declared matching-environment tolerance, and hosted
cost is zero. Its quality and stable-output signatures are
`a18dfdeec1eda8840e269da046285aa518a9a6094e4943e174f0893dc216a1ed`
and
`a7b02cdee0e58c881122a692d2bfecdacb13eefbb35225be705ae3ff6c7113a0`.
