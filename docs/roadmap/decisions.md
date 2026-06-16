# Decisions

This file records accepted working decisions. It is not a changelog. Add to it
when a product or architecture call should guide future work.

## D-001: Lighthouse Agent Board is a milestone, not the boundary

Status: `Accepted`

Lighthouse Agent Board is the first milestone toward a Human-Agent Workspace.
MR review is the entry workflow because it has clear roles, artifacts, tasks,
verification, and approval. Architecture decisions should avoid overfitting to
MR review when the same board primitives can support broader collaboration
workflows. The current implementation may still use `review-room` paths and
`Room` schema names for compatibility.

## D-002: Room state is the collaboration source of truth

Status: `Accepted`

Messages, tasks, findings, handoffs, decisions, threads, and Agent runs should
stay in Agent Board state so the owner can audit and control collaboration.
Private Agent-to-Agent side channels should not become the product control
plane.

## D-003: Chat is not execution

Status: `Accepted`

Normal room messages are discussion. Agent execution requires explicit task
assignment, successful claim, or a policy-approved transition. This prevents
broadcast chat from causing duplicate or unintended Agent work.

## D-004: `agent_runs` is the canonical execution surface

Status: `Accepted`

Lighthouse Agent Board should not rely on any one vendor's session list for
trust. Every execution-capable connector should report visible run state through
`agent_runs`, with adapter-specific transcript or log pointers when available.

## D-005: Legacy direct adapters are not the product path

Status: `Superseded by D-013`

Earlier P0 work used direct adapter experiments to validate identity, tokens,
events, and `agent_runs`. Those experiments are no longer an owner-facing
product path. Keep their useful state-model lessons, but do not add UI or docs
that ask users to register direct Agent connectors.

## D-006: Remote MCP is the active Agent onboarding path

Status: `Accepted`

Remote MCP is the only active Agent onboarding path for the current product
phase. Other adapter ideas remain parked until MCP has proven real Agent
ergonomics and the owner explicitly reopens the integration scope.

## D-007: MCP invite does not bootstrap a remote machine

Status: `Accepted`

Creating an MCP invite creates Agent Board identity, credentials, and bootstrap
metadata. It does not by itself install dependencies, start a daemon, prepare a
repo checkout, or control the remote Agent machine.

## D-008: Server-side invalidation is not remote cleanup

Status: `Accepted`

Token rotation, disconnect, kick, and revocation can invalidate Agent Board
access. They should not be described as cleaning files, logs, shell history,
transcripts, config, or workspace residue on the Agent machine.

## D-009: Room and artifact content is untrusted by default

Status: `Accepted`

Guest messages, MR diffs, code comments, external links, attachments, and Agent
output should be treated as untrusted collaboration input. Context packs and
prompts should label trust boundaries before content reaches an Agent.

## D-010: External side effects stay behind owner decisions

Status: `Accepted`

Agents may propose external actions. Sync adapters may publish only after an
owner decision or a trusted policy boundary approves the action.

## D-011: `services/review-room-service` is the canonical Agent Board P0

Status: `Accepted`

Future Lighthouse Agent Board P0 work should land in
`services/review-room-service`. The older `experiments/review-room/service`
implementation remains a legacy protocol reference and evidence archive for
task/run/handoff/decision behavior, but it should not receive new product
features. Root validation should use the canonical service tests.

## D-012: Messages feed Inbox, not execution

Status: `Accepted`

Workbench messages remain a first-class supervision and coordination channel.
They enter the Context Stream and every participating Agent's Inbox so an
activated Agent can recover oversight context. `@Agent` mentions raise priority
and mark the item as requiring a reply, but message delivery never creates
execution authority; executable work still requires task claim and visible
`agent_run` state.

## D-013: Workbench UI and docs are MCP-only

Status: `Accepted`

Workbench product UI should expose only MCP invite copy and the `/mcp` endpoint
for Agent onboarding. Direct Agent registration flows must not appear in
Console copy, built-in P0 HTML, or current project docs. Backend
compatibility names such as `Room` and `connectors` may remain where they are
needed for schema, tests, MCP identity, and historical migration boundaries.
