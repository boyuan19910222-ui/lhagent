# Review Room Protocol

## Purpose

Review Room needs a stable protocol before it can grow from a single-process prototype into a Lighthouse control plane for multi-Agent collaboration.

The protocol should make one thing explicit:

```text
Messages are conversation.
Tasks are executable work.
Findings are review output.
Decisions are human or policy checkpoints.
Agent runs are execution evidence.
```

This avoids the most dangerous failure mode for a multi-Agent room: treating every chat message as an implicit instruction for every connected Agent.

## Current P0 boundary

The current prototype already has useful primitives:

- `Room` as the collaboration state source.
- `Message` as the timeline item.
- `Finding` as structured review output.
- `Connector` as the Agent identity.
- `Invite` as the initial access path.
- Token-authenticated HTTP and WebSocket events.
- Owner confirmation before MR sync preview.

The current protocol is still intentionally small. It mostly handles `message.create`, `finding.create`, `finding.respond`, and owner confirmation. Productization should add typed task, run, handoff, artifact, and decision objects instead of overloading messages.

## Protocol principles

- The Room is the source of truth for collaboration state.
- The Connector is the execution boundary, not a trusted owner surrogate.
- The Agent Adapter is replaceable; Codex is one adapter, not the protocol.
- Normal chat is broadcast and non-executable by default.
- Executable work requires a structured task and server-side routing.
- External side effects require explicit decision records and human or policy confirmation.
- Every Agent execution should produce an `agent_run` record.
- Every high-risk action should be auditable, cancellable, and attributable.

## Identity model

| Identity | Purpose | Typical capabilities |
| --- | --- | --- |
| owner | Room controller and final decision maker | `room:manage`, `task:create`, `task:assign`, `finding:confirm`, `member:disconnect` |
| guest | External participant | `room:read`, `message:create` |
| connector | Agent-side bridge | Depends on role and capability |
| system | Review Room service or trusted adapter | State transitions, webhook ingestion, sync preview |

Connector identity should include:

```json
{
  "connectorId": "connector_123",
  "name": "Reviewer Agent",
  "role": "reviewer",
  "adapterType": "codex",
  "capabilities": ["room:read", "message:reply", "finding:create"],
  "protocolVersion": "review-room.v1"
}
```

## Core objects

### Room

Room stores collaboration state and access scope.

Key fields:

- `id`
- `title`
- `provider`
- `mrUrl`
- `context`
- `status`
- `participants`
- `connectors`
- `createdAt`
- `updatedAt`

### Message

Message is conversational and should not trigger execution by default.

Key fields:

- `id`
- `roomId`
- `senderType`
- `senderName`
- `kind`
- `body`
- `payload`
- `createdAt`

### Task

Task is executable work. This is the main missing protocol object.

Key fields:

```json
{
  "id": "task_123",
  "roomId": "room_123",
  "kind": "review|fix|verify|research|custom",
  "status": "open|claimed|assigned|running|completed|failed|cancelled|stale",
  "instruction": "Review the MR for permission boundary risks.",
  "target": {
    "mode": "connector|role|capability|claim",
    "connectorId": "connector_reviewer",
    "role": "reviewer",
    "capability": "finding:create"
  },
  "source": {
    "messageId": "msg_123",
    "findingId": "",
    "artifactId": ""
  },
  "createdBy": "review room owner",
  "assignedConnectorId": "connector_reviewer",
  "leaseExpiresAt": 0,
  "createdAt": 0,
  "updatedAt": 0
}
```

### Finding

Finding is structured review output.

Key fields:

- `id`
- `roomId`
- `severity`
- `status`
- `filePath`
- `line`
- `claim`
- `evidence`
- `suggestedFix`
- `createdBy`

### Handoff

Handoff lets one Agent propose that another Agent, role, or capability should take over a piece of work.

Key fields:

```json
{
  "id": "handoff_123",
  "roomId": "room_123",
  "fromConnectorId": "connector_reviewer",
  "target": {
    "role": "developer",
    "capability": "finding:respond"
  },
  "sourceFindingId": "finding_123",
  "reason": "The finding needs a code fix and regression test.",
  "suggestedTask": "Fix this finding and report verification results.",
  "status": "proposed|accepted|rejected|converted_to_task"
}
```

### Agent run

Agent run is the execution trace for an assigned task.

Key fields:

- `id`
- `roomId`
- `taskId`
- `connectorId`
- `adapterType`
- `externalSessionId`
- `status`
- `promptSummary`
- `workspace`
- `model`
- `sandbox`
- `startedAt`
- `finishedAt`
- `finalMessage`
- `error`
- `logPath`
- `transcriptUrl`

### Thread

Thread is a scoped discussion, not general chat.

Use it when multiple Agents need to deliberate around a finding, task, or artifact.

Key fields:

- `id`
- `roomId`
- `kind`
- `sourceFindingId`
- `sourceTaskId`
- `participants`
- `question`
- `maxTurns`
- `status`
- `summary`

### Artifact

Artifact is a durable file, patch, test result, screenshot, log, report, or diff.

Key fields:

- `id`
- `roomId`
- `kind`
- `title`
- `mimeType`
- `uri`
- `contentHash`
- `createdBy`
- `createdAt`

### Decision

Decision records human or policy confirmation before an external side effect.

Key fields:

- `id`
- `roomId`
- `kind`
- `targetType`
- `targetId`
- `decision`
- `decidedBy`
- `reason`
- `createdAt`

## Event envelope

All realtime events should share a consistent envelope:

```json
{
  "type": "task.assigned",
  "id": "evt_123",
  "roomId": "room_123",
  "actor": {
    "type": "owner|guest|connector|system",
    "id": "connector_123",
    "name": "Reviewer Agent"
  },
  "payload": {},
  "createdAt": 0,
  "protocolVersion": "review-room.v1"
}
```

## Minimum event set

Conversation:

- `message.create`
- `message.created`

Task lifecycle:

- `task.create`
- `task.created`
- `task.claim`
- `task.assigned`
- `task.started`
- `task.completed`
- `task.failed`
- `task.cancelled`
- `task.stale`

Finding lifecycle:

- `finding.create`
- `finding.created`
- `finding.respond`
- `finding.updated`
- `finding.confirm`
- `finding.reject`

Handoff:

- `handoff.propose`
- `handoff.accepted`
- `handoff.rejected`
- `handoff.converted_to_task`

Agent run:

- `agent_run.created`
- `agent_run.started`
- `agent_run.stream`
- `agent_run.completed`
- `agent_run.failed`

Thread:

- `thread.create`
- `thread.message.create`
- `thread.summary`
- `thread.closed`

The P0 service currently persists scoped thread records and thread messages, broadcasts thread creation/message/summary events, and includes threads in room snapshots. A summary with `needs_owner_decision` marks the room for owner action; it does not automatically create executable work.

Room management:

- `presence.updated`
- `member.disconnected`
- `room.disconnected`
- `room.snapshot`

## Routing rules

An Agent should execute only when all of these are true:

- The event is a task assignment, not a normal chat message.
- The task is assigned to the connector, or the connector successfully claimed it.
- The task matches the connector role and capabilities.
- The task is within lease and not cancelled.
- The connector runtime independently validates the assignment before invoking the adapter.

Natural-language mentions such as `@Reviewer` may help the UI create a task, but they should not be execution authority.

## Lease and timeout

Tasks need leases so that a disconnected or stuck Agent does not hold work forever.

Recommended lifecycle:

```text
open -> claimed -> assigned -> running -> completed
                               -> failed
                               -> stale -> reassign|cancel
```

Rules:

- A lease is granted when a task is assigned.
- The connector must heartbeat while running.
- Missing heartbeat moves the task to `stale`.
- Owner or policy may reassign, cancel, or retry stale tasks.

## Productization order

1. Add `agent_runs` for visible execution state.
2. Add `task.create` targeted by `connectorId`.
3. Emit `task.assigned` and require connector-side assignment checks.
4. Add connector capabilities and server-side enforcement.
5. Add role/capability routing and `task.claim`.
6. Add `handoff.propose`.
7. Add scoped `agent_deliberation` threads. P0 now persists bounded, participant-scoped deliberation and summaries.
8. Add artifacts and decisions around external sync.
