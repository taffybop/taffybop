# Phase 08 Regression Plan

## Release-first validation

For the current release, validate flag/rollback wiring, a no-op and failing
telemetry exporter, representative confidence/fallback and review flows,
artifact-manifest generation, hosted deny/allow behavior, one functional
candidate/known-good smoke comparison, and one rollback smoke. The exhaustive
telemetry, calibration, canary, performance/resource, evidence, privacy,
failure-injection, and recovery-time plan below is deferred to post-release
hardening.

## Story execution

Run only one Phase 08 story at a time. For each story:

1. confirm Definition of Ready and record before metrics;
2. run its dedicated test file;
3. run completed Phase 08 story tests;
4. run every impacted earlier-phase regression;
5. run API/schema and canonical-serialization contracts;
6. verify the documented flag-off or operational rollback;
7. record evidence and stop for approval.

## Required Phase 08 suites

- `tests/stories/phase_08/`
- `tests/regression/phase_08/`
- `tests/contract/`
- `tests/benchmarks/`
- `tests/performance/`
- applicable frontend canonical-serialization tests

## Fixed regression profiles

- Local core with every optional behavior disabled.
- Deterministic text/layout/table profile.
- Structured chart/diagram profile.
- Local visual-model profile.
- Hosted route denied by policy.
- Hosted route approved through a test double only.
- PDF, direct image, DOCX, PPTX, and XLSX adapter-conformance profile.
- Missing, corrupt, or hash-mismatched optional artifact.
- Exporter unavailable, slow, and backpressured.
- Review budget exhausted and review route unavailable.
- LlamaParse-15 source-grounded hard-negative profile.
- Missing M5 semantic-twin coverage profile.

No CI suite performs billable live Llama inference. Required paired Llama
service samples are captured by a separately authorized, retained benchmark
run and then consumed by the canary/release gate.

## Quality and compatibility gates

- No unexplained regression by document category.
- No missing, duplicate, or fabricated content on frozen fixtures.
- All emitted claims retain required evidence, provenance, confidence, and
  concerns.
- JSON, Markdown, text, API errors, and legacy projections remain compatible.
- All default-off paths reproduce the approved earlier-phase baseline except
  for explicitly excluded nondeterministic runtime metadata.

## Telemetry and calibration gates

- Metric labels and structured telemetry contain no document text, filenames,
  crop bytes, prompts, secrets, or unbounded identifiers.
- Exporter failure never fails or materially delays parsing.
- Stage/component p50/p95 timing is retained for diagnosis; CPU, peak RSS/GPU,
  and instrumentation resource overhead stay within approved P00 resource
  budgets. End-to-end latency uses only the paired LlamaParse gate below.
- Quality, fallback, escalation, and external-cost signals reconcile with
  fixture truth and test-double call records.
- Calibration uses disjoint fit/evaluation partitions and meets approved
  per-content ECE/Brier targets; otherwise the category remains conservative.
- Every review packet is grounded and every routing decision observes its
  configured document/region budget.
- Diagnostics distinguish correctly detected, missed, and false-positive
  concerns against source-grounded fixture truth.
- Confidence never substitutes OCR/classifier/page confidence for text,
  structure, completeness, value, relationship, or generated-claim confidence.

## LlamaParse-15 controls

- Positive: verified `postal-10k`/`settlement-agreement` tables, explicit Uber
  chart endpoints/node labels, and unchanged deterministic fallback.
- Non-target: complete source evidence and disabled optional routes remain
  byte-equivalent and produce no review/model calls.
- Negative: NY 13-to-12 grid collapse without concern; Postal `FERS`/`ClO`;
  purchase redline/order loss; settlement `Look-Back`; Uber false caption,
  New Zealand/Australia, hidden chart text, ungrounded values, unsupported
  directions, duplicate representations, bad bbox, and printed-page mismatch.
- Coverage negative: absent direct-image, scanned, DOCX, PPTX, or XLSX
  semantic-twin class blocks the applicable profile rather than being reported
  as a passing zero-count comparison.

## Release and rollback gates

- Runtime, dependency, OCR, converter, and model artifacts are versioned,
  hashed, sourced, and license-reviewed.
- Hosted processing is denied unless data classification, tenant policy,
  region scope, retention, residency, redaction, provider, and model version
  are approved.
- Canary comparison covers quality, compatibility, provenance, resources,
  escalation, and cost against the pinned known-good release; latency is
  compared only with paired LlamaParse evidence.
- Canary evidence represents all named LlamaParse-15 gaps and traces each
  blocking result back to its case/page/region and upstream gate without
  storing source content in telemetry.
- Controlled quality, paired LlamaParse latency, artifact, privacy, exporter,
  and routing failures trigger their documented stop or rollback path.
- The full rollback restores known-good artifacts, flags, API/schema behavior,
  and fixture results within the approved recovery-time objective.

## Phase exit

P08-US12 must produce a completion report and phase summary showing every gate,
before/after metric, exception, owner, and approval. Production release remains
blocked until that evidence is reviewed explicitly.
The sole operative latency gate is
[`latency-reference-v1.md`](../benchmarks/llamaparse-15/latency-reference-v1.md),
including its full 15-case release screen. Before Definition of Done or phase
exit, refresh every applicable case with at least five interleaved
candidate/Llama samples. Candidate p50 and nearest-rank p95 must each be no
greater than their paired Llama values per case; no corpus average may mask a
slow case, no failure may be dropped, and required quality/reliability may not
regress. A path without semantically comparable Llama input/output remains
`Unmeasured/Blocked`; single-run historical totals and local stage/component
timings are diagnostic only and cannot satisfy or waive latency. CPU/RSS/GPU,
instrumentation isolation, quality, security/privacy, compatibility,
custody/hosted-use, cost/output, timeout/fail-closed, default-off, recovery, and
rollback gates remain independent.
