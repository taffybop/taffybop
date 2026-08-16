# P03-US08 Hardened Phase 04 Renewal Independent Review 03

Status: Blocked; superseded by remediation and requires fresh review  
Review date: 2026-08-04  
Scope: Final pre-implementation production/security review of the narrow Phase 04 tables renewal

## Reviewed bundle

- Decision: 23,229 bytes, raw SHA-256
  `60310ce94111030f818da36a8373c6c20c270e624aae8d285898253adbcab816`.
- Machine-readable renewal: 20,439 bytes, raw SHA-256
  `f4cb26489e701e21337f20119e52b6ff26bcb059bbb953b18fd45f3d5cb7e6b8`,
  semantic SHA-256
  `f507aa0026ac6a552bf36e248f983b41d762e535d9fac71ccbd5bf1916b0a94d`.
- Executable guard: 290,781 bytes, raw SHA-256
  `775768d9076b4c1a3c54b4cd9fc574299ea17c5b6d7150c8638d4ae0a0065534`.
- Guard tests: 160,959 bytes, raw SHA-256
  `72c66d03ad6acff7d16298c5b6865e0c5f1791e7c1ea5bf060560213893e2e92`.
- Implementation verification: 6,957 bytes, raw SHA-256
  `1fde128cd45d83377f7b167f5aafc242288da77f154273181613626c92236807`.

The complete pre-review guard passed 310 tests with one pre-existing
Starlette/httpx deprecation warning. Passing tests did not override the
independent findings below.

## Blocking findings

### IR03-FE-01 - indexed callback provenance escape

Severity: Major / security  
Disposition at review: Blocking

The frontend scanner accepted an unknown callback after it was placed in a
collection and invoked by numeric index. Both
`const callbacks = [item.callback]; callbacks[0](item)` and
`const callbacks = Object.values(item); callbacks[0](item)` were accepted.
This contradicted the closed no-unknown-callback contract and was the same
capability class as already rejected direct borrowed callbacks.

Required remediation was a common fail-closed rule for indexed invocation,
indexed or nested method dispatch, aliases, destructuring overwrites, and
callable-parameter shadowing while retaining proven owned callbacks and normal
React mapping.

### IR03-SEM-01 - span-only later-story semantic escape

Severity: Major / correctness and dependency order  
Disposition at review: Blocking

The table-semantics scanner accepted unconditional selection mutation inside
`reconcile_table_candidates` when span fidelity was enabled and evidence
reconciliation was false. Inserting
`merged["selected_candidate"] = True` before the terminal output gate was
accepted and returned the marker at runtime. This contradicted the frozen
contract that P04-US01 span-only execution may preserve evidence but must not
run P04-US02 selection, scoring, or discard behavior.

Required remediation was an exact false-reconciliation branch immediately
after validated owned copies and before any story body, containing only the
canonical/plain output gates and `return merged`.

## Review decision

**BLOCKED.** The reviewer granted no production/security approval. The
requester-authorized renewal, attempt-48 facts, non-waived gates, and Phase 05
boundary remained unchanged, but Phase 04 production work could not start on
this bundle.

## Remediation checkpoint

Both findings were subsequently addressed in:

- executable guard: 293,020 bytes, raw SHA-256
  `793fd0ccd3958f0e447aa86a18a46790fab070f0b41ede15d56d1a140a21ce3b`;
  and
- guard tests: 164,435 bytes, raw SHA-256
  `429f183a68d6836727801d4aabf668d25db9c8d1724056f44fbefb6e0d7e8c6e`.

The amended guard passed 323 tests with one pre-existing warning and Python
compilation. This remediation checkpoint is not self-approval; the amended
bundle requires a new independent review.
