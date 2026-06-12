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

## Current acceptance checklist

- [ ] Local task/run tests pass.
- [ ] Local connector task-assignment tests pass.
- [ ] Home page exposes visible task/run controls.
- [ ] Full `npm test` passes.
- [ ] Remote service updated.
- [ ] Remote smoke test proves task/run loop.
- [ ] User receives public URL and curl verification commands.
