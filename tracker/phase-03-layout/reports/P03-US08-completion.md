# P03-US08 Completion Report

Status: Done — approved, active, time-bounded latency exception renewal  
Story: Separate running regions and printed page identity  
Points: 5  
Estimate history: re-estimated 3→5 at readiness  
Started: 2026-08-01  
Completed: 2026-08-03  
Exception renewed: 2026-08-03 — frontend bbox compatibility only  
Exception review due: 2026-09-02

## Definition of Ready

| Requirement | Result |
|---|---|
| Scope and non-scope explicit | Pass — physical/printed identity, running-region projection, Body/Full presentation, source custody, replay, frontend parity, rollback, resources, and metrics are bounded; renumbering, guessing absent pages, and evidence removal are excluded |
| Points at most 5 | Pass — 5; re-estimated from the historical 3-point plan after independent audits exposed the bounded source-authority, inverse-reconstruction, strict frontend, resource, and retained-metrics work |
| Dependencies Done | Pass — P01-US03 and P03-US04 are Done; the operational P03-US07 predecessor is also Done |
| Acceptance measurable | Pass — exact 30-page/27-visible-label/3-null, 47-region, 4-method-proof, role, repetition, canonical Body/Full, rollback, and performance denominators are specified |
| Dedicated tests identified | Pass — story, contract, real-corpus, performance/custody, frontend, integration, negative, fixture, phase, and prior-phase paths are identified |
| Fixtures available and authorized | Pass — exact source reports, sealed oracle, generated positive/non-target/adversarial fixtures, visibility controls, and source-projection authority controls are available and independently approved |
| API/frontend impact documented | Pass — strict additive public/IR/canonical contracts, physical-only navigation, bidi-isolated display, Body/Full control, and copy/download parity are specified |
| Feature flag identified | Pass — `PARSER_LAYOUT_RUNNING_REGIONS_ENABLED` / `parser.layout.running_regions.enabled`, default false with zero US08 flag-off work |
| Rollback defined | Pass — exact predecessor return, page/document atomic rollback, idempotence, and terminal strip/replay failure closure are specified |
| Quality/performance specified | Pass — exact/max+1 resource witnesses, closed deadline boundaries, reviewed quality denominators, paired final-code latency/RSS gates, custody, and zero hosted use are mandatory before Done |

Definition-of-Ready result: **10/10 Pass**, independently approved on
2026-08-01. The sealed readiness gate passed **25/25 checks**. At that
checkpoint P03-US08 was the sole In Progress story; no Phase 04 story had
started.

The accepted implementation contract is
[P03-running-regions-and-page-identity-policy.md](../decisions/P03-running-regions-and-page-identity-policy.md).

## Readiness evidence

- oracle semantic SHA-256:
  `ab7ce318bf390da82306c627ef1eee0352ded574245c4cdb901422e67bf26d7f`;
- synthetic registry semantic SHA-256:
  `55a086b4d8d56ea538435c96165fe5571964514ddaec2a4e6986ae89c248133c`;
- executable contract file SHA-256:
  `5b8e6cdb3641fef22ce9c02d5c9633751ec295ae9d16b8a3a26d7644034f3b6e`;
- generated synthetic file SHA-256:
  `f2a45566e3a7e64bf8caa819854dd9240c4a5e88a7a5ae260c09fe021f1746bb`;
- readiness test file SHA-256:
  `6f7859e4902c58a17f7eadcff85bba1072b752831962d2872ac2855861c63fe3`;
- source-truth correction:
  [P03-US08 Uber page-1 visibility addendum](../evidence/P03-US08-uber-page1-visibility-addendum.md);
  and
- independent review: source/projection, replay, visibility, resource,
  frontend, and metrics-contract blockers closed before promotion.

## Implementation and acceptance

The default-off local stage separates physical identity, embedded and detected
printed labels, display fallback, and accepted running regions without
renumbering source pages or discarding evidence. Projection requires the
factory-issued authority and exact source/predecessor bindings. The public,
IR, canonical, API, and frontend contracts remain strict and additive.

The reviewed corpus produces the accepted exact result:

- 30 reviewed pages with 27 source-visible printed labels and three explicit
  nulls, including Uber page 1's unchanged legacy display fallback;
- 47 accepted running regions: 16 headers, 30 footers, zero navigation-top,
  and one navigation-bottom, with 28 repeated regions in nine groups;
- canonical output of 223 Body, 16 header, 31 footer, and 270 Full blocks; and
- exact physical-page navigation, Body/Full selection, source/render/copy/
  download parity, byte-exact fused-owner reconstruction, rollback, and
  terminal replay behavior.

Negative, hostile, ownership-conflict, forged-authority, malformed-label,
visibility, exact/max+1 resource, and injected-deadline controls fail closed.
Flag off performs zero US08 import, extraction, projection, traversal, or
serialization work and returns the exact configured predecessor.

## Completion basis and strict disclosure

P03-US08 closes as **Done with an approved, time-bounded metrics exception**
under the active
[frontend bbox compatibility renewal](../decisions/P03-US08-frontend-bbox-latency-exception-renewal.md).
The original decision and executable waiver remain immutable historical
records in the renewal chain.
This is not a strict current-artifact pass, does not alter the v1 metrics
schema or its ceilings, and does not relabel any retained measurement.

The sole exception is the New York timetable projection p95 in immutable
attempt 48:

| Measurement | Result |
|---|---:|
| Observed projection p95 | 0.050946750 seconds |
| Strict ceiling | 0.050000000 seconds |
| Overrun | 0.000946750 seconds / 1.8935% |
| Candidate-specific authorization | at most 5% |

Attempt 48 remains an immutable `failed_measurement_candidate`. Its fail-fast
path correctly has no paired samples, so it is not used to claim whole-parser
or memory acceptance. A canonical strict-final artifact is absent.

The companion
[P03-US08-running-region-metrics-attempt-31-post-seal-invalid.json](../evidence/P03-US08-running-region-metrics-attempt-31-post-seal-invalid.json)
remains immutable and quarantined as post-seal-invalid. It completed all 20
paired workers and passed every strict gate, including paired latency and both
64 MiB RSS gates. Current code is not byte-identical to either retained
candidate: it differs from attempt 48 at exactly the authorized frontend
validator and frontend contract-test paths, while the other 84/86 required
paths—including every measured backend/parser runtime path—match. Current code
differs from the companion at exactly four paths: those two frontend paths plus
the companion's historical retained-artifact validator and contract test. The
renewal binds that exact chain; it does not promote the companion to canonical
final evidence.

All 29 `app/**` backend paths are identical to attempt 48, with manifest
`3f60c9b297760cf5fc0b1e89cd0ef02666f35c77ccc474202b80e26915703bb7`;
therefore `measured_backend_parser_runtime_paths_match_original` is true.

Peak RSS is **not waived**. Neither are correctness, quality, security,
API/schema compatibility, allocation, source-extraction latency, Uber
projection latency, paired-parser latency, resources, deadlines, output size,
code/dependency/input/fixture custody, rollback, or hosted use. Hosted
requests, tokens, and cost remain 0, 0, and $0.

Attempts 1–55 remain immutable failed history. Attempts 52–55 are part of the
sealed history ledger only and are not the basis for the exception; the
candidate-specific basis remains attempt 48. The failed-history manifest is
`bca401f2207619ba84422e020104b9a609e0be0f4dc2b42f3ae4fb53d315ceff`.
Attempts 54–55 came from campaigns already started by an older disconnected
Codex thread; that thread has ended. Their reconciliation changed only the
history seal and closeout records, not product/runtime bytes. The final guard
and full focused US08 gate below were rerun after the 55-attempt seal.

## Exception renewal identity, expiry, and rollback

The active decision is
[P03-US08-LATENCY-EXCEPTION-RENEWAL-20260803-FRONTEND-BBOX](../decisions/P03-US08-frontend-bbox-latency-exception-renewal.md),
and its executable record is
[P03-US08-frontend-bbox-latency-waiver-renewal.json](../evidence/P03-US08-frontend-bbox-latency-waiver-renewal.json).
They bind the current 86-path manifest
`b5bfab2739f231a57abddf787a6c566c5fddec5b2128bd4892f3682622a06fcc`
and the exact two-file frontend-only change.

The original immutable closeout records remain available as historical inputs
to that renewal chain:

- [P03-US08-provisional-latency-waiver.json](../evidence/P03-US08-provisional-latency-waiver.json):
  4,873 bytes; raw SHA-256
  `1fe75bc3d749730938653030052d463340eb2e856b810e0586e9afb12e9a72c8`;
- semantic SHA-256
  `0d3cd13942dd465c537dd7075baf0d2e8b30bc5dd891af55622c07f493610554`;
  and
- [P03-US08-provisional-latency-exception.md](../decisions/P03-US08-provisional-latency-exception.md):
  3,476 bytes; raw SHA-256
  `7bea63acad8403e442362edd8aabe0f4db084e6abd0cdd59e2b148b40a8b0d25`.

The renewal expires at the earliest of 2026-09-02, any further required-code
custody change, production enablement, or Phase 04 exit. It must be replaced by
a strict current-code final campaign or explicitly renewed. Expiry or
revocation returns P03-US08 to In Progress and blocks dependent exit claims.

`PARSER_LAYOUT_RUNNING_REGIONS_ENABLED` remains false by default. Setting it
to false prevents loading the running-region module, skips extraction and
projection, and returns the exact configured predecessor.

## Verification and UI evidence

- Active renewal waiver/custody guard: **28/28 passed**, with one pre-existing
  Starlette warning in **16.88 seconds**.
- Full focused US08 closeout rerun: **291 passed, 1 expected strict-final
  skip, 1 warning in 65.87 seconds**.
- Frontend Node **24.14.0** lint, typecheck, production build, **106/106 unit
  tests**, and **1/1 bundle test**: **Pass** after the compatibility correction.
- Responsive frontend verification: **22/22 Pass**.
- Zero hosted requests, tokens, and cost: **Pass**.

The focused warning belongs to that invocation and is not a waived product
failure. Automated frontend coverage proves contract validation, physical-only
navigation, bidi-isolated labels, Body/Full rendering, normalization, source,
copy/download, build, bundle, and responsive behavior.

Live browser verification now passes for `clinical-study.pdf`: the UI displays
all four physical pages, printed label `1/21` on the first selected page, and
22 canonical blocks, with working Body and Full views. The public-item bbox
compatibility path accepts `w`/`h` only when they exactly equal
`width`/`height`; the strict running-region bbox contract still rejects those
aliases.

Detailed evidence is in
[P03-US08-verification.md](../evidence/P03-US08-verification.md).

## Definition of Done

| Requirement | Result |
|---|---|
| Implementation and exact corpus acceptance complete | Pass — 30 pages, 27 visible labels, three nulls, 47 regions, and exact Body/Full counts |
| Dedicated, negative, resource, and rollback controls pass | Pass — focused coverage and strengthened waiver guard; final aggregate invocation recorded above |
| API/schema/canonical/frontend compatibility pass | Pass — strict additive contracts, physical-only navigation, Body/Full parity, build, bundle, and responsive checks |
| Strict ceilings remain authoritative | Pass — no schema, ceiling, or retained result changed |
| Exception scope is exact and approved | Pass — attempt-48 New York projection p95 only, 1.8935% overrun within the authorized 5% candidate bound |
| Non-waived gates have evidence | Pass — companion completed 20 paired workers and passed strict RSS/paired gates; all other exclusions remain enforced |
| Canonical strict-final disclosure is accurate | Pass — absent; attempt 48 remains failed and companion remains post-seal-invalid |
| Default-off rollback and expiry are executable | Pass — false by default; review due 2026-09-02 and any further required-code change, enablement, or Phase-04-exit expiry applies |
| Machine-readable custody and history are sealed | Pass — renewal binds the immutable original records, exact two-file frontend delta, current manifest, both candidates, and all 55 failed attempts |
| Live UI compatibility is verified | Pass — clinical study renders four pages, printed label `1/21`, 22 canonical blocks, and working Body/Full views |

Definition-of-Done result: **10/10 Pass under the approved active,
time-bounded latency exception**. P03-US08 completed on 2026-08-03. This is not
a strict current-artifact metrics pass, and no Phase 04 implementation is
claimed here.

## Hardened superseding renewal — 2026-08-03

The requester-authorized chain ends at
[`P03-US08-LATENCY-EXCEPTION-RENEWAL-20260803-PHASE04-TABLES-HARDENED`](../decisions/P03-US08-phase04-tables-latency-exception-hardened-renewal.md)
and its
[executable record](../evidence/P03-US08-phase04-tables-latency-waiver-hardened-renewal.json),
with final approval recorded in
[the independent approval](../evidence/P03-US08-phase04-tables-hardened-renewal-independent-approval.md).
The decision is **25,343 bytes**, raw SHA-256
`bb3107b29f5a01876a64ee0179e1bff32b16bb93ecffa51da2f54c2d65510682`;
the executable record is **22,113 bytes**, raw SHA-256
`5d0ac8411fd785eda1db1cbc01d2082ea09d65482ddba4796982cf0f60db4655`
and semantic SHA-256
`a8e38c8269e5faf1e03f5bff942dd97b74bea87f6ae26f9c6c175e50ed6eba87`.
The approval record is **5,573 bytes**, raw SHA-256
`a57f537c7636a5dc918e819f916ee4c9234af5bdee6b375fd1956bf1492e7715`.
They do not alter the immutable identities or claims above. The earlier
86-path manifest remains the renewal baseline, not a claim that admitted Phase
04 table files stay byte-identical.

Attempt 48 remains failed for `ny-timetable` /
`running_region_projection` p95 at **0.050946750 seconds** against the unchanged
**0.050000000-second** ceiling (**0.000946750 seconds / 1.8935%** over, within
the unchanged maximum **5%** candidate-specific bound). The companion remains
quarantined, the canonical strict-final artifact remains absent, and this
completion is not a strict current-artifact metrics pass. The new record admits
only its named, default-off Phase 04 table paths and protected functions;
changes structurally sealed inside that scope, and Phase 04 exit within it, no
longer activate the preceding blanket required-code/Phase-04-exit rule. A
protected running-region semantic/runtime/custody change or admitted-scope
expansion requires a new explicit decision and expires the renewal before the
change. Production enablement remains prohibited and review is due no later
than **2026-09-02**. Default-off exact-predecessor rollback and every non-waived
RSS, paired/source/Uber latency, correctness, security, compatibility, custody,
resource/deadline, output, rollback, and hosted-use gate remain in force.
