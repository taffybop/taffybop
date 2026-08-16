# Phase 06 Regression Plan

## Release-first validation

For the current release, use deterministic local/hosted test doubles to prove
contract, routing, grounding, merge, ordinary adapter failure, deterministic
fallback, and default-off behavior. No live or billable model call is required.
Benchmark, hardware/resource, campaign, and exhaustive adversarial requirements
below are deferred to post-release hardening.

Run Phase 00–06 regressions and contracts in these modes:

1. all visual models disabled;
2. eligible and ineligible regions with a deterministic local mock/model;
3. hosted transport mocked with allow and deny policies;
4. grounded and ungrounded model observations;
5. accepted merge and every deterministic fallback path.

Required negative cases:

- no configured model;
- missing/corrupt model weights;
- timeout, quota, malformed schema, and unsafe content;
- ineligible or already-complete deterministic region;
- output without evidence IDs;
- unknown, cross-page, or out-of-crop evidence references;
- value inconsistent with source geometry;
- invalid chart or diagram structure;
- disallowed document classification;
- exhausted page/document cost budget;
- duplicate merge and canonical-presentation conflict.
- source image with no caption returned as a `document_caption`;
- New Zealand flag identified as Australia without sufficient pixel evidence;
- exact unprinted chart value without cited mark/axis evidence and tolerance;
- directed Mermaid-style edge where the source connector has no arrowhead.

Required controls:

- positive: explicit Uber chart endpoints and visible diagram/node labels retain
  source provenance and are not relabeled as generated;
- non-target: complete deterministic text/table regions make zero model calls
  and remain byte-equivalent through fallback;
- negative: the false-caption, flag-identity, ungrounded-value, and
  unsupported-direction cases above are rejected with stable reasons.

The default-disabled mode must reproduce the Phase 05 deterministic result.
Ineligible regions must produce zero adapter calls. Rejected observations must
not reach merge, and merge/fallback runs must preserve the approved evidence,
IDs, order, concerns, and canonical output.
Accepted generated evidence must retain its distinct origin in JSON, Markdown,
and text and appear once. Performance evidence reports routing, adapter,
grounding, merge, and fallback time separately for diagnosis; these component
timings are not latency gates, and no quality gate may be waived because a
faster ungrounded path exists.
No CI test may require live network access or billable inference.
Required paired Llama service samples are captured by a separately authorized,
retained benchmark run outside CI and then consumed as gate evidence.

The sole operative latency gate is
[`latency-reference-v1.md`](../benchmarks/llamaparse-15/latency-reference-v1.md):
for every semantically comparable case, refresh at least five interleaved
candidate/Llama samples before Definition of Done and phase exit, and require
candidate p50 and nearest-rank p95 to be no greater than their paired Llama
values per case. Corpus averages cannot mask a slow case, failures cannot be
dropped, and required quality/reliability must be unchanged. Non-comparable
cases remain `Unmeasured/Blocked`. Timeout/fail-closed, RSS/resource, output,
cost, security, compatibility, custody/hosted-use, default-off, and rollback
gates remain independent.
