# P02 Numeric-Safe OCR Cleanup Policy

Status: Accepted  
Date: 2026-07-30  
Applies to: P02-US05

## Context and source truth

The legacy OCR cleanup treats any maximal sequence of two or more uppercase
`[A-F0-9]{2,}` fragments totaling at least 24 characters as a split
hexadecimal identifier. A retained catastrophe chart line contains twelve
decimal labels — `2015 2020 2025` repeated four times — and is therefore
silently rewritten as one 48-digit token. The P02-US05 story also names
`2010`–`2021`; that sequence remains a useful synthetic negative control, but
it is not substituted for the reviewed retained source.

OCR token evidence already preserves the twelve source words and bboxes. This
policy changes only cleaned line text; it never joins, deletes, or rewrites the
underlying token evidence.

## Eligibility

The numeric-safe path considers one maximal whitespace-delimited run only when:

- it has at least two and at most 64 fragments;
- every fragment matches the existing uppercase ASCII contract
  `[A-F0-9]{2,}`;
- the concatenated value is at most 128 characters and contains at least one
  `A`–`F`; a decimal-only run is never eligible, even after a hash label;
- the immediately preceding token, after removing only a trailing `:` or `=`,
  is an allowlisted identifier label; and
- the complete maximal run, not a convenient prefix, has the exact length
  declared by that label.

Exact labels and lengths are:

| Label | Required length |
|---|---:|
| `MD5` | 32 |
| `SHA1`, `SHA-1` | 40 |
| `SHA224`, `SHA-224` | 56 |
| `SHA256`, `SHA-256` | 64 |
| `SHA384`, `SHA-384` | 96 |
| `SHA512`, `SHA-512` | 128 |
| `HASH`, `CHECKSUM`, `DIGEST`, `FINGERPRINT` | one of 32, 40, 56, 64, 96, or 128 |

Label comparison is ASCII case-insensitive, but candidate fragments are not
case-folded or corrected. Bare known-length values, generic `ID`, account,
invoice, serial, distant-label, lowercase, Unicode-confusable, punctuated,
partial-length, and mixed ordinary alphanumeric sequences are not joined.

## Bounds and failure behavior

- At most 65,536 characters and 4,096 whitespace tokens are inspected per
  cleaned line.
- At most 64 candidate fragments and 128 candidate characters are accumulated.
- Traversal is linear and concatenation occurs once after eligibility passes.
- If a line or candidate exceeds a bound, the numeric-safe path returns the
  whitespace-normalized line without a hex join. It never truncates, falls back
  to the permissive legacy join, or partially mutates the run.
- Existing 8 MiB Tesseract TSV and 100,000-word bounds remain authoritative
  before cleanup.

## Compatibility, flag, and rollback

`parser.ocr.numeric_cleanup_v2.enabled` /
`PARSER_OCR_NUMERIC_CLEANUP_V2_ENABLED` is default off and has no dependency on
the Phase 02 font/reconciliation flags. It applies consistently to embedded
PDF images, rendered PDF regions, direct rasters, selective span OCR, and both
standard and sparse OCR passes.

Every new function argument defaults to false. Disabled callers omit the new
keyword at adapter and selective-render boundaries, preserving existing
monkeypatch/observer call shapes as well as exact legacy output. The original
permissive helper remains the flag-off implementation.

Disable the flag to restore the legacy cleanup exactly. This may restore the
known decimal false join; it does not change raw OCR token, bbox, confidence,
or diagnostic evidence.
