# Lighthouse Roadmap

This folder is the working roadmap for Lighthouse.

It is meant to be more than a task list. It keeps the project thesis,
milestones, current execution tracks, completed evidence, decisions, and open
ideas in one place so local discussion can turn into repeatable product
progress.

Repository-level Agent instructions live in [AGENTS.md](../../AGENTS.md). Agents
should read that file before changing roadmap or product-direction documents.

## Current focus

The active focus is Lighthouse Agent Board as the first milestone toward a
broader Human-Agent Workspace. The canonical P0 service is
`services/review-room-service`; older `review-room` paths remain compatibility
or legacy-reference names, but product and UI language should use Agent Board:

- MR review is the entry workflow, not the product boundary.
- The durable value is an auditable, assignable, observable, approval-gated
  collaboration control plane for humans and Agents.
- Workbench messages are preserved for owner/supervisor coordination and feed
  Agent Inbox, but executable work still flows through tasks, claims, and
  `agent_runs`.
- The P0 experiment should stay concrete enough to test with real activated
  Agents, while leaving room for other future board types such as legal review,
  incident response, release review, or product decision boards.

## Files

- [product-thesis.md](./product-thesis.md): north star, scope, and product
  boundaries.
- [milestones.md](./milestones.md): phased goals and acceptance criteria.
- [tracks/review-room-p0.md](./tracks/review-room-p0.md): current Lighthouse
  Agent Board experiment track.
- [tracks/connector-and-mcp.md](./tracks/connector-and-mcp.md): connector
  runtime, adapter, MCP, and bootstrap track.
- [tracks/observability-and-routing.md](./tracks/observability-and-routing.md):
  tasks, agent runs, handoffs, claims, and deliberation track.
- [tracks/safety-and-lifecycle.md](./tracks/safety-and-lifecycle.md): trust
  boundaries, capabilities, decisions, revocation, and remote residue track.
- [tracks/lighthouse-productization.md](./tracks/lighthouse-productization.md):
  Lighthouse Console, backend, integrations, and workflow expansion track.
- [decisions.md](./decisions.md): accepted working decisions.
- [done.md](./done.md): completed work and evidence.
- [ideas-inbox.md](./ideas-inbox.md): useful ideas that are not yet committed
  to a milestone.
- [review-room-remote-mcp-debugging-2026-06-13-14.md](./review-room-remote-mcp-debugging-2026-06-13-14.md):
  remote MCP debugging trail, bugs, fixes, smoke tests, and carry-forward notes.

## Status language

Use these statuses consistently:

- `Done`: shipped in repo or deployed, with evidence.
- `Verified`: tested in the intended environment, with evidence.
- `In progress`: implementation or design is active.
- `Planned`: accepted direction, not started.
- `Open question`: still needs product or technical validation.
- `Parked`: useful, but not relevant to the current milestone.

## Maintenance loop

1. Capture new local discussion in [ideas-inbox.md](./ideas-inbox.md).
2. Promote an idea into a track only when it has a clear user value, owner,
   acceptance criteria, and next action.
3. Promote a track item into [milestones.md](./milestones.md) only when it is
   needed for the next product proof.
4. Move finished work into [done.md](./done.md) with links to code, docs, tests,
   deployment notes, or real scenario results.
5. Record durable product or architecture calls in [decisions.md](./decisions.md)
   so we do not re-litigate them in every thread.

## Evidence rule

A roadmap item is only `Done` when there is a link to evidence. Evidence can be:

- code or tests in this repo,
- a concept doc that defines the accepted design,
- a deployed service health check or smoke test result,
- a real remote-Agent scenario transcript or result,
- a decision record approved by the owner.

If the code exists but has not been tested in the target environment, mark it
`Done in local P0` or `Needs remote verification` instead of calling it fully
verified.
