# Lighthouse Review Room

## Core conclusion

Review Room should be a Lighthouse-hosted Agent collaboration control plane, not only a chat room and not only a small service inside one user instance.

Related productization notes:

- [Roadmap](../roadmap/README.md)
- [Review Room Execution Plan](./review-room-execution-plan.md)
- [Review Room Connector Architecture](./review-room-connector-architecture.md)
- [Review Room Protocol](./review-room-protocol.md)
- [Review Room Security](./review-room-security.md)
- [Review Room Agent Collaboration](./review-room-agent-collaboration.md)

Recommended split:

| Layer | Deployment | Responsibility |
| --- | --- | --- |
| Review Room Control Plane | Lighthouse platform | Room, message, finding, artifact, identity, permission, audit, console UI, MR comment synchronization |
| Review Room Connector | User Lighthouse instance or local CLI | Private Git/IM access, local Agent bridge, remote Reviewer Agent adapter, A2A/MCP conversion |

This keeps private source code, enterprise Git tokens, IM tokens, and local Agent execution inside the user's trusted environment while still giving Lighthouse a durable collaboration state source.

## Product model

Review Room turns code review into a structured Agent collaboration room:

- MR is the context entry.
- Room is the collaboration state source.
- Finding is the structured review output.
- Developer Agent responses are tracked in the Room.
- Human confirmation is the external sync boundary.
- Connector syncs confirmed results back to MR comments, IM, or later pipeline status.

Lighthouse does not need to be the smartest review Agent. Its role is to host the coordination layer where local and remote Agents can participate safely, leave auditable traces, and hand control back to a human before external changes are published.

## Agent split

Remote Reviewer Agents are better suited for read-only, review, verification, and design judgment work:

- Read the current MR or branch diff and produce structured findings.
- Review a Developer Agent fix plan and call out missing tests or unresolved risk.
- Evaluate the Review Room console interaction model.
- Audit connector security boundaries such as token scope, webhook secret handling, public exposure, and MR comment permissions.
- Re-check completed fixes and return pass/fail plus remaining findings.

Local Developer Agents are better suited for source edits, tests, running services, UI verification, and preparing commits. This keeps write conflicts inside the local workspace and keeps remote Agents focused on review output.

## Local product slice

This repository includes a local product slice at:

```text
experiments/review-room/service
```

The service uses SQLite for state, `aiohttp` for the realtime HTTP/WebSocket surface, and `codex_connector.py` as the Agent-side bridge to `codex exec --json`. It models:

- Review Room storage.
- Room messages.
- Structured findings.
- Local and remote Agent connectors.
- Token-authenticated connector events.
- Room-scoped owner and connector WebSocket identities.
- Guest invites, join tokens, and owner-controlled member disconnect.
- Developer Agent responses.
- Human confirmation and MR sync preview.
- Reviewer-to-Developer handoffs that owner can convert into tasks.
- Automatic Reviewer verification tasks after Developer fix completion.
- GitLab/GitHub-style merge request webhook ingestion.

It is intentionally small enough to run on a Lighthouse instance after installing the service requirements, and concrete enough to validate the full Room -> Connector -> Finding -> Developer response -> human confirmation loop with real Agent processes.

## API surface

- `GET /health`
- `POST /api/demo/session`
- `POST /api/rooms`
- `GET /api/rooms`
- `GET /api/rooms/{id}`
- `POST /api/rooms/{id}/invites`
- `POST /api/rooms/{id}/join`
- `POST /api/rooms/{id}/connectors`
- `POST /api/rooms/{id}/connectors/{connector_id}/rotate-token`
- `POST /api/rooms/{id}/tasks`
- `POST /api/rooms/{id}/threads`
- `POST /api/rooms/{id}/disconnect`
- `POST /api/connectors/{id}/events`
- `POST /api/tasks/{id}/claim`
- `POST /api/tasks/{id}/runs`
- `POST /api/tasks/{id}/complete`
- `POST /api/rooms/{id}/messages`
- `POST /api/rooms/{id}/findings`
- `POST /api/findings/{id}/handoffs`
- `POST /api/handoffs/{id}/accept`
- `POST /api/handoffs/{id}/reject`
- `POST /api/threads/{id}/messages`
- `POST /api/threads/{id}/summary`
- `POST /api/decisions/{id}/accept`
- `POST /api/decisions/{id}/reject`
- `PATCH /api/findings/{id}`
- `POST /api/findings/{id}/developer-response`
- `POST /api/findings/{id}/confirm`
- `POST /api/webhooks/merge-request`
- `GET /api/mcp/tools`
- `POST /api/mcp/tools/get_snapshot`
- `POST /api/mcp/tools/post_message`
- `POST /api/mcp/tools/create_finding`
- `POST /api/mcp/tools/propose_handoff`
- `POST /api/mcp/tools/list_tasks`
- `POST /api/mcp/tools/claim_task`
- `POST /api/mcp/tools/start_run`
- `POST /api/mcp/tools/complete_task`
- `POST /api/mcp/tools/request_owner_confirmation`
- `GET /ws/rooms/{id}?token=...`

## Productization path

P0: Local research loop

- Run the included connector service.
- Exercise MR webhook -> Room -> WebSocket connector -> Finding -> Developer Agent response -> human confirmation.
- Add webhook secret validation and connector token rotation before public exposure.
- Use SSH tunnel or HTTPS reverse proxy for controlled access.

P0.5: Connector and execution hardening

- Keep `codex_connector.py` as a compatibility adapter, not the universal connector contract.
- Add connector metadata such as adapter type, protocol version, capabilities, forbidden actions, heartbeat, and version.
- Add first-class `agent_runs` so background Agent work is visible even when a vendor session list is not.
- Add `task.create` and direct `task.assigned` so normal room messages do not trigger Agent execution.
- Add `task.claim` so open role/capability work cannot run until an eligible connector explicitly claims it.
- Add owner-triggered connector token rotation so leaked or stale connector credentials can be invalidated without deleting the connector record.
- Add `handoff.propose` and owner accept/reject so Reviewer Agent recommendations become Developer Agent tasks only through visible Review Room state.
- Add automatic `verify` task generation after completed handoff-backed `fix` tasks, preserving links to the source finding and handoff.
- Add MCP `start_run` and `complete_task` tools so MCP-style connectors can produce first-class `agent_runs`.
- Add decision records and MCP `request_owner_confirmation` so external actions stay behind owner approval.
- Add MCP `post_message` and `propose_handoff` so lightweight connectors can join room discussion and propose owner-visible handoffs without a sidecar.
- Add scoped `agent_deliberation` threads so multi-Agent discussion is visible, bounded, participant-scoped, and summarized before owner action.
- Extract a generic connector runtime or sidecar with adapter dispatch.
- Add bootstrap commands, generated config, service setup, logs, reconnect policy, and token rotation.
- Build a minimal MCP Gateway experiment for read-only room snapshots and structured finding submission.

P1: Lighthouse control plane

- Move Room state into Lighthouse backend.
- Show real Room list, Room detail, Finding state, and connector status in Lighthouse Console.
- Keep the user-side Connector responsible for private network and Agent adapter access.

P2: Agent protocol ecosystem

- Add A2A adapter by mapping Room/Finding/Artifact to A2A Task/Message/Artifact.
- Add MCP Gateway tools such as `get_snapshot`, `list_tasks`, `claim_task`, `start_run`, `post_message`, `create_finding`, `propose_handoff`, `complete_task`, and `request_owner_confirmation`.
- Add IM and Git adapters for WeCom, Feishu, QQ, GitHub, GitLab, and Gongfeng MR comments.
