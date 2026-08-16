# LAT-US01 r34 metrics and custody review

Date: 2026-08-10  
Review scope: retained evidence identity, denominators, reproducibility,
quality/output custody, test-report reconciliation, and metric interpretation  
Disposition: **No non-RSS blocking or Major finding; conditional only**

## Identity and reproducibility

The r34 profile, evaluation, and private ledger retain the exact SHA-256
identities recorded in [the non-RSS validation](LAT-US01-r34-non-rss-validation.md).
The profile schema accepted the retained bytes, and a fresh evaluator result
equalled the retained evaluation exactly. The evaluator therefore preserves the
complete denominator: 47 selected attempts, 94 role observations, 47
successes, zero failures, zero controller failures, zero drifted observations,
and zero missing slots.

Current candidate-code, dependency-manifest, model-artifact, and ten harness
file identities are exact r34 matches. The retained profile binds all 15 cases
in order, 30 pages, exact source custody, cache-disabled/offline execution, and
the complete final ledger. The validation did not substitute a fresh campaign
or a selectively reused subset.

## Quality, compatibility, and output custody

The retained current-runtime comparison reports zero unexplained drift with
210 reviewed claims, 109 literal-eligible claims, 162 semantic-eligible
claims, 48 excluded unsupported masks, 25 controls, and 12 dimensions. Its
quality signature remains
`a18dfdeec1eda8840e269da046285aa518a9a6094e4943e174f0893dc216a1ed`; the
historical stable-output signature remains
`a7b02cdee0e58c881122a692d2bfecdacb13eefbb35225be705ae3ff6c7113a0`.

The r34 model validation accepted exact current-runtime JSON/Markdown custody,
per-role output parity, stage lifecycle/resource closure, closed failure
vocabulary, source/dependency/model/configuration/environment identities, and
zero hosted-use values. The profile is explicitly environment-noncomparable to
P00, so no P00 performance-regression pass is claimed.

## Test-report reconciliation

Existing backend, frontend, focused harness/custody, and fatal-envelope reports
remain historical retained reports rather than invented fresh results. Current
production, dependency, frontend, and retained-harness identities did not
change after r34. The only post-r34 executable change is covered by the fresh
4/4 continuation-driver check. The full backend, frontend, all-15 performance,
hosted, and RSS suites were deliberately not rerun.

## Review conclusion

Metrics and custody evidence is complete for every non-RSS LAT-US01
requirement. The r34 evaluation still contains exactly one failure code,
`diagnostic_hwm_delta_exceeded`; that independent resource finding is neither
hidden in an aggregate nor offset by quality, output, or LlamaParse evidence.
This review therefore supports non-RSS closure only and does not approve a
normal Done transition or a resource exception.
