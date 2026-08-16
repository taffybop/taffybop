# P01 Schema Evolution and Canonical Ownership Policy

Status: Accepted  
Date: 2026-07-29

## Decision

Phase 01 uses an internal versioned evidence/relationship IR and preserves the
public `1.0` response as the compatibility projection.

New public Phase 01 data, when explicitly enabled, must be:

- optional and additive;
- independently versioned;
- ignored safely by existing clients;
- derived from the canonical backend IR;
- absent from the default flag-off response;
- removable by disabling the narrow owning feature flag.

No existing endpoint, required field, field meaning, item ordering, legacy
Markdown fallback, or schema-version string may change in P01-US01 or
P01-US02. P01-US03 and P01-US04 may expose additive canonical presentation
blocks behind `parser.canonical_serialization.enabled`; the legacy projection
remains available and byte-compatible while the flag is off.

The backend owns canonical JSON evidence, Markdown, and semantic text.
Frontends render declared canonical blocks and may only use the documented
legacy fallback for older responses. They must not infer new document semantics
from evidence fields.

Any future breaking change requires a new public schema version, an explicit
migration and retirement policy, compatibility fixtures, and a separate
approved decision record.

## Rationale

This satisfies the Phase 01 entry criterion while minimizing consumer risk.
It also provides a reversible path to serialization parity without presenting
internal evidence records as stable public API prematurely.

## Rollback

Disable the Phase 01 feature flags. The unchanged public `1.0` projection and
legacy frontend fallback remain the operational path.
