# P03-US08 Hardened Phase 04 Tables Renewal — Independent Review 14 (Blocked)

Status: **BLOCKED — no approval granted**  
Reviewed: 2026-08-04  
Scope: Fresh scope, compatibility, and resource pre-seal after review 13 remediation

## Candidate identification

- executable custody guard: **388,884 bytes**, raw SHA-256
  `0b9c03cf87af1c1a5a4c1c1f4d29c09b32af279911bbd51496fd235fc237c8ff`;
- focused guard tests: **200,515 bytes**, raw SHA-256
  `4729838f92a5efb859839f972fb5839ce8c78902a9f44b5583dde1d6ae11c3a4`.

The scope/security and compatibility reviewers returned clean pre-seal
verdicts on these exact bytes. The independent resource finding below blocks
the bundle and cannot be overridden by those clean component verdicts.

## Blocking finding

**IR14-RESOURCE-01 — overlapping JSX lookahead.** Each JSX opening-tag scan
was individually limited to 4,096 characters, but total lookahead work across
the source was not bounded. The scanner also allowed another raw `<` at brace
depth zero inside the same opening tag. Repeated `<table =` prefixes could
therefore share one final self-closing slash, evade the unique-slash cap, and
trigger overlapping scans with quadratic work.

The accepted reviewer input was equivalent to:

```python
"return " + ("<table =" * tags) + "/>;"
```

Measured 100/200/400-tag inputs took approximately
0.005921/0.023594/0.091089 seconds. Repeating a 3,602-byte block 1/2/4/8 times
took approximately 0.114742/0.225886/0.451199/0.977548 seconds. The
two-megabyte source ceiling therefore did not provide a proportionate
lookahead-work bound.

## Execution evidence

- Scope/security suite: **153 passed, 1** documented warning; the IR13
  TypeScript bypass and all prior scope probes were closed.
- Compatibility/boundary suites were clean, including **15** valid JSX/helper
  controls, **49** broader compatibility controls, **228** boundary controls,
  and the exact fact/custody slices.
- Resource/lexer subset: **115 passed, 460 deselected, 1** documented warning;
  45 prior resource probes and 11 other JSX boundary/malformed probes passed.
- The overlapping-lookahead reproducer remained accepted. Reviewers edited no
  files.

Attempt 48 remained failed at **0.050946750 seconds** against the unchanged
**0.050000000-second** ceiling (**0.000946750 seconds / 1.8935%**, maximum
**5%** candidate-specific). Canonical strict-final evidence remained absent,
the companion remained quarantined, and the 55-artifact failed-history
manifest remained
`bca401f2207619ba84422e020104b9a609e0be0f4dc2b42f3ae4fb53d315ceff`.
Every non-waived gate remained unchanged. No production, configuration,
runtime, story-status, or Phase 05 change occurred.

## Required disposition

This review grants no approval and must never be reclassified. Remediation
must reject a raw `<` at brace depth zero inside an opening tag, cap cumulative
opening/closing JSX lookahead steps, count all proven opening tags rather than
unique slash positions, retain matching-tag closure, add permanent aggregate
lookahead regressions, rerun the complete gates, reseal identities, and obtain
a fresh independent review.
