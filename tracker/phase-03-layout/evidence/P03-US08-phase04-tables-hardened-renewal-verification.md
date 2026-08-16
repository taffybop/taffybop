# P03-US08 Hardened Phase 04 Tables Renewal Verification

Status: Executable renewal resealed and verified; fresh independent approval pending  
Recorded: 2026-08-04  
Scope: Narrow administrative P03-US08 renewal needed for unrelated, default-off Phase 04 table work

## Outcome

The decision, machine-readable renewal, executable custody guard, and complete
focused test file are internally consistent. This is implementation evidence,
not self-approval: Phase 04 production changes may rely on the renewal only
after a fresh independent reviewer approves the exact identities below.

The first fresh final review found two Major issues before approval: indexed
or aliased frontend callbacks could evade callable provenance, and the
span-only reconciliation path did not have an exact boundary preventing
later-story selection mutations. Both findings were fixed in the executable
guard, their supplied and adjacent reproducers are permanent negative
regressions, and the amended identities below supersede the pre-review guard
identities. The blocked review did not approve the earlier bundle.

The next fresh logic review found that a selection mutation could still be
inserted between the required reconciliation copies. The guard now freezes the
entire guard/deadline/three-copy/false-reconciliation opening as one ordered,
contiguous AST preamble. Selection, scoring, and discard probes after every
copy boundary are permanent negative regressions. That review also corrected
the span-disabled versus span-only return-identity wording below. Review 04
remains blocked history and did not approve its reviewed bundle.

The final holistic review then found that the frontend scanner omitted the
Phase 05 token boundary and still admitted opaque method receivers and local
callable cycles hidden in method callbacks. It also identified the decision's
span-only attachment wording as broader than the executable immutable-copy
contract. The decision now scopes retained candidates to upstream input; the
frontend guard rejects Phase 05 forms, opaque or rebound receivers, and typed
self/mutual callback recursion while preserving locally owned React/table
mapping. Review 05 remains blocked history and granted no approval.

The following fresh scope review then found that frontend static roots
`Object`, `JSON`, and `Array` could still be rebound, and that backend scope
scanning admitted additional Phase 05 and running-region identifier forms.
The shared boundary-aware scope normalizer now rejects camel, compact,
plural, separator, and case variants; static roots are trusted only for exact,
unshadowed reviewed calls. Assignment, parameter, destructuring, TypeScript
alias/cast, borrowed-method, and update variants are permanent negative
regressions. Review 06 remains blocked history and granted no approval.

The next three-way review found five further closure gaps: split string
expressions could reconstruct forbidden scope, forbidden compact terms could
remain embedded inside longer identifiers, named default parameters and
implicit coercion hooks could recurse outside the frontend call graph,
property-only global capability reads were admitted, and the legacy P03
repository-code assertion did not separately recognize the already-present
Phase 04 readiness test. The scanners now cover bounded reconstructed strings,
embedded identifiers, default-parameter call edges, coercion/serializer hooks,
and capability-root reads. The frozen P03 manifest remains exactly 86 paths;
an exact identity-bound administrative contract separately closes five Phase
04 paths and rejects any sixth path. Review 07 remains blocked history and
granted no approval.

Review 08 found backend dictionary/set, formatted-value, and simple-alias
reconstruction gaps, plus split frontend literal reconstruction. The static
scanners now cover bounded ordered container variants, exact formatted scalar
values and local constant bindings, and complete frontend literal
reconstruction. Review 08 is immutable blocked history and granted no
approval.

Review 09 found additional arithmetic formatting, static reorder/decode,
frontend index/slice, and converted numeric reconstruction paths. The guard
now uses bounded exact scalar arithmetic, byte and reorder handling, and
complete cross-literal numeric selection checks. Review 09 is immutable
blocked history and granted no approval.

Review 10 found admitted `strip`, `split`, `re.sub`, and Unicode-normalization
transformations; cross-literal selection; regex/comment ambiguity; and
post-allocation resource checks. The guard now scans normalized transform
results, uses a context-aware regex lexer, and preflights multiplication,
formatting, replacement, shifts, joins, and Cartesian products before
materialization. Review 10 is immutable blocked history and granted no
approval.

Review 11 found regex ambiguity after control heads, dynamic formatting
widths, frontend and backend construction before bounds, and use of
`ast.literal_eval`. The remediation recognizes control-head regex contexts,
rejects or projects dynamic widths, performs incremental source/literal/node
and result accounting, and uses AST-only literal validation. Review 11 is
immutable blocked history and granted no approval.

Review 12 found regex ambiguity after closing blocks, aggregate Cartesian
format/split/replacement and legacy-join allocation gaps, an AST-node-limit
fail-open, incomplete width projection, and quadratic slash scanning. The
remediation uses a linear lexer, exact 8,192-node fail-closed prepass, and
aggregate count/byte/width preflight for every admitted static operation.
Review 12 is immutable blocked history and granted no approval.

Review 13 found that the JSX-close exception could be abused by valid plain
TypeScript to hide a forbidden split literal. JSX handling is now disabled on
the `.ts` helper and the TSX branch accepts only exact matching allowlisted
opening, closing, and self-closing tags. Review 13 is immutable blocked
history and granted no approval.

Review 14 found quadratic overlapping JSX lookahead. The lexer now rejects a
raw `<` at brace depth zero inside an opening tag, counts every opening tag,
and charges every opening/closing lookahead character to one non-resetting
262,144-step per-call budget. Review 14 is immutable blocked history and
granted no approval.

The immutable failed-review history remains preserved:

- failed independent audit: **6,082 bytes**, raw SHA-256
  `4aa0f7e8c26e2f64775a5635d1b6a367045de960222e3fcbb3e57b56e2e48e9d`;
- blocked red-team review: **3,462 bytes**, raw SHA-256
  `4af6a45c8b2137b16629845cd1a02475b87ccde147057b017ed460394903784c`;
- blocked independent review 02: **2,416 bytes**, raw SHA-256
  `81b0dbb97f52814d574928045993f18ebb62a4b38ad6669e07b5bc4830ab1b7c`;
- blocked independent review 03: **3,474 bytes**, raw SHA-256
  `36802aca76f53182c92ee23462873c5409045d60264983cda3e7435a1bea8fff`;
  and
- blocked independent review 04: **3,916 bytes**, raw SHA-256
  `d24d75423a7912054f05108c8df65eb6aee0c92793eefc513b97715d66a20192`;
  and
- blocked independent review 05: **4,273 bytes**, raw SHA-256
  `a5efdc3489c87071c2effc50440f3344dfab0c4ade3d38505f3710e718202805`;
  and
- blocked independent review 06: **3,897 bytes**, raw SHA-256
  `91f20c5c84f42cd880d3912f18ed10f142027796b0896bac402e5f27ad3a5a28`;
  and
- blocked independent review 07: **4,751 bytes**, raw SHA-256
  `ec01f4a4bf4f8283ca90aebf301aaf8060d04f199b9b9c31a21ba1a051a01a06`;
  and
- blocked independent review 08: **4,802 bytes**, raw SHA-256
  `cf4551c6ff5c47d25c7a42e3d57285e43aa18fa838a90c9cbd4b8307b2879bfa`;
  and
- blocked independent review 09: **4,344 bytes**, raw SHA-256
  `1d9e3cbf6626b91a66cbd56c793c8abac652b17171bdb7358dd0d88ef0a0adf7`;
  and
- blocked independent review 10: **3,787 bytes**, raw SHA-256
  `ff97869c9582480f879a7ddf7113698c44626e13ecbca550f107402c22633aae`;
  and
- blocked independent review 11: **3,890 bytes**, raw SHA-256
  `d80c132673979f162fca90135816a810f1cacb488978abf53c009949a6580bd2`;
  and
- blocked independent review 12: **4,280 bytes**, raw SHA-256
  `c5ce59f91eae54ec05cd1580f824a62da6e5abfae8bbb97827043f23d059ff4e`;
  and
- blocked independent review 13: **2,936 bytes**, raw SHA-256
  `c75b5b1f4449ab1b5f7332bdc2881bfa7915fbd711501ee3dc07a19275f2fb5e`;
  and
- blocked independent review 14: **3,134 bytes**, raw SHA-256
  `d7469d732d9bdaa6450f666f53ae5f203e42b6f4b4330520bb991cf7ebdbb087`.

None was overwritten, reclassified, or treated as approval.

## Resealed identities

- Decision: **25,343 bytes**, raw SHA-256
  `bb3107b29f5a01876a64ee0179e1bff32b16bb93ecffa51da2f54c2d65510682`.
- Machine-readable renewal: **22,113 bytes**, raw SHA-256
  `5d0ac8411fd785eda1db1cbc01d2082ea09d65482ddba4796982cf0f60db4655`,
  semantic SHA-256
  `a8e38c8269e5faf1e03f5bff942dd97b74bea87f6ae26f9c6c175e50ed6eba87`.
- Executable custody guard
  `tests/fixtures/phase_03/running_regions/performance_exception.py`:
  **389,880 bytes**, raw SHA-256
  `d749ea7a0713dbd35d2323b54dda4b1652c1077d501601b04e9b30135230f2bd`.
- Focused guard tests
  `tests/performance/test_p03_us08_provisional_latency_exception.py`:
  **201,049 bytes**, raw SHA-256
  `51f69bf36583d687a4d870e76849d51f57581679f33cb0c33f1d97f46ca1d978`.
- Administrative P03 metrics/custody contract:
  **165,157 bytes**, raw SHA-256
  `3862f5d386f0bf4440da646d1cc7603dedb7f14cf694d275da49a6d9d0c97e75`;
  exact predecessor **162,944 bytes**, raw SHA-256
  `3604bf403b900970414ce8cc86d40bf806958cb0b1cb2d17e776ee404c2b408e`.
- Required pre-implementation Phase 04 frontend readiness test:
  **2,156 bytes**, raw SHA-256
  `ffc15e1ed0511b20a34bdead5342345b521f25e644b705806e2d9060a7d1f817`.

## Preserved exception facts

Attempt 48 remains failed for `ny-timetable`,
`running_region_projection`, `latency_p95_seconds`: observed
**0.050946750 seconds** against the unchanged **0.050000000-second** strict
ceiling, an overrun of **0.000946750 seconds / 1.8935%**. The maximum
candidate-specific authorization remains **5%**. This does not establish a
strict current-artifact metrics pass; the canonical strict-final artifact
remains absent and the companion remains quarantined.

The failed history remains sealed at 55 artifacts with manifest SHA-256
`bca401f2207619ba84422e020104b9a609e0be0f4dc2b42f3ae4fb53d315ceff`.
The renewal preserves the unchanged RSS and allocation gates; paired-parser,
source-extraction, and Uber-projection latency gates; correctness and quality;
security; API/schema compatibility; dependency/input/fixture/code custody;
deadline and resource; output-size; rollback; and hosted-use gates.

The running-region flag and all four table flags remain false by default.
Disabling `PARSER_LAYOUT_RUNNING_REGIONS_ENABLED` performs zero P03-US08
work and returns the exact configured predecessor. The renewal is reviewable
no later than **2026-09-02** and expires before production enablement, any
relevant running-region semantic/runtime or custody change, admitted Phase 04
scope/path expansion, or hardened grammar/scanner relaxation.

## Closed Phase 04 allowance

The record admits only five Phase 04 paths added after the frozen P03 baseline
and eight existing paths under closed validation. It adds no Phase 05 path or
behavior and leaves the 86-path P03 manifest unchanged. In particular:

- `.env.example` is either its exact 4,696-byte predecessor or that predecessor
  plus the exact four-line, ordered, default-false table suffix.
- `app/services/config.py` is not an admitted path. `app/config.py` may add
  only four ordered `bool = False` settings, their exact dependency guards,
  and exact default-false environment bindings.
- `app/services/tables.py` is an atomic two-state AST surface: the frozen
  predecessor or the identity-bound four-node geometry candidate. Mixed
  states, inferred/fabricated cell geometry, malformed/non-finite boxes, and
  default-on extraction are rejected.
- `app/services/pipeline.py` retains five closed broad helper surfaces and
  one separately exact `_parse_loaded_document` vector-geometry try block.
  Exact flag forwarding, statement forms, call counts, call order, and
  positional provenance are enforced.
- The new backend semantics module is restricted to nine exact public
  functions, exact signatures, exact default-off guards, a single shared
  250 ms deadline per public operation, bounded/canonical JSON and SHA
  boundaries, cumulative candidate and output caps, owned plain-data copies,
  exact `RawTable`/mapping conversion, cycle/depth/node/string/container
  controls, and bounded non-amplifying loops.
- Reconciliation is span-owned: with span fidelity disabled it returns the
  exact original object without copying or work. With span fidelity enabled
  and evidence reconciliation disabled, it returns an owned, unchanged copy.
  This prevents a later-story flag from activating P04-US02 behavior during
  P04-US01.
- Source-alignment and text-reconciliation changes are limited to exact
  marker-gated replay hooks. Frontend changes are limited to the exact inert
  table-semantics helper, exact canonical delegation, and safe table-only JSX.
- The one administrative metrics/custody contract is accepted only at its
  exact predecessor or exact reviewed candidate identity. The candidate keeps
  `REQUIRED_CODE_PATHS` at 86, pins the readiness-test identity, separately
  enumerates exactly five Phase 04 table paths, and rejects a sixth.

The guard rejects aliases, borrowed mutable output, hostile mapping callbacks,
reflection, dynamic execution/import, CommonJS export escapes, project imports
other than the exact `RawTable` type, browser/network/storage/filesystem/
subprocess access, unsafe HTML, resource/event JSX, unbounded growth, nested
resource amplification, deadline reset, noncanonical serializer output,
running-region coupling, Phase 05 references, reconstructed forbidden strings,
embedded compact forbidden identifiers, default-parameter/coercion cycles,
and property-only process/browser/storage capability reads.

## Verification

Python compilation passed for the executable guard, focused tests,
administrative metrics/custody contract, and the Phase 04 table readiness
Python fixtures and story test.

The final complete focused command:

```text
.venv/bin/python -m pytest -q tests/performance/test_p03_us08_provisional_latency_exception.py
```

Result: **576 passed, 1 warning in 31.80 seconds**. The sole warning is the
pre-existing Starlette `httpx` deprecation warning from FastAPI test-client
import. No test was skipped or failed.

The complete non-waived P03 metrics/custody contract command also passed:

```text
.venv/bin/python -m pytest -q tests/performance/test_p03_us08_running_region_metrics_contract.py
```

Result: **122 passed, 1 expected retained-final skip, 1 warning in 22.15
seconds**. The skip is the already-documented absent canonical strict-final
artifact; the warning is the same Starlette/httpx deprecation.

Fresh pre-seal review on the exact identities above was clean in all three
independent lanes. Scope/security passed **154 tests, 1 warning in 1.18
seconds** and rejected the review-13 and review-14 reproducers. Resource and
non-execution passed **116 tests, 460 deselected, 1 warning in 1.94 seconds**,
plus 45/45 direct resource probes, exact boundary probes, and in-memory
compilation. Compatibility/boundary passed **15**, **49**, and **228** tests
in its three principal slices, plus the exact 5/5 fact and 5/5 custody slices;
each invocation reported only the documented warning. These are pre-seal
component verdicts, not the fresh final whole-bundle approval required below.

This administrative reseal changed no production parser, configuration,
frontend runtime, environment default, metrics implementation, frozen 86-path
manifest, benchmark observation, failed-history artifact, or Phase 05 record.
Its sole P03 contract change is the exact Phase 04 custody distinction above.
P04-US01 remains Ready and held; no Phase 04 story is In Progress. Hosted
requests, tokens, and cost were all zero.

## Independent-review requirement

A fresh reviewer must verify these exact identities, the immutable failed
reviews, requester attribution, attempt-48 values, maximum 5% bound,
default-off rollback, expiry, no-running-region-change claim, closed
Phase-04-only grammar, resource/deadline and output controls, frontend
capability closure, and every non-waived gate. Until that review records
approval, this renewal cannot authorize Phase 04 production changes.
