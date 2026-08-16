# Phase Boundary and Clean-Chat Handoff

Status: Accepted  
Date: 2026-07-30  
Supersedes: `2026-07-29-autonomous-execution-boundary.md` only where the
authorization boundary differs

## Context

The requester reaffirmed autonomous sequential execution within the active
phase and replaced the earlier remaining-phases interpretation with an explicit
phase boundary:

- complete every dependency-ready story in the active phase, one In Progress
  story at a time;
- complete independent reviews, retained evidence, metrics, regressions,
  tracker reconciliation, and the phase exit gate;
- stop before starting the next phase and request explicit confirmation;
- after confirmation, apply the same method through Phase 08.

The requester also prefers a fresh chat at each phase boundary to avoid an
unnecessarily long conversation context.

## Decision

Phase 02 is authorized through its complete exit gate. No Phase 03 story may be
implemented or marked In Progress until the requester explicitly confirms
after reviewing the Phase 02 exit report.

At each phase boundary, retain a durable workspace checkpoint and provide a
copy/paste kickoff prompt for the next phase. The requester can then start a
new Codex chat (or use the product's new-chat control) and resume from the
workspace rather than relying on conversation memory.

This decision changes the authorization boundary only. It does not waive any
Definition-of-Ready, Definition-of-Done, dependency, compatibility, security,
performance, evidence, review, regression, or rollback gate.

## Rollback

If the requester chooses to continue in the same chat, use the retained
workspace checkpoint as the source of truth. If authorization is narrowed,
stop before the first excluded phase and preserve all completed evidence.
