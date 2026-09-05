# 2026-08-23 user requirement amendment — ACORD structure and chart source-asset arbitration

Status: **Accepted for tracking; no production implementation authorized by this amendment**

## Request

1. Preserve the original structure of the complex form-type table in
   `insurance-acord.pdf`, keeping field names, blank slots, controls, and any
   entered values in their original logical row/column/group positions.
2. Use a staged chart pipeline: detect the chart, retain its source visual,
   classify its family and complexity, attempt trustworthy semantic assembly,
   validate completeness, and preserve the original image for later advanced
   OCR/model work regardless of the primary representation selected now.

## Classification

- The ACORD requirement refines existing SG-016/FFD-010. It is not a second
  defect for the same source region and ownership root cause.
- Source-asset custody and terminal arbitration for every detected chart are a
  distinct post-baseline requirement, FFD-015. FFD-003 continues to own
  semantic chart assembly and its family-specific completeness validators. A
  retained image preserves visible evidence but does not prove axes, legends,
  categories, series, or points were understood.

## Registry invariants

- The immutable v2 denominator remains 25 source gaps and 13 baseline root
  causes. No `SG-026` is created and no authoritative baseline wording or hash
  changes.
- Post-baseline tracked defects are FFD-014 and FFD-015.
- Tracker total becomes 15 defects and 24 ordered implementation slices.
- Status counts become 13 Proposed, 0 Ready, 1 In Progress, 0 Validating,
  1 Blocked, and 0 Done.
- The strict one-production-defect WIP limit remains. This amendment records
  requirements only and does not start FFD-010 or FFD-015.

## Safety decisions

- Form fidelity is structural. Extracting the same words into a flattened list
  is not equivalent to preserving the source grid. Blank fields are meaningful
  structural values and must not disappear or receive placeholders.
- Every conservatively detected chart owner attempts deterministic bounded
  source-asset retention before semantic dispatch. Actual bytes and integrity
  custody are required; metadata-only retention or a server-local path is
  insufficient. Unsafe or unavailable assets fail closed.
- Family classification and `regular`/`complex` classification are independent
  metadata. Complexity alone never selects the public primary: any complete,
  grounded chart, regular or complex, is structured-primary.
- Terminal state is exactly one of `structured_primary`,
  `image_primary_unsupported`, `image_primary_incomplete`, or
  `asset_unavailable`. Unsupported analyzer coverage is distinct from attempted
  but incomplete/ambiguous/failed analysis.
- Native/OCR chart text remains separately attributable and nonduplicating.
  Later advanced analysis is append-only, must preserve the original asset
  bytes/ID/hash/crop custody, and may promote semantics only by passing the same
  family-specific completeness validator.

## Closure evidence

- FFD-010: fresh full `insurance-acord.pdf` Llama/service/JSON/Markdown/DOM
  evidence, complete source grid oracle, blank and entered-value variants,
  static-control states, transformed/generic positives, adversarial ownership
  refusals, and unchanged adjacent/parties evidence.
- FFD-015: fresh full evidence for all seven affected chart PDFs; exact chart
  asset bytes/hashes and overlays; independent family/complexity traces; all
  four terminal states and legal enrichment transitions in focused evidence;
  unchanged asset identity across promotion; once-only JSON/Markdown/DOM
  primaries; transformed chart variants, non-chart controls, malformed/resource
  refusals, attributable transcripts, and no invented semantics.
- Both cards remain subject to their immediate affected-benchmark gates, wave
  gates, generic-production policy, and the final all-15 campaign.
