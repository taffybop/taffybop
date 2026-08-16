# LAT-US01 r34 scoped owner exception

Status: **Requester-approved**  
Date: 2026-08-10  
Decision owner: Requester

## Decision

The requester approved completion of LAT-US01 with a narrowly scoped owner
exception for the retained r34 `diagnostic_hwm_delta_exceeded` finding. The
story may be recorded as Done, but the failed local instrumentation-HWM result
remains a failed result and is never represented as a pass.

## Exact scope

This exception applies only to these retained artifacts:

- Profile SHA-256 `7f50beda94a0ddfa36cef6d9c563ae1b5ba77b9e96d944cb4445d92b8cd4e01c`
- Evaluation SHA-256 `828f607e1a27cb501235c6294f9602fce7d021ee02d2f1efbfd93fc8a7dd4898`
- Attempt ledger SHA-256 `28b8e9d6d82727fb1c17c911dbe5a06ab68ac3117f62b2851a87c943c56d4041`

It covers only the evaluation's single failure code,
`diagnostic_hwm_delta_exceeded`, where five local pairs exceed the unchanged
67,108,864-byte diagnostic-versus-authoritative worker self-HWM ceiling. It
does not change that ceiling, delete failed history, or claim a local RSS,
LlamaParse latency, quality, security, compatibility, custody, output, or
production pass that the retained evidence does not establish.

## Non-transfer and stop boundary

The exception is non-transferable: it cannot be used for altered code,
dependencies, models, configuration, corpus bytes, environment, another
campaign, or any other story. It does not authorize a selective rerun through
the known-limited continuation driver.

LAT-US02 remains Proposed and has not started. This decision does not authorize
LAT-US02 readiness, implementation, testing, or evidence work; it also does
not resume Phase 04, touch Phase 05, enable production, or authorize a hosted
LlamaParse campaign. Separate requester confirmation is required before any
next-story action.

## Supporting record

- [r34 non-RSS validation](../evidence/LAT-US01-r34-non-rss-validation.md)
- [r34 conditional completion record](../reports/LAT-US01-non-rss-closure-r34.md)
