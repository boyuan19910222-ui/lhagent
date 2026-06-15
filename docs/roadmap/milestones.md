# Milestones

## M0: Roadmap foundation

Status: `In progress`

Goal:

- Create a durable roadmap structure in the repo.
- Collect the current thesis, execution tracks, completed evidence, and idea
  backlog.

Acceptance:

- Roadmap folder exists and links to the existing Agent Board concept docs.
- Existing completed Agent Board work is summarized with evidence links.
- Future discussion has a clear place to land before it becomes implementation.

Next actions:

- Review this v0 with the owner.
- Add missing local discussion points into `ideas-inbox.md`.
- Promote the first 3 to 5 next actions into M1.

## M1: Local Lighthouse Agent Board P0 is reliable

Status: `In progress`

Goal:

- Make the local Lighthouse Agent Board experiment a reliable control-plane
  proof.
- Preserve the current P0 scope while tightening tests, docs, and UX paths.

Acceptance:

- Local tests pass for tasks, runs, connectors, handoffs, claims, MCP tools,
  owner decisions, realtime events, and scoped threads.
- The built-in page supports the core workflow without curl for normal owner
  actions.
- The service README gives a clear run, invite, MCP, and connector bootstrap
  path.
- Current implementation status is reflected in `done.md`.

Current evidence:

- Local repository test suite passed on 2026-06-14. See
  [done.md](./done.md#full-local-repository-test-suite).

Key tracks:

- [Lighthouse Agent Board P0](./tracks/review-room-p0.md)
- [Observability and routing](./tracks/observability-and-routing.md)
- [Safety and lifecycle](./tracks/safety-and-lifecycle.md)

## M2: Real remote Agent loop

Status: `Planned`

Goal:

- Validate Lighthouse Agent Board with real activated Agent behavior, not
  scripted demo messages.

Acceptance:

- A remote Agent can connect through the intended adapter path.
- The Agent can read board context with trust labels.
- The Agent responds only to explicit task or allowed tool context.
- `agent_runs`, status, task completion, and transcript or log pointers are
  visible to the owner.
- Encoding and locale issues are handled before the first user-facing Agent
  reply.
- Disconnect, token rotation, and revocation behavior is clear to the owner.

Key tracks:

- [Connector and MCP](./tracks/connector-and-mcp.md)
- [Observability and routing](./tracks/observability-and-routing.md)
- [Safety and lifecycle](./tracks/safety-and-lifecycle.md)

## M3: Connector ecosystem

Status: `Planned`

Goal:

- Split the connector protocol, connector runtime, and Agent adapters so
  Lighthouse Agent Board is not locked to the current Codex sidecar.

Acceptance:

- Connector registration declares adapter type, protocol version, capabilities,
  forbidden actions, heartbeat, and version.
- `codex-sidecar` remains a compatibility adapter.
- `mcp-remote` is validated against at least one real Agent path.
- The adapter matrix documents which Agents need MCP, sidecar, CLI, HTTP,
  vendor API, or A2A integration.
- Bootstrap UX explains what Lighthouse Agent Board can start remotely and what still
  requires user-side setup.

Key track:

- [Connector and MCP](./tracks/connector-and-mcp.md)

## M4: Lighthouse control plane productization

Status: `Planned`

Goal:

- Move from local experiment to Lighthouse product surface.

Acceptance:

- Lighthouse backend owns durable board state.
- Lighthouse Console exposes board list, board detail, task panel, run panel,
  finding panel, decisions, and connector status.
- User-side connector boundary protects private repo, IM, and Agent execution
  access.
- Git and IM sync adapters publish only confirmed decisions.

Key track:

- [Lighthouse productization](./tracks/lighthouse-productization.md)

## M5: Workspace expansion

Status: `Open question`

Goal:

- Test whether the same room primitives support non-MR collaboration.

Candidate room types:

- incident response,
- release readiness,
- legal review,
- security triage,
- product decision,
- documentation review.

Acceptance:

- At least one non-MR workflow is mapped to room, task, artifact, Agent run,
  handoff, decision, and sync primitives.
- The workflow does not require weakening the safety or observability model.
