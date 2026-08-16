# P03-US08 Hardened Phase 04 Renewal Independent Review 05

Status: Blocked; superseded by remediation and requires fresh review  
Review date: 2026-08-04  
Scope: Final holistic scope, provenance, resource, and documentation review

## Reviewed bundle

- Decision: 23,229 bytes, raw SHA-256
  `60310ce94111030f818da36a8373c6c20c270e624aae8d285898253adbcab816`.
- Machine-readable renewal: 20,439 bytes, raw SHA-256
  `f4cb26489e701e21337f20119e52b6ff26bcb059bbb953b18fd45f3d5cb7e6b8`,
  semantic SHA-256
  `f507aa0026ac6a552bf36e248f983b41d762e535d9fac71ccbd5bf1916b0a94d`.
- Executable guard: 293,275 bytes, raw SHA-256
  `e57fd60b10698dd057766b1c39d7e701db1eb25f92e1b36e8a50cb551f72204d`.
- Guard tests: 164,972 bytes, raw SHA-256
  `7bde01fa050c68ceac530519edafc4279409894354cf17f93923e7cec1dac613`.
- Implementation verification: 8,348 bytes, raw SHA-256
  `720e9729ef5902c601f56b410f4768cce56321262a367ce12b3959cdedfb48cd`.

The complete reviewed guard passed 325 tests with one pre-existing
Starlette/httpx warning. Passing tests did not override the findings below.

## Findings

### IR05-DOC-01 - span-only attachment overstatement

Severity: Moderate / correctness  
Disposition at review: Required correction and reseal

The identity-bound decision said span-enabled, reconciliation-disabled
`reconcile_table_candidates` could attach an alternative. The executable
six-statement preamble forbids mutation and returns an owned unchanged copy.
The statement was not clearly scoped to candidates already retained upstream.

### IR05-FE-01 - Phase 05 frontend scope gap

Severity: Major / phase boundary  
Disposition at review: Blocking

The backend and environment scanners rejected Phase 05 tokens, but the
frontend scanner did not use the same boundary. Valid helper bodies containing
`phase05`, `phase_05`, `P05`, or the string `Phase 05` were accepted,
contradicting the explicit prohibition on Phase 05 paths, status, and behavior.

### IR05-FE-02 - opaque receiver and callback-cycle gap

Severity: Major / correctness and resource safety  
Disposition at review: Blocking

The frontend scanner treated arbitrary parameters as valid method receivers,
so `item.map(String)` could dispatch an opaque input method. Its callable
graph recorded direct calls but not local functions supplied as method
callbacks, allowing self or mutual recursion through `.map` callback edges.
Both behaviors contradicted callable provenance and bounded-resource claims.

Required remediation was:

- boundary-aware rejection of Phase 05 identifiers and strings while retaining
  valid Phase 04 terms;
- method dispatch only on values proven locally owned or safely derived;
- rejection of opaque receiver and receiver-alias dispatch;
- callable graph edges for local method callbacks, including typed self and
  mutual recursion; and
- permanent negative regressions for element-return propagation,
  post-construction rebinding, callback aliases, and the supplied examples.

## Review decision

**BLOCKED.** No production/security approval was granted. A concurrent
metrics/custody approval could not override these correctness and phase-boundary
findings. Production remained at its frozen predecessor identities, P04-US01
remained Ready and held, later Phase 04 stories remained Proposed, and all ten
Phase 05 stories remained Proposed.

## Remediation checkpoint

The decision wording, frontend scope/provenance/call-graph guards, regressions,
and bound machine record were subsequently resealed. Final-code identities are:

- decision: 23,396 bytes, raw SHA-256
  `f3b02772501140e1ca6b7fbd865fc91733a7d39bbcfabb8770289ee580d27318`;
- machine-readable renewal: 20,439 bytes, raw SHA-256
  `5b8894f40c6082465b0f00f1b39aaba6ec496776ae4fd83ff33d92f15c0282e3`,
  semantic SHA-256
  `a63e635ead65ddff1a3aa49356393fabaefd687e53b6b8ae5ac063a2400894b6`;
- executable guard: 298,695 bytes, raw SHA-256
  `159cd91a25cdd273798eb5be73f73af7dfe329b8fe27cbbfcf84b61073a6d5c2`;
  and
- guard tests: 168,501 bytes, raw SHA-256
  `7df133ea544affd70c07317a9733d04a73fbd4935ef0a320b5a607c194374ae6`.

Python compilation passed and the fully resealed guard passed 339 tests with
one pre-existing warning. This checkpoint is not self-approval; the final
bundle requires a new independent review.
