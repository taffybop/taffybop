# LAT-US02 metrics and custody review

Date: 2026-08-10  
Review scope: identity custody, artifact materialization, CPU/RSS interpretation,
test evidence, campaign absence, and tracker status  
Disposition: **NO-GO — one Major, no Blocker, no separate Minor finding**

## Identities and artifact custody

- application:
  `4c75f9384e298a65adab275ec3a12df8088af2db84064e1a99c3e9931f4a53ed`
- dependency manifest:
  `0253ae6df39a044b66d2b10d1a486841c7a25b2b1225e9a6aee2b6bf3016a2dc`
- runtime dependency:
  `1801756d928fdb92825663653b8c7d87a39c2d5cb9563dcad614c12aef8c299b`
- parser runtime:
  `542c879fdc2cfe0be223e4729082bac529780d90c6d811c853de852765b35a35`
- LAT-US02 harness:
  `4c1094e4558311908e4eccc29eb987abad312405428a0e1abf7b2b08ee35c750`
- lifecycle tests:
  `81acd07bdd21623d704fcc29641aa52d4883b4067c92afd03403627f6a451ec7`
- network isolation:
  `daa9f3e2323569be9fe97a1ef4fbfaf56082e90479558b3c6a87f8f1ca447ae9`

The approved combined artifact tree revalidated at content SHA-256
`7da24e7a135b1f0c66048fb552c5dce4d41bc328daf9e86670f435203dad09d4`
and metadata SHA-256
`976a5216d69fc5162944bf54338163445de58113729c4881da6574a15195667f`:
`56` regular files, `563,549,064` logical bytes, exact two-source union, no
symlinks, owner-private mode `0700`, and matching pre/post no-write observation.
The in-memory materialization-manifest identity is
`6099699b…5365`.

The retained LAT-US01 mode-`0600` ledger/profile/evaluation remain exact:

- ledger `28b8e9d6…d4041`
- profile `7f50beda…e01c`
- evaluation `828f607e…898a`

Its evaluation remains false solely for `diagnostic_hwm_delta_exceeded`, with a
maximum delta of `234,389,504` bytes. LAT-US02 does not rewrite or reuse that
failure as a pass.

## Test and campaign custody

The production-adapter contract passed **62/62** with one existing warning;
its SHA-256 is
`b25bef9f43934ab62bfabe207070bab79f2d0bb52cda2dff5ccf8cdc76c8f8b4`.
The independently repeated five-suite matrix passed **165/165** with the same
warning. These are controller/contract validations, not production benchmark
measurements.

No LAT-US02 production directory, launch receipt, attempt receipt, evaluation,
completion report, real ASGI campaign, hosted call, provider credit, or egress
record exists. Hard-zero hosted-use schema fields remain intact.

## Blocking metric finding

The adapter's aggregate reaped-child rusage plus live edge snapshots cannot be
independently recomputed for every PID/create-time lineage and can omit a
short-lived/reparented native descendant without marking contamination.
`sampled_late=false` is not derived from a complete lineage ledger. This
violates the exact request-boundary CPU authority in [metrics.md](../metrics.md)
and is recorded as Major `LAT-US02-METRIC-CPU-001`.

The owner-directed LAT-US02 exception makes numerical RSS observational only.
It does not make incomplete CPU/process evidence observational and does not
authorize selecting, retrying, or omitting a failed local run. No RSS pass or
RSS measurement result is claimed because the campaign never launched.

## Review conclusion

Keep LAT-US02 In Progress and LAT-US03–LAT-US08 Proposed. Resume requires exact
native per-process counters, complete birth/exit lineage and reaped tombstones,
derived late/coverage status, missing/rounded evidence failure, adversarial
short-lived child/grandchild and reparent/PID-reuse controls, a new frozen
identity set, and fresh prelaunch security and metrics approval.
