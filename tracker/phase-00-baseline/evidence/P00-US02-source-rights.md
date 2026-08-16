# P00-US02 Source-Use Decision

Decision date: 2026-07-28  
Decision status: Approved for P00-US02  
Approver: Workspace requester and artifact provider  
Expiry: None stated

## Decision

The requester confirmed in the active Phase 0 conversation that the catastrophe
files are public and redistributable. For P00-US02, that approval applies only
to this immutable artifact triplet:

| Artifact | SHA-256 |
|---|---|
| `benchmark-expertmodeldata/catastrophe-recap.pdf` | `d4d365e06715c4bf9b9ab2159caf79c1ef827234b3bf0b586357e3601795b87e` |
| `benchmark-expertmodeldata/catastrophe-recap.md` | `5104172e1d81eed0a001efaec7bec6f05d32a95f58dc169aacdc5842082069e8` |
| `benchmark-expertmodeldata/catastrophe-recap.json` | `cf0e1b11bd4e44b9ac20725e2bdf51a8301ea9bde173bbf1224c1280511381db` |

These exact artifacts and source-reviewed annotations derived from them may be
retained in the workspace, committed to a repository, redistributed with the
benchmark, and used in local, private-CI, and committed-CI validation.

## Boundaries

- This is the requester's source-use attestation; no independent license review
  or named license was supplied.
- The decision does not authorize mutation of the three source/expert artifacts.
- The requester's statement that “almost all” other files are public and
  redistributable is not treated as an all-corpus decision. P00-US04 must
  identify any exceptions before approving all 15 cases for committed CI.
- This decision authorizes benchmark/test metadata only and does not authorize
  production parser changes, hosted processing, dependency changes, or Phase 1.

## Consumers and rollback

Affected consumers are the P00-US02 truth fixture, its dedicated tests, and
later Phase 0 benchmark tooling that reads this fixture. Rollback removes only
the registration and derived annotations; it does not delete or modify the
approved source/expert artifacts.
