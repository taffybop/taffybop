# P03-US08 Hardened Phase 04 Renewal Independent Review 04

Status: Blocked; superseded by remediation and requires fresh review  
Review date: 2026-08-04  
Scope: Amended renewal logic, dependency-order, and callable-closure review

## Reviewed bundle

- Decision: 23,229 bytes, raw SHA-256
  `60310ce94111030f818da36a8373c6c20c270e624aae8d285898253adbcab816`.
- Machine-readable renewal: 20,439 bytes, raw SHA-256
  `f4cb26489e701e21337f20119e52b6ff26bcb059bbb953b18fd45f3d5cb7e6b8`,
  semantic SHA-256
  `f507aa0026ac6a552bf36e248f983b41d762e535d9fac71ccbd5bf1916b0a94d`.
- Executable guard: 293,020 bytes, raw SHA-256
  `793fd0ccd3958f0e447aa86a18a46790fab070f0b41ede15d56d1a140a21ce3b`.
- Guard tests: 164,435 bytes, raw SHA-256
  `429f183a68d6836727801d4aabf668d25db9c8d1724056f44fbefb6e0d7e8c6e`.
- Implementation verification: 7,468 bytes, raw SHA-256
  `5049e4ffccf14235f1eaf6c398334e30e2b365c97d3578a43cf7590a2f90bcac`.
- Independent review 03 blocked record: 3,474 bytes, raw SHA-256
  `36802aca76f53182c92ee23462873c5409045d60264983cda3e7435a1bea8fff`.

## Blocking finding

### IR04-SEM-01 - interstitial reconciliation mutation

Severity: Major / correctness and dependency order  
Disposition at review: Blocking

The amended scanner required the false-reconciliation branch after the last
argument copy but checked the copy statements as a set rather than one exact
contiguous preamble. It therefore accepted a P04-US02 selection mutation
inserted after the `merged` copy and before the Docling/vector copies:

```python
merged = _copy_table_mapping(merged, deadline)
merged["selected_candidate"] = True
docling_tables = _copy_table_mapping(docling_tables, deadline)
```

At runtime with span fidelity enabled and evidence reconciliation disabled,
the result was detached but incorrectly contained the selected marker.

Required remediation was to freeze one exact ordered contiguous opening:
leading span guard, single shared deadline, `merged` copy, Docling copy,
vector copy, and exact false-reconciliation canonical/plain return branch.
Permanent negative probes were required after every copy boundary for
selection, scoring, and discard mutation.

## Documentation finding

### IR04-DOC-01 - span-disabled return identity

Severity: Moderate / correctness  
Disposition at review: Required correction

The implementation verification described span-disabled reconciliation as an
owned copy. The executable contract returns the exact original object without
copying when span fidelity is disabled. The owned unchanged deep copy applies
when span fidelity is enabled and evidence reconciliation is disabled.

## Review decision

**BLOCKED.** The concurrent metrics/custody review approved the reviewed
bundle's administrative facts, but that approval did not override this Major
logic finding and could not authorize Phase 04 production changes. Callback
remediation from review 03 was verified; no analogous inactive-stage
insertion gap was found in the exact leading guards for gating or continuation.

The review ran 64 targeted checks and the complete 323-test guard, with one
pre-existing Starlette/httpx warning; Python compilation passed. Production
surfaces remained at their frozen predecessor identities, P04-US01 remained
Ready and held, later Phase 04 stories remained Proposed, and every Phase 05
story remained Proposed.

## Remediation checkpoint

The exact contiguous preamble and documentation correction were subsequently
implemented. Final-code identities are:

- executable guard: 293,275 bytes, raw SHA-256
  `e57fd60b10698dd057766b1c39d7e701db1eb25f92e1b36e8a50cb551f72204d`;
  and
- guard tests: 164,972 bytes, raw SHA-256
  `7bde01fa050c68ceac530519edafc4279409894354cf17f93923e7cec1dac613`.

The amended guard passed 325 tests with one pre-existing warning and Python
compilation. This checkpoint is not self-approval; the final bundle requires a
new independent review.
