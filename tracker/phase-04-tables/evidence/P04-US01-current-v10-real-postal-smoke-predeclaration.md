# P04-US01 Current-v10 Real Postal Smoke Predeclaration

Date: 2026-08-07  
Status: Predeclared; not yet executed  
Classification: noncanonical, non-retained reviewed-document smoke

This one-run smoke uses `metrics.fresh_snapshot` for reviewed real benchmark
case `postal-10k` with P04-US01 enabled under the independently approved v10
code (`metrics.py` SHA-256
`8fb8ef4b05229c587f480d803057ce8963c38ed3558f741fe6fd03e755ab89b6`,
`rss_lane.py` SHA-256
`c07133c0bddf3c748303923aedd01ef4a63df2f5a90f6f5ce2c8f680eb98f0b5`).
It prints only bounded selected metrics; it does not write the retained final
metrics destination.

The smoke passes only on zero exit, empty worker diagnostics, exact v7 external
attestation/v4 lane protocol validation, unchanged 10 ms RSS and 100 ms child
hard gaps, zero observed children, unchanged child-rusage fingerprint,
default resource/output/deadline gates, complete cleanup, and a bounded JSON
summary containing latency, RSS, sample counts, identities, schemas, sidecar
bytes, and gate state.

A failure is sealed and is not a current pass. A success remains a one-case,
one-state smoke; it cannot replace three-case five-pair canonical evidence,
quality evidence, a retained report, story completion, Phase 04 exit, or Phase
05 authorization.
