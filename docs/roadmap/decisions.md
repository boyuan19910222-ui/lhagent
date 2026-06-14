# Decisions

This file records accepted working decisions. It is not a changelog. Add to it
when a product or architecture call should guide future work.

## D-001: Review Room is a milestone, not the boundary

Status: `Accepted`

Review Room is the first milestone toward a Human-Agent Workspace. MR review is
the entry workflow because it has clear roles, artifacts, tasks, verification,
and approval. Architecture decisions should avoid overfitting to MR review when
the same room primitives can support broader collaboration workflows.

## D-002: Room state is the collaboration source of truth

Status: `Accepted`

Messages, tasks, findings, handoffs, decisions, threads, and Agent runs should
stay in Review Room state so the owner can audit and control collaboration.
Private Agent-to-Agent side channels should not become the product control
plane.

## D-003: Chat is not execution

Status: `Accepted`

Normal room messages are discussion. Agent execution requires explicit task
assignment, successful claim, or a policy-approved transition. This prevents
broadcast chat from causing duplicate or unintended Agent work.

## D-004: `agent_runs` is the canonical execution surface

Status: `Accepted`

Review Room should not rely on any one vendor's session list for trust. Every
execution-capable connector should report visible run state through
`agent_runs`, with adapter-specific transcript or log pointers when available.

## D-005: Codex sidecar is an adapter, not the connector architecture

Status: `Accepted`

The current Codex bridge is useful for P0 validation, but the stable product
contract should separate connector protocol, generic runtime or sidecar, and
adapter-specific execution.

## D-006: MCP Remote is a key low-install path, not a universal answer

Status: `Accepted`

MCP Remote should be explored as the preferred low-install path for Agents that
can consume remote tools and events. It should not replace sidecar, CLI, HTTP,
A2A, or vendor API adapters until real compatibility, trigger, workspace, and
observability behavior is proven.

## D-007: Connector registration does not bootstrap a remote machine

Status: `Accepted`

Registering or inviting a connector creates Review Room identity, credentials,
and bootstrap metadata. It does not by itself install dependencies, start a
daemon, prepare a repo checkout, or control the remote Agent machine.

## D-008: Server-side invalidation is not remote cleanup

Status: `Accepted`

Token rotation, disconnect, kick, and revocation can invalidate Review Room
access. They should not be described as cleaning local files, logs, shell
history, transcripts, config, or workspace residue on the Agent machine unless
the adapter explicitly supports that cleanup.

## D-009: Room and artifact content is untrusted by default

Status: `Accepted`

Guest messages, MR diffs, code comments, external links, attachments, and Agent
output should be treated as untrusted collaboration input. Context packs and
prompts should label trust boundaries before content reaches an Agent.

## D-010: External side effects stay behind owner decisions

Status: `Accepted`

Agents may propose external actions. Sync adapters may publish only after an
owner decision or a trusted policy boundary approves the action.

