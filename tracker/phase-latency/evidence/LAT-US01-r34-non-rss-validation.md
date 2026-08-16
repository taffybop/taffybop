# LAT-US01 r34 non-RSS closure validation

Date: 2026-08-10  
Status: **Non-RSS validation complete; subsequent scoped owner exception records LAT-US01 Done**

## Scope and boundary

This record seals the retained r34 profile against the LAT-US01 requirements
other than the independently unresolved diagnostic-versus-authoritative HWM
gate. It neither reruns the retained campaign nor creates a resource exception,
latency pass, production approval, or later-story authorization.

The sole retained candidate profile is
[`LAT-US01-final-candidate-profile-r34.json`](LAT-US01-final-candidate-profile-r34.json),
SHA-256 `7f50beda94a0ddfa36cef6d9c563ae1b5ba77b9e96d944cb4445d92b8cd4e01c`.
Its deterministic evaluation is
[`LAT-US01-final-candidate-evaluation-r34.json`](LAT-US01-final-candidate-evaluation-r34.json),
SHA-256 `828f607e1a27cb501235c6294f9602fce7d021ee02d2f1efbfd93fc8a7dd4898`.
The private retained attempt ledger is
[`LAT-US01-final-candidate-attempt-ledger-r34.json`](LAT-US01-final-candidate-attempt-ledger-r34.json),
SHA-256 `28b8e9d6d82727fb1c17c911dbe5a06ab68ac3117f62b2851a87c943c56d4041`.
All three files are regular mode-`0600` evidence files.

## Revalidation

`CandidateProfileSet.model_validate_json` accepted the exact profile. A fresh
`evaluate_candidate_profile_set` result was byte-for-byte equal to the retained
evaluation and bound the profile hash above. It selected all 47 planned slots:

| Check | Result |
|---|---|
| Attempt observations / selected attempts | 47 / 47 |
| Role observations | 94 |
| Successful attempts / role observations | 47 / 94 |
| Attempt, role, and controller failures | 0 / 0 / 0 |
| Drifted observations / missing slots | 0 / 0 |
| Cases / pages / reviewed claims | 15 / 30 / 210 |
| Literal / semantic / excluded masks | 109 / 162 / 48 |
| Controls / dimensions | 25 / 12 |
| Unexplained output drift | false |
| Hosted calls, credits, tokens, cost, egress | 0 / 0 / 0 / 0 / 0 |
| Production instrumentation / feature flag | false / null |
| Rollback disposition | stop disposable benchmark workers |

The profile model also revalidated exact slot order, complete ledger
selections, source and dependency identities, cache-disabled/offline policy,
authoritative/diagnostic parity bindings, stage/resource boundary completeness,
output custody, and the closed failure vocabulary. This is structural and
custody validation of retained evidence; it is not a new performance campaign.

## Identity reconciliation and focused retest

The following current identities match r34 exactly:

| Identity | SHA-256 |
|---|---|
| Candidate `app/**` code tree | `d1d65d70a98dcdbbfbdccae9cb5c82316395765777f1c8fb9a439af8d64624d7` |
| Dependency manifest | `0253ae6df39a044b66d2b10d1a486841c7a25b2b1225e9a6aee2b6bf3016a2dc` |
| Model artifacts | `a204f7eaeb2cac3d30ea9618d7ebe1afdfab74646a4c2b47ba0897d386b764f5` |
| Each of the ten retained harness files | exact match to the r34 identity manifest |

No production Python source, `pyproject.toml`, `uv.lock`, frontend source, or
frontend lockfile changed after the retained r34 profile. The only executable
file changed after r34 is the isolated continuation-driver test. Its focused
check, `tests/performance/test_lat_us01_resume_driver.py`, passed **4/4** with
one pre-existing FastAPI/Starlette deprecation warning in 0.18 seconds.

Accordingly, the retained backend and frontend reports named in the resumption
handoff are reused only for the unchanged surfaces they cover; this record does
not relabel them as new complete-suite results. No complete backend/frontend
suite, all-15 performance campaign, hosted LlamaParse campaign, or RSS campaign
was run.

## Preserved limitation and remaining exception

The continuation driver remains unsuitable for an acceptance-producing
selective rerun: it supports only contiguous-prefix reuse, does not bind all
measurement-changing options to identity, does not retain parent-ledger
lineage, and could omit prior resource-failing history under general
selection. It was not used to create a new acceptance result here.

The retained evaluation is `passed: false` solely for
`diagnostic_hwm_delta_exceeded`: five local pairs exceed the unchanged
67,108,864-byte ceiling. That result is preserved without reinterpretation.
It is the sole remaining LAT-US01 exception after this non-RSS validation, but
it was not waived by this validation. The subsequent requester-approved
[scoped owner exception](../decisions/LAT-US01-r34-scoped-owner-exception.md)
records the exact r34 Done transition without changing the failed result.

## Separate review records

- [Production and security review](LAT-US01-r34-production-security-review.md)
- [Metrics and custody review](LAT-US01-r34-metrics-custody-review.md)
- [Conditional completion record](../reports/LAT-US01-non-rss-closure-r34.md)
- [Scoped owner-exception decision](../decisions/LAT-US01-r34-scoped-owner-exception.md)
