# Historical Baseline Verification After Phase 0

Status: Accepted  
Date: 2026-07-29

## Problem

The retained P00-US10 verifier correctly binds each immutable run to the exact
application and runner source used to create it. Its regression wrapper also
required those historical source hashes to equal the live workspace forever.
That second requirement makes any authorized production or benchmark-tool
change after Phase 0 fail by construction.

## Decision

Retained Phase 0 runs remain byte- and hash-immutable. Read-only verification:

1. validates the recorded historical environment and its self-hash;
2. validates every retained run, case, output, report, and tree identity;
3. validates all frozen corpus, reviewed-claim, and control inputs against the
   current workspace;
4. deterministically rebuilds the report using the run's recorded historical
   environment;
5. separately enforces the live OpenAPI, ParseResult, ErrorResponse, flag-off
   output, and dependency-isolation compatibility gates.

The live application and runner source hashes may advance in later authorized
phases. They are never rewritten into or compared as equality with the Phase 0
run record. Read-only verification also uses the run's recorded settings and
environment, so report reproduction does not require the current host to load
the historical engines or retain fixed settings that later phases legitimately
extend.

## Safety

This does not relax an output, truth, schema, artifact, or retained-evidence
identity. It separates historical provenance from live compatibility, which
are distinct assertions.

## Rollback

Revert this verifier behavior only in a frozen Phase 0 checkout whose live
source is intentionally identical to the recorded source. Later-phase
checkouts must retain the historical/live distinction.
