# Review Room Execution Plan

## Goal

Deliver a simple, visible Review Room integration path that validates the product ideas from the architecture notes:

- Connector registration is explicit about adapter type, protocol version, capabilities, and forbidden actions.
- Human chat does not automatically trigger every Agent.
- Owner-created tasks drive Agent execution.
- Every Agent execution is visible through `agent_runs`.
- Existing Codex connector remains the first adapter.
- MCP Gateway is explored as an adapter path, not as the only connector architecture.
- The running slice is deployed to the lightweight cloud Review Room service for hands-on verification.

## Delivery slices

### Slice 1: Task and run control loop

User-visible result:

- Owner can create a task for a specific connector.
- The assigned connector receives `task.assigned`.
- The connector starts an `agent_run`, produces a finding/message/response, and completes the task.
- Room snapshot shows `tasks` and `agentRuns`.

Implementation:

- Add `tasks` table.
- Add `agent_runs` table.
- Add connector metadata fields: `adapterType`, `protocolVersion`, `capabilities`, `forbidden`, `version`, and `heartbeatAt`.
- Add REST endpoints:
  - `POST /api/rooms/{room_id}/tasks`
  - `POST /api/tasks/{task_id}/runs`
  - `POST /api/tasks/{task_id}/complete`
- Add WebSocket events:
  - `task.create`
  - `task.created`
  - `task.assigned`
  - `agent_run.start`
  - `agent_run.started`
  - `task.complete`
  - `task.completed`

Verification:

- Unit tests prove task assignment, connector-only run start, task completion, and snapshot visibility.
- WebSocket tests prove a connector receives assignment and emits run lifecycle events.

### Slice 2: Simple connector bootstrap

User-visible result:

- After registering a connector, owner sees a concrete command/config path for starting the connector.
- The command keeps the existing `codex_connector.py` path as the first adapter.

Implementation:

- Add generated connector config fields to registration response.
- Document local and remote command examples in the service README.
- Keep tokens visible only to the owner and returned registration response.

Verification:

- Tests prove registration response includes adapter metadata and bootstrap details.
- Room snapshot hides connector tokens from guests/connectors.

### Slice 3: MCP Gateway experiment

User-visible result:

- A minimal MCP-style gateway can read a room snapshot and submit a structured finding through connector identity.
- The experiment clearly states what still requires real Agent compatibility testing.

Implementation:

- Add HTTP JSON endpoints for the first gateway slice:
  - list tools/resources.
  - get room snapshot.
  - create finding.
- Keep connector token authorization and capability checks.

Verification:

- Tests prove the gateway can read snapshot and create a finding with a connector token.
- Tests prove guest/owner tokens cannot impersonate connector tools.

### Slice 4: Lightweight cloud deployment

User-visible result:

- The public Review Room service on the lightweight cloud host runs the updated code.
- Health check passes.
- A remote smoke test creates a room, registers a connector, creates a task, starts a run, completes the task, and reads the final snapshot.

Verification:

- `GET /health` returns ok.
- Smoke test response includes one task and one completed agent run.
- The deployed systemd service is active.

### Slice 5: Visible simple onboarding path

User-visible result:

- Owner can create a room, invite an Agent, and see the connector bootstrap path from the same page.
- Owner can open the right-side `任务与运行` panel, choose a connector, and assign a structured task without calling curl manually.
- The page shows current tasks and `agentRuns`, making Agent background work visible during the review.

Implementation:

- Add a right-side work panel to the built-in Review Room HTML.
- Reuse `POST /api/rooms/{room_id}/tasks` for task assignment from the page.
- Render task and run snapshots from `tasks` and `agentRuns`.

Verification:

- Home page tests prove the task/run controls and API wiring are present.
- End-to-end API smoke still proves the same task/run loop on the deployed service.

### Slice 6: Connector token rotation

User-visible result:

- Owner can rotate an Agent connector token without deleting the connector record.
- Old connector tokens stop working immediately.
- Active connector WebSocket sessions are disconnected and must reconnect with the new token.
- The Room timeline records an audit event without leaking the new token.

Implementation:

- Add `POST /api/rooms/{room_id}/connectors/{connector_id}/rotate-token`.
- Return the new connector token and bootstrap command only in the owner-authenticated response.
- Reset the connector to `invited` until it reconnects with the rotated token.

Verification:

- Store tests prove old token invalidation, new token authentication, and audit redaction.
- HTTP tests prove old connector events fail and new connector events work.
- WebSocket tests prove active old sessions receive a disconnect event.

### Slice 7: Reviewer-to-Developer handoff

User-visible result:

- Reviewer Agent can propose that a finding should be handed off to another role or capability.
- Owner can accept or reject the handoff from Review Room state.
- Accepting a handoff converts it into a structured `fix` task and assigns it to an eligible Developer Agent.
- Handoffs are visible in the Room snapshot and right-side work panel.

Implementation:

- Add a `handoffs` table.
- Add `POST /api/findings/{finding_id}/handoffs`.
- Add `POST /api/handoffs/{handoff_id}/accept` and `/reject`.
- Add WebSocket events `handoff.propose`, `handoff.proposed`, `handoff.converted_to_task`, and `handoff.rejected`.

Verification:

- Store tests prove `finding -> handoff -> task` conversion.
- HTTP tests prove owner-accepted handoff creates an assigned Developer task.
- WebSocket tests prove Developer Agent receives `task.assigned` after owner accepts the handoff.

### Slice 8: Automatic verification task after fix

User-visible result:

- When a Developer Agent completes a `fix` task created from a handoff, Review Room creates a follow-up `verify` task.
- The verification task keeps source links to the fix task, finding, and handoff.
- Review Room assigns the verification task back to the original Reviewer Agent when that connector is still eligible.
- The Reviewer Agent receives a normal `task.assigned` event; verification remains explicit task execution, not hidden chat-triggered work.

Implementation:

- Add a `complete_task_result` path that returns the completed task plus any newly-created follow-up task.
- Generate an idempotent `verify` task for completed handoff-backed `fix` tasks.
- Broadcast `task.created` and `task.assigned` for the verification task over HTTP/WebSocket realtime paths.
- Keep the legacy `complete_task` return shape as the completed task for connector compatibility.

Verification:

- Store tests prove `fix -> verify` task generation and source linkage.
- HTTP tests prove Developer task completion creates a Reviewer verification task in the room snapshot.
- WebSocket tests prove the Reviewer connector receives `task.assigned` for the generated verification task.

### Slice 9: Claimable tasks and MCP task discovery

User-visible result:

- Owner can create an open task with `target.mode=claim`.
- A connector must explicitly claim matching work before it can start an `agent_run`.
- Claim checks enforce connector room, revoked status, target role, and target capability.
- MCP-style connectors can list room tasks and claim eligible tasks without installing the Codex sidecar.

Implementation:

- Add `claim_task` store logic with lease assignment and `task_claimed` audit messages.
- Add `POST /api/tasks/{task_id}/claim`.
- Add WebSocket `task.claim`, broadcasting `task.claimed` and then `task.assigned`.
- Reject `agent_run.start` and `task.complete` for unassigned open tasks.
- Add MCP tools `list_tasks` and `claim_task` on the experimental gateway.

Verification:

- Store tests prove unmatched connectors cannot claim and open tasks cannot run before claim.
- HTTP tests prove claim is required before starting a run.
- WebSocket tests prove claim produces realtime assignment and then allows run start.
- MCP tests prove task listing marks claimable work and `claim_task` assigns it.

## Current acceptance checklist

- [ ] Local task/run tests pass.
- [ ] Local connector task-assignment tests pass.
- [ ] Claimable task routing tests pass.
- [ ] Home page exposes visible task/run controls.
- [ ] Connector token rotation tests pass.
- [ ] Handoff conversion tests pass.
- [ ] Verification task generation tests pass.
- [ ] Full `npm test` passes.
- [ ] Remote service updated.
- [ ] Remote smoke test proves task/run loop, claim routing, token rotation, handoff conversion, and verification task generation.
- [ ] User receives public URL and curl verification commands.
