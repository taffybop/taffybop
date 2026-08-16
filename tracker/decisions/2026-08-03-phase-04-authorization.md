# Phase 04 Authorization

Status: Accepted  
Date: 2026-08-03  
Authorized phase: Phase 04 — Tables

## Context

Phase 03 is recorded complete at 8/8 stories and 38/38 points under the active,
time-bounded P03-US08 frontend-bbox latency-exception renewal. The accepted
phase-boundary decision requires separate requester confirmation before any
Phase 04 status transition or implementation begins.

After reviewing Phase 03 outputs and performing additional manual report
validation, the requester asked in the active Codex thread:

> can we proceed to next phase?

In this phase-boundary context, `next phase` unambiguously means Phase 04 —
Tables.

## Decision

Phase 04 is authorized through its complete exit gate, subject to all existing
Definition-of-Ready, Definition-of-Done, dependency, compatibility, security,
performance, evidence, review, regression, rollback, and mandatory-stop gates.
Execute one dependency-ready Phase 04 story at a time in canonical order:

1. P04-US01 — Preserve explicit table cells and span fidelity;
2. P04-US02 — Reconcile Docling and vector table evidence;
3. P04-US04 — Gate table candidates and reject visual impostors; and
4. P04-US03 — Handle continued and multi-page tables safely.

This authorization opens Phase 04 readiness work. It does not by itself make
P04-US01 Ready or In Progress: its 10/10 Definition-of-Ready record, fixtures,
oracle, contracts, tests, rollback, and measurement boundaries must be complete
before implementation starts. P04-US02, P04-US04, and P04-US03 remain Proposed
until their dependency and readiness gates are reached.

## Preserved boundaries

- This decision authorizes Phase 04 only and stops before Phase 05.
- It grants no production promotion or hosted-model use.
- It grants no new waiver and does not broaden the P03-US08 latency exception.
- The active P03-US08 renewal still expires on any further path in its locked
  required-code set changing, production enablement of running regions, Phase
  04 exit, or its 2026-09-02 review boundary. Required-code implementation must
  not begin until that custody/recertification consequence is resolved through
  strict current-code evidence or another exact, explicitly approved decision.
- The settlement `a.`/`b.`/`c.` marker-paint defect remains a separate Phase 03
  frontend follow-up; Phase 04 must not silently absorb it or reinterpret the
  already-correct backend hierarchy and clause-`b.` table ownership.

## Rollback

If authorization is narrowed or revoked before P04-US01 implementation, leave
all Phase 04 stories Proposed and retain only the readiness evidence already
created. If revoked after work begins, stop before the next mutation, preserve
completed in-scope evidence, and use the story feature flag for rollback.
