# P03-US01 Verification Evidence

Date: 2026-07-31  
Status: Pass

## Scope and compatibility

- `PARSER_LAYOUT_TABLE_CAPTIONS_ENABLED` is default off and requires shared IR
  normalization.
- Enabled output adds only source-grounded caption items and relationship
  fields under schema `1.0`.
- Disabled projection is exact, raw IR caption evidence is retained in both
  states, and table rows/cells never change.
- No package, model, network service, runtime download, hosted request, token,
  or cost was added.

## Exact benchmark result

| Case | Reviewed identity | Result |
|---|---|---|
| Catastrophe physical p1 / printed p7 | Exhibit 7; bbox `[100.700, 210.095, 250.220, 9.351]` | Exact 1/1, linked once |
| Clinical physical p2 | Table 1; bbox `[36.000, 77.922, 169.539, 6.700]` | Exact 1/1, linked once |
| Clinical physical p4 | Table 2; bbox `[36.000, 77.922, 424.521, 7.316]` | Exact 1/1, linked once |
| Finance control | No supported external caption | Exact flag-on/off semantic and Markdown parity |

Aggregate: **3 expected / 3 actual / 3 identity-matched**, precision **1.0**,
recall **1.0**, zero unexpected captions, zero Markdown duplicates, 100% bbox
coverage, 100% relationship plus owner-backlink coverage, and unchanged target
table-content hashes.

## Security and resource behavior

- Non-source, generated, empty, non-text, dangling, orphan, internal, distant,
  malformed, and ambiguous cross-owner candidates fail closed.
- Multiline raw provenance exports the union of all compatible same-page boxes.
- Connected overlap components make same-owner deduplication and cross-owner
  ambiguity transitive and source-order independent, including differing text
  at one physical region.
- Limits are 64 references/table, 128 same-text candidates/page, and 512 total
  candidates/page. At 129 and 513, the complete affected set remains
  evidence-only and pairwise geometry work is zero.
- Overflow diagnostics are bounded and do not contain raw caption text.

Independent adversarial measurements found 128 same-text candidates at 8,256
intersection calls and 512 distinct candidates at 131,328 calls; 129 and 513
overflow cases perform zero intersection calls. Geometry/evidence indexes and
one-pass page rebuilding remove the prior document-quadratic paths.

## Performance and size

| Measure | Result |
|---|---:|
| Layout stage warmups / samples | 5 / 100 |
| p50 / p95 / max | 1.302 / 1.677 / 1.984 ms |
| Peak traced allocation | 88,477 bytes |
| Five-percent ceiling | 425 ms |
| Absolute stage gate | 50 ms |
| Catastrophe JSON delta | +3,997 bytes |
| Clinical JSON delta | +23,014 bytes |
| Finance JSON delta | 0 bytes |

Full-parser flag snapshots run in separate fresh processes, so converter/model
caches and process-lifetime RSS high-water marks are isolated per state. The
artifact records each wall time, processing duration, RSS high-water mark,
output size, and output hash. These single cold snapshots document both states;
the isolated 100-sample stage distribution is the acceptance measurement.

## Test gates and review

- Final story/contract/API/canonical/real/performance/custody gate:
  **62 passed**.
- Independent production/security gate: **124 passed, 1 documented opt-in
  skip**.
- Real benchmark gate: **5 passed**.
- Frontend Node 22.18: lint, typecheck, production build, **46 unit tests**, and
  **1 bundle test** passed.
- Python compilation, targeted independent lint, and dependency integrity:
  **Pass**.
- Existing warnings only: Starlette/httpx and upstream Docling deprecations.

Independent review found and closed raw/public bbox loss, generated/orphan
promotion, terminal relationship loss, duplicate/idempotence defects,
cross-owner conflicting text, order-dependent overlap chains, unbounded
same-text/page work, repeated geometry indexing, per-owner page rebuilding,
frontend affected-path coverage, cached timing/RSS comparisons, and
count-only artifact acceptance. Final production/security, performance,
frontend/API, and metrics/custody reviews all approved with no remaining Major.

The local services started and the production frontend build passed. The
session had no controllable browser, so no manual click-through is claimed.
The composed affected-path test instead binds physical p1/printed p7,
caption-specific canonical Markdown, normalized JSON, copy/Blob bytes,
explicit rendering, and flag-off absence. Manual UI is retained for a Phase 03
exit retry.

## Retained artifact

Machine-readable final-code, input, exact-identity, output-hash, relationship,
performance, RSS, size, policy, environment, and zero-cost evidence is retained
in
[P03-US01-table-caption-metrics.json](P03-US01-table-caption-metrics.json).

- Size: **15,548 bytes**
- SHA-256:
  `98ccfb93b352dee0d01b5d614b1b298816ff80d817f1363fe27f682906f2857a`
- Semantic SHA-256:
  `5c12918f141d042e258c3e99d79941b3d0261e7338529ec66d3057f76aee4305`

The artifact is atomically written, raw-SHA pinned by the retained gate, and
binds 19 final code/config/frontend/test files plus the exact path, size, and
SHA-256 of all three PDFs. No bound file drifted after generation.

## Rollback and unresolved scope

Set `PARSER_LAYOUT_TABLE_CAPTIONS_ENABLED=false`. This removes the projection
and returns exact predecessor JSON/Markdown while retaining raw evidence.

Visual captions/internal visual children, source notes/footnotes, generalized
relationship order, and styled run semantics remain explicit Phase 03 work.
The clinical Table 2 caption preserves the extractor-visible `( N = 538)`
flattening; italic `N` semantics belong to P03-US05.
