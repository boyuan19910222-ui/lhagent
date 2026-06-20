# Track: Safety And Lifecycle

Status: `In progress`

## Purpose

Keep the room useful without treating room content as trusted instructions or
pretending server-side revocation can clean another machine.

Core concept doc:

- [Lighthouse Agent Board Security](../../concepts/review-room-security.md)

## Safety rule

Room content is collaboration input, not trusted instruction.

Untrusted by default:

- guest messages,
- MR diffs,
- code comments,
- external comments,
- links,
- attachments,
- Agent output.

## Capability boundary

MCP invite identity should declare:

- role,
- adapter type (`mcp-remote` in the current product phase),
- protocol version,
- capabilities,
- forbidden actions,
- sandbox expectations,
- version,
- heartbeat or last seen status.

The service should enforce policy before MCP tools mutate Board state. The
Agent's native runtime remains responsible for its own execution safeguards.

## Owner approval boundary

External side effects require owner confirmation or a trusted policy adapter.

External side effects include:

- MR comment sync,
- IM messages,
- commit creation,
- push,
- merge,
- deploy,
- pipeline status changes,
- secret or credential access.

## Lifecycle boundary

Owner actions such as rotate token, disconnect, kick, or revoke invalidate server
access. They do not automatically clean residue on an Agent machine unless the
adapter explicitly implements remote cleanup.

Possible residue includes:

- room id,
- bearer token,
- MCP config,
- connector scripts,
- virtualenvs or dependencies,
- repo checkouts,
- shell history,
- stdout/stderr logs,
- Agent session transcripts,
- workspace changes,
- test artifacts,
- local caches.

## Current next actions

- Add an owner-facing cleanup checklist by adapter type.
- Label token rotation and disconnect as server-side invalidation, not remote
  cleanup.
- Make bearer-token handling guidance visible in bootstrap output.
- Keep `get_agent_briefing` and future context packs explicit about trusted
  policy/task data versus untrusted room, MR, code, link, attachment, and Agent
  output content.
- Add guardrails for obvious prompt injection and external side-effect requests.
- Bring `request_owner_confirmation` into the deployed MCP tool surface so
  external-effect requests can create first-class decision records instead of
  relying on visible conversation alone.

## Recent evidence

- [done.md](../done.md#agent-and-supervisor-room-exit-lifecycle)
  records remote preview/API smoke coverage for supervisor leave, Agent
  `leave_room`, owner revoke, audit events, and UI copy that states server-side
  invalidation does not clean remote MCP config, logs, shell history, caches,
  or workspaces.
- [services/review-room-service/README.md](../../../services/review-room-service/README.md)
  records the current MCP guidance that `get_agent_briefing` is read-only rule
  and state discovery, not execution authorization.
- [review-room-remote-mcp-debugging-2026-06-13-14.md](../review-room-remote-mcp-debugging-2026-06-13-14.md)
  records repeated stale-token failures from local scratch loops and preserves
  the rule that bearer tokens must not be committed to docs, scripts, or logs.
- [done.md](../done.md#real-remote-mcp-agent-board-inbox-and-messaging-scenario)
  records a real remote scenario where a Reviewer Agent treated an MR link as
  external content, waited for owner read-only approval, and did not execute
  task/run actions from chat alone.
- The MCP `encodingProbe` and `bodyUtf8Base64` path are now part of the remote
  Agent safety boundary for shell-sensitive non-ASCII text.

## Acceptance criteria

- Owner can understand what is revoked server-side.
- Owner can understand what may remain on the remote Agent machine.
- Agents receive context with trust labels.
- Connectors enforce local assignment and capability checks.
- Decision records exist before sync adapters publish external effects.
