# P00-US04 corpus custody and redistribution decision

Status: Approved — no exceptions  
Decision date: 2026-07-29  
Authority: requester/provider confirmation in the active execution thread

## Decision

All remaining 14 hash-pinned PDF/Markdown/JSON triplets and their derived
annotations are public and redistributable with no exceptions. Together with
the previously approved catastrophe triplet, this gives all 15 benchmark cases
an explicit public/redistributable custody classification.

Covered case IDs:

- `catastrophe-recap`
- `clean-energy`
- `clinical-study`
- `component-datasheet`
- `egov-survey`
- `esg-metrics`
- `finance-10k`
- `health-report`
- `insurance-acord`
- `manufacturing-report`
- `ny-timetable`
- `postal-10k`
- `purchase-agreement`
- `settlement-agreement`
- `uber-earnings`

The immutable artifact hashes in
[`manifest.json`](../../benchmarks/llamaparse-15/manifest.json) identify the
covered source and expert files. The manifest and operational attestation are
hash-pinned in
[`P00-US04-source-rights.md`](../evidence/P00-US04-source-rights.md).

## Approved operational boundaries

The covered triplets and derived annotations may be:

- copied and retained in the workspace;
- committed to and redistributed with the repository or benchmark package; and
- executed in local, private, or committed CI.

No covered artifact requires a private-reference-only boundary or a synthetic
replacement for custody reasons.

## Non-effects

This decision does not classify expert output as source truth, waive
reviewer-versioned evidence and scoring masks, authorize parser behavior
changes, or waive any Definition-of-Ready, scope, test, regression, or
completion gate.
