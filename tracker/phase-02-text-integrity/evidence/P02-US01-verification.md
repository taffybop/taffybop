# P02-US01 Verification Evidence

Date: 2026-07-30  
Status: Pass

## Scope and compatibility

- The audit is enabled only when
  `PARSER_TEXT_INTEGRITY_FONT_AUDIT_ENABLED=true` and both shared-IR flags are
  enabled. It is off by default.
- It adds reason-coded internal IR concerns and evidence without changing
  native text, the public endpoint, the legacy projection, or canonical
  presentation.
- Indirect fonts retain stable `object:<id>` identity. Direct font
  dictionaries retain audit-local `direct:<n>` identity without conflating
  Python object reuse.
- Complete healthy reports attach through a tested identity return: the same IR
  object is returned without copying or revalidation.

## Acceptance coverage

1. Both malformed catastrophe subsets, objects 13 and 25, are detected with
   stable collapse-to-space findings.
2. All 14 non-target corpus cases across 29 pages and the registered synthetic
   Type0, WinAnsi, multilingual, unusual-font, and intentional-spacing
   controls remain unflagged.
3. Missing `/ToUnicode`, non-identity `/CIDToGIDMap`, ambiguous CMaps,
   unsupported structures, and missing/dangling/non-stream embedded programs
   receive distinct states. Unsafe fonts remain unresolved.
4. Findings retain font reference, optional indirect object ID, identity
   basis, affected bboxes/runs, used CIDs, mapped-character counts, advances,
   reason codes, and confidence basis.
5. Per-font reuse is measured and deterministic. Hard bounds stop font-object
   and character work rather than continuing after a diagnostic.

The bounded CMap parser detects conflicting mappings for a used source CID and
classifies the result `to_unicode_ambiguous`. CID-to-GID streams distinguish
identity, non-identity, malformed, unresolved stream, missing, not-applicable,
and unsupported states.

## Security and retention

- Input is bounded to 25 MiB and 100 pages.
- Work is bounded to 256 fonts, 500,000 characters, 10,000 retained runs,
  256 runs per finding, 256 CIDs per record, 20 diagnostics, and five seconds.
- Raw and decoded CMaps are each capped at 2 MiB with at most 262,144 mappings;
  CID-to-GID data is capped at 128 KiB.
- Embedded font programs are resolved only far enough to classify stream
  presence. Their bytes are never decoded, retained, logged, returned, or
  persisted. Structural tests fail if program decoding is attempted.
- Malformed and unsupported structures yield bounded unresolved diagnostics
  rather than an unsafe recovery or a document-wide parser failure.

## Corpus and performance evidence

The retained runner matched every source SHA-256 to the immutable Phase 0
record and measured 15 cases/30 pages with two warmups and ten samples per
case. It measures the isolated additive audit plus strict report serialization;
complete healthy IR attachment is separately verified as a no-copy identity
return. Phase 0 per-case parse records are historical comparators rather than
paired full-parser samples, and that limitation remains explicit.

| Measure | Result |
|---|---:|
| Bad-font recall | 2/2 (100%) |
| Healthy corpus false positives | 0/14 (0%) |
| Deterministic cases | 15/15 |
| Cache hits / lookups | 83/178 (46.6292%) |
| Healthy overhead p50 / p95 / max | 0.535195% / 2.461017% / 2.885164% |
| Maximum isolated peak-RSS increment | 87,080,960 bytes |

Machine-readable per-case results are retained in
[P02-US01-font-audit-metrics.json](P02-US01-font-audit-metrics.json).

## Test gates

- Focused story, adversarial, structural, anomaly, contract, regression,
  corpus, metrics, and performance gate: **34 passed**.
- Complete Phase 0–2 story, contract, regression, and performance gate:
  **761 passed**.
- Complete backend suite: **838 passed, 10 documented opt-in skips**, and one
  pre-existing Starlette/httpx deprecation warning.
- Python compilation: **Pass**.
- Dependency integrity: **Pass**; `pip check` reports no broken requirements.
- Retained JSON evidence and fixture registry parsing: **Pass**.
- Independent code review after all corrections: **Pass, no findings**.
- Independent corpus/performance review after all corrections: **Pass, no
  findings**.

The 10 skips are the existing real image-model, Docling/finance sample, and
shared-analysis integration gates, each requiring its documented opt-in
environment variable. No acceptance criterion depends on a skipped test.

## Review findings resolved

Independent review originally identified direct-font omission, non-terminating
font/character bounds, collapsed CID-to-GID stream states, unsafe embedded-font
program classification, ambiguous `/ToUnicode` handling, and incomplete
performance coverage. The implementation and tests now cover each case.

Corpus review originally identified narrow exact assertions, unvalidated
registry expectations, and insufficient retained metrics. All 15 corpus cases
now assert their exact expected findings, the registry is cross-validated, and
the reproducible metric artifact records quality, determinism, cache, latency,
and RSS.

## Dependency and rollback

`pdfminer.six==20260107` is now an explicit direct project pin because
production code imports its existing PDF primitives. This introduces no new
installed distribution, model, network service, or font asset. The accepted
license/security decision is
[P02-font-fixture-dependency-policy.md](../decisions/P02-font-fixture-dependency-policy.md).

Set `PARSER_TEXT_INTEGRITY_FONT_AUDIT_ENABLED=false` to bypass the audit. Native
extraction and existing public output then follow the prior path unchanged.
