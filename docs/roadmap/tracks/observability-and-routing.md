# Track: Observability And Routing

Status: `In progress`

## Purpose

Make Agent work visible, assignable, and auditable.

Core concept docs:

- [Review Room Protocol](../../concepts/review-room-protocol.md)
- [Review Room Agent Collaboration](../../concepts/review-room-agent-collaboration.md)

## Product rule

Normal chat does not trigger execution. Executable work flows through explicit
room state:

- `task.create`
- `task.assigned`
- `task.claim`
- `agent_run.started`
- `task.completed`
- `handoff.propose`
- `thread.summary`
- owner decision records

## What the owner should see

- Who owns a task.
- Whether an Agent has started.
- Whether the Agent is still running, stale, completed, failed, cancelled, or
  revoked.
- What prompt or task summary was used.
- Which connector, adapter, model, workspace, sandbox, and transcript/log path
  were involved when available.
- Which finding, handoff, decision, or external sync action came from the run.

## Current next actions

- Ensure every run has a stable transcript or log pointer when the adapter can
  provide one.
- Add stale run detection and owner-visible recovery actions.
- Define cancellation behavior for active tasks and runs.
- Tighten UI copy around "working" versus "connected" versus "ready".
- Add manual scenario docs that show the full review -> fix -> verify loop.

## Acceptance criteria

- `agent_runs` is the canonical cross-Agent execution surface.
- Vendor-specific session visibility is useful but not required for trust.
- A connector cannot run an unassigned open task.
- Multiple eligible Agents cannot accidentally execute the same claimable task.
- Handoffs and deliberation summaries do not bypass owner or policy gates.

## Risks

- If work happens in background processes without room state, users will not
  trust it.
- If broadcast chat triggers execution, multiple Agents may race or duplicate
  work.
- If Agent deliberation happens outside the room, the audit trail loses the most
  important reasoning.

