# Review Room Connector Architecture

## Purpose

Review Room needs a connector architecture that works beyond the current Codex prototype.

The current `codex_connector.py` is useful for P0 validation, but it mixes three concerns:

- Review Room transport over authenticated HTTP and WebSocket events.
- Connector runtime behavior such as reconnect, status reporting, history loading, and logs.
- Codex-specific execution behavior such as `codex exec --json`, sandbox selection, prompt shaping, and JSONL parsing.

Productization should keep Codex as one adapter, not as the universal connector contract.

## Target shape

Agent-side integration should split into three layers:

| Layer | Responsibility |
| --- | --- |
| Review Room Connector Protocol | Token auth, identity, capabilities, input events, output events, heartbeat, errors, version and schema negotiation |
| Generic Connector Runtime or sidecar | WebSocket connection, reconnect, room snapshot loading, schema validation, status reporting, logs, token refresh, adapter dispatch |
| Agent Adapter | Codex, CLI, HTTP webhook, A2A, MCP, vendor API, or custom enterprise SDK integration |

This split lets remote Agents either implement the Review Room protocol directly or run a generic sidecar that adapts Review Room tasks to the Agent's native interface.

## Connector identity

Connector registration should move toward explicit adapter metadata:

```json
{
  "name": "Reviewer Agent",
  "role": "reviewer",
  "adapterType": "codex-sidecar",
  "protocolVersion": "review-room.v1",
  "capabilities": ["room:read", "message:reply", "finding:create"],
  "forbidden": ["repo:write", "external:sync", "deploy:execute"],
  "endpoint": "",
  "version": "0.1.0"
}
```

The Connector remains the product identity and permission boundary even when the underlying adapter changes.

## Bootstrap gap

Current connector registration only creates a server-side connector record and returns access details such as room id, role, and connector token.

It does not:

- Install the connector runtime on a local or remote Agent machine.
- Install Python or other runtime dependencies.
- Install Codex, CodeBuddy, OpenClaw, or any other Agent runtime.
- Prepare a target repository checkout or workspace.
- Start a user service, systemd service, daemon, or background worker.
- Use the `endpoint` field to callback, bootstrap, or remote-control the connector.

The Agent-side connector currently connects outbound to:

```text
/ws/rooms/<room_id>?token=<connector_token>
```

Productization needs an installer or bootstrap layer with:

- One-time install commands.
- Generated config files.
- Systemd or user-service setup.
- Token rotation and refresh.
- Heartbeat and version reporting.
- Reconnect policy.
- Local logs and transcript paths.
- Clear permission boundaries for who can provision, update, or revoke a connector.

## Adapter types

Recommended adapter types:

| Adapter type | Use case | Notes |
| --- | --- | --- |
| `codex-sidecar` | Current P0 Codex CLI bridge | Good compatibility sample, not the whole protocol |
| `cli` | Generic command-line Agent | Runtime maps task input to a command and parses output |
| `http-webhook` | Agent or service that accepts HTTP callbacks | Useful for enterprise systems with stable callbacks |
| `a2a` | Agents that speak A2A Task/Message/Artifact | Maps Review Room objects into A2A objects |
| `mcp-remote` | Agents that can call remote MCP servers | Best for tool/resource style integration |
| `vendor-api` | Hosted Agent with proprietary API | Adapter owns vendor auth and session mapping |

## MCP Gateway

A Review Room MCP Gateway is the preferred first entry path for Agents that already support remote MCP servers, especially HTTPS or Streamable HTTP MCP.

Agent invite links now default to `adapterType=mcp-remote`. The invite bootstrap returns the MCP tool base URL, connector token, room id, connector id, role, and supported tools. `codex-sidecar` remains an explicit compatibility adapter for environments that need a local WebSocket process or Codex CLI bridge.

MCP reduces the need to install `codex_connector.py` or a Lighthouse-specific sidecar on an Agent host, while still preserving connector-scoped identity, capabilities, task claiming, first-class `agent_runs`, owner confirmation, and trust labels. Because MCP is tool-call oriented rather than a persistent socket, MCP tool calls mark the connector as `mcp_ready` and update `lastSeenAt`/`eventCount`; they do not count as WebSocket online presence.

MCP connectors observe room activity through a realtime SSE stream plus `poll_events` for reconnect recovery. The MCP bootstrap returns `eventStreamUrl`, bearer authorization details, and a WebSocket fallback URL. A remote Agent that keeps the SSE stream open receives room messages, tasks, findings, handoffs, decisions, scoped threads, thread messages, and agent runs as they happen; `Last-Event-ID` or `poll_events` lets it catch up after disconnect. Receiving a chat message still does not imply executable work unless an explicit assigned or claimed task exists.

Candidate MCP tools:

- `get_snapshot` (implemented in the P0 experiment)
- `poll_events` (implemented in the P0 experiment)
- `list_tasks` (implemented in the P0 experiment)
- `claim_task` (implemented in the P0 experiment)
- `start_run` (implemented in the P0 experiment)
- `post_message` (implemented in the P0 experiment)
- `create_finding` (implemented in the P0 experiment)
- `propose_handoff` (implemented in the P0 experiment)
- `complete_task` (implemented in the P0 experiment)
- `request_owner_confirmation` (implemented in the P0 experiment)

Candidate MCP streams:

- `room.events` over SSE at `/api/mcp/events?roomId=<roomId>` (implemented in the P0 experiment)

Candidate MCP resources:

- Room timeline.
- Task list.
- Finding list.
- MR diff.
- Artifacts.

Every resource exposed through MCP should carry explicit trust labels. Room messages, guest comments, MR diffs, code comments, and attachments are collaboration input, not trusted instructions.

## MCP open questions

The MCP direction needs product experiments before becoming the default connector path:

- Which target Agents support remote MCP servers directly?
- Which target Agents only support local stdio MCP or no MCP at all?
- Is adding a remote MCP URL enough, or does the user still need a local proxy, plugin, CLI config, or workspace helper?
- Can the Agent be reliably triggered by MCP-discovered tasks, or does MCP only expose tools that the Agent calls while already active?
- Can an Agent poll or wait for Review Room tasks through MCP, or is a sidecar or worker still required for unattended execution?
- If a task needs local edits, tests, or private file reads, where does that capability live: the Agent's native environment, a local connector, or a hosted runner?
- Can MCP-based runs still produce first-class `agent_runs`, transcript links, status updates, and revocation behavior in Review Room?
- Do Codex, Claude Code, CodeBuddy, OpenClaw, HermesAgent, and future Agents need different adapter paths despite sharing some MCP capability?

## Run visibility

Review Room should not depend on a vendor-specific Agent session list for trust.

Every connector execution should create or update a first-class `agent_run` with:

- Run id.
- Room id.
- Task id.
- Connector id.
- Adapter type.
- External session id when available.
- Status.
- Started and finished timestamps.
- Prompt summary.
- Workspace.
- Model.
- Sandbox.
- Final message.
- Error.
- Log path or transcript URL.

For Codex specifically, the adapter should capture any available external session or thread id. A future `codex-thread` adapter may create or continue a visible Codex app thread, but Review Room should remain the canonical cross-Agent observability surface.

## Productization order

1. Keep `codex_connector.py` as the P0 compatibility adapter.
2. Add connector metadata: `adapterType`, `protocolVersion`, capabilities, forbidden actions, heartbeat, and version.
3. Add first-class `agent_runs` independent of any vendor UI.
4. Add `task.create` and direct `task.assigned` before Agents execute work.
5. Extract a generic connector runtime or sidecar from the Codex-specific connector.
6. Add bootstrap commands and generated connector config.
7. Build a minimal MCP Gateway with read-only snapshot and structured finding submission.
8. Test the MCP Gateway against one Agent with remote MCP support and one Agent with local-only or no MCP support.
9. Decide whether MCP is the default connector path, an enterprise integration path, or a compatibility adapter.
