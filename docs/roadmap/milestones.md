# Milestones

## Progress snapshot: 2026-06-20

Lighthouse Agent Board is now past roadmap foundation and into local P0
hardening plus remote preview verification. The strongest verified areas are
Workbench CRUD/lifecycle, human supervisor invites, message and audit surfaces,
MCP-only Agent onboarding, and server-side leave/revoke semantics. The strongest
real remote-Agent proof is still partial: activated Agents have joined through
the deployed `/mcp` endpoint, consumed Inbox context, and exchanged visible
messages, but the full task claim -> `agent_run` -> completion -> handoff ->
owner decision loop still needs real activated-Agent verification.

Current status by milestone:

- M0 is done: the roadmap ledger and repository Agent guide exist.
- M1 is in progress: the canonical local P0 service has broad API/UI/test
  coverage and remote preview smoke evidence, but should keep refreshing
  evidence before each product claim.
- M2 is in progress: real remote MCP messaging and Inbox are verified; real
  task/run execution remains the next proof.
- M3 is in progress: MCP-only onboarding now includes briefing, leave, reconnect,
  and revoke semantics; compatibility and bootstrap variants remain open.
- M4 is in progress at local P0 depth: Workbench CRUD and lifecycle controls
  exist in the canonical service, while durable Lighthouse Console/backend
  productization is still planned.
- M5 remains an open question until a non-MR workflow is mapped without
  weakening the safety or observability model.

## M0: Roadmap foundation

Status: `Done`

Goal:

- Create a durable roadmap structure in the repo.
- Collect the current thesis, execution tracks, completed evidence, and idea
  backlog.

Acceptance:

- Roadmap folder exists and links to the existing Agent Board concept docs.
- Existing completed Agent Board work is summarized with evidence links.
- Future discussion has a clear place to land before it becomes implementation.

Evidence:

- [README.md](./README.md)
- [product-thesis.md](./product-thesis.md)
- [decisions.md](./decisions.md)
- [done.md](./done.md#roadmap)
- [AGENTS.md](../../AGENTS.md)

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

- Local repository test suite passed on 2026-06-15. See
  [done.md](./done.md#full-local-repository-test-suite).
- Workbench CRUD, lifecycle, collaboration, audit, supervisor invite, and
  MCP-only onboarding evidence is recorded in
  [done.md](./done.md#lighthouse-agent-board-local-p0).
- Agent and supervisor leave/revoke lifecycle has remote preview/API smoke
  evidence in
  [done.md](./done.md#agent-and-supervisor-room-exit-lifecycle).

Remaining proof:

- Keep root `npm test` current after every P0 service change.
- Add or refresh a compact manual full-review scenario that exercises owner ->
  Reviewer -> Developer -> verification -> owner decision in one board.
- Avoid calling local P0 UI behavior production-complete until the intended
  Lighthouse Console/backend target is verified.

Key tracks:

- [Lighthouse Agent Board P0](./tracks/review-room-p0.md)
- [Observability and routing](./tracks/observability-and-routing.md)
- [Safety and lifecycle](./tracks/safety-and-lifecycle.md)

## M2: Real remote Agent loop

Status: `In progress`

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

Current evidence:

- [Real remote MCP Agent Board inbox and messaging scenario](./done.md#real-remote-mcp-agent-board-inbox-and-messaging-scenario):
  activated Reviewer and Developer Agents joined the same deployed board,
  recovered context, handled direct mentions through Inbox, and kept ordinary
  chat separate from task execution.

Remaining proof:

- Verify the real task claim, `agent_run`, completion, handoff, and owner
  decision loop with activated Agents, not only messages and Inbox routing.
- Verify transcript or log pointer behavior for a real adapter run.

## M3: MCP Agent onboarding

Status: `In progress`

Goal:

- Make Remote MCP onboarding reliable enough for real Agent Board evaluation
  without adding non-MCP onboarding paths.

Acceptance:

- MCP invite bootstrap declares role, capabilities, forbidden actions, status
  semantics, and expiry.
- `mcp-remote` is validated against at least one real Agent path.
- The MCP compatibility matrix documents which Agents support remote MCP, which
  need Agent-side configuration, and which cannot join yet.
- Bootstrap UX explains what Lighthouse Agent Board can invalidate server-side
  and what still requires user-side setup.

Key track:

- [Connector and MCP](./tracks/connector-and-mcp.md)

Current evidence:

- [Workbench MCP-only onboarding cleanup](./done.md#workbench-mcp-only-onboarding-cleanup)
  keeps owner-facing UI and docs on MCP invite copy plus `/mcp`.
- [Agent and supervisor room exit lifecycle](./done.md#agent-and-supervisor-room-exit-lifecycle)
  records the current MCP `leave_room`, reconnect, owner revoke, and blocked
  tool behavior.

Remaining proof:

- Build the MCP compatibility matrix for target Agents.
- Document Agent-side setup variants that still map to the same `/mcp` contract.
- Keep bootstrap copy explicit that MCP invites do not install, start, or clean
  up anything on the remote Agent machine.

## M4: Lighthouse control plane productization

Status: `In progress`

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

Current evidence:

- [Workbench CRUD and Terminal Operations UI framework](./done.md#workbench-crud-and-terminal-operations-ui-framework)
  records local P0 Workbench create/list/read and owner-gated lifecycle
  controls.
- [Workbench detail collaboration surface and audit log cleanup](./done.md#workbench-detail-collaboration-surface-and-audit-log-cleanup)
  records local and remote preview evidence for dynamic Agent mentions, compact
  message composer, collapsed audit log, and role-gated finding mutation.

Remaining proof:

- Decide what moves from the canonical P0 service into the durable Lighthouse
  backend unchanged and what remains prototype-only.
- Define Console-grade state retention, sync preview, transcript/log retention,
  and external integration boundaries before product launch claims.

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
