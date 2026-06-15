# Track: Connector And MCP

Status: `In progress`

## Purpose

Make Lighthouse Agent Board usable by different Agents without forcing every Agent host to
install the current Codex-specific sidecar.

Core concept doc:

- [Lighthouse Agent Board Connector Architecture](../../concepts/review-room-connector-architecture.md)

## Target shape

Connector integration should split into:

- Agent Board connector protocol,
- generic connector runtime or sidecar,
- adapter-specific implementation.

Candidate adapters:

- `mcp-remote`
- `codex-sidecar`
- `cli`
- `http-webhook`
- `a2a`
- `vendor-api`

## Working decisions

- `codex_connector.py` is a compatibility adapter, not the universal connector
  contract.
- Connector registration creates Agent Board identity and credentials. It does
  not install or start anything on the remote machine by itself.
- `endpoint` is metadata unless an adapter explicitly implements callback or
  bootstrap behavior.
- MCP Remote is the preferred low-install experiment path for Agents that can
  call remote tools and consume events.
- Sidecar-style connectors remain necessary for unattended local execution,
  private workspace access, and Agent runtimes without remote MCP support.

## Current next actions

- Build an adapter compatibility matrix for target Agents.
- Record which Agents support remote MCP, local stdio MCP, neither, or a vendor
  API path.
- Confirm whether MCP can trigger unattended work or only provide tools while an
  Agent is already active.
- Keep standard MCP invite copy centered on `review_room.connect` followed by
  `review_room.wait_for_action`; treat SSE as optional realtime delivery, not an
  unattended runtime guarantee.
- Make bootstrap output explicit about user-side prerequisites.
- Add owner-facing setup variants:
  - MCP Remote quick connect,
  - Codex sidecar command,
  - generic CLI adapter sketch,
  - enterprise HTTP callback sketch.

## Recent evidence

- [review-room-remote-mcp-debugging-2026-06-13-14.md](../review-room-remote-mcp-debugging-2026-06-13-14.md)
  captures the current standard MCP Streamable HTTP contract, UTF-8 probe,
  cursor loop, persistent test runner limits, and status semantics.
- `mcp_action_runner.py` proves a process can stay alive and drive
  `review_room.wait_for_action`, but it remains a protocol test runner rather
  than production Agent execution.

## Acceptance criteria

- Owner sees a clear connector path after invite or registration.
- The connector path states what Lighthouse Agent Board will do and what the user still
  needs to set up.
- Connector status distinguishes invited, active, stale, revoked, `mcp_ready`,
  and `mcp_streaming`.
- Tool calls and persistent event streams update connector status without
  overstating online presence.
- Every execution-capable adapter can produce first-class `agent_runs`.

## Open questions

- Which target Agents can consume remote Streamable HTTP MCP directly?
- Which target Agents require local MCP proxy config?
- Which target Agents can keep an event stream open?
- How should transcript links map across Codex, Claude Code, CodeBuddy,
  OpenClaw, HermesAgent, and future Agents?
- How much bootstrap should Lighthouse own versus the user-side connector?
