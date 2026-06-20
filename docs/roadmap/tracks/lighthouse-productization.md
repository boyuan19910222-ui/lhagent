# Track: Lighthouse Productization

Status: `In progress`

## Purpose

Move Lighthouse Agent Board from local experiment into Lighthouse as a durable product
surface.

## Target shape

Lighthouse should provide:

- room list,
- workbench CRUD and lifecycle controls,
- room detail,
- timeline,
- task panel,
- Agent run panel,
- finding panel,
- handoff and decision panel,
- MCP Agent status and lifecycle controls,
- MCP invite and bootstrap UX,
- audit and sync preview,
- integration settings.

Private repo, IM, and Agent execution access should stay in the user's trusted
environment. Lighthouse exposes MCP tools and records state; it does not take
over private Agent runtime setup.

## Workbench CRUD and UI framework

Status: `Done in local P0`

The next productization step is to define the Workbench framework before
building full CRUD. The current P0 already has useful object primitives, but it
does not yet have a complete Workbench management model or Console-grade UI.

Framework first means:

- Treat the Agent Board as a Workbench surface, not a chat room.
- Define Workbench-level lifecycle operations: create, list, read, rename,
  archive, restore, and delete.
- Map existing P0 objects into product surfaces: Context Stream, Agent Inbox,
  Tasks, Findings, Runs, Handoffs, Decisions, MCP Agent status, Threads, and
  Audit.
- Record which operations are already supported by P0 APIs or MCP tools and
  which are planned for Console CRUD.
- Design the UI information architecture before expanding implementation:
  board list, board detail, object panels, inspector, activity/audit rail, and
  owner action bar.
- Keep deletion and destructive lifecycle actions behind owner confirmation,
  audit records, and clear remote-cleanup boundaries.

Initial capability framing after the local P0 implementation:

- Workbench: create/list/read exist through `/api/workbenches`, mapped to the
  canonical room store for compatibility.
- Workbench lifecycle: rename, archive, restore, and delete exist in the local
  P0 API with owner authorization and audit events.
- Workbench delete is a server-side tombstone; it does not claim to clean remote
  Agent machines, shell history, Agent-side MCP configuration, transcripts, caches,
  or workspace files.
- Messages: create/read exist; edit/delete are not part of the execution path
  and need product policy before implementation.
- Inbox: MCP read/ack states exist; Console inbox UI and batch handling are
  planned.
- Tasks and Runs: create/list/claim/start/complete exist across REST and MCP;
  Console edit, cancel, retry, reassign, and timeline views are planned.
- Findings, Handoffs, and Decisions: core objects exist; Console-first review
  and owner-decision flows need a dedicated UI framework.
- MCP Invites and Agent status: invite/read exist through MCP-first flows;
  lifecycle controls such as rotate, revoke, disconnect, permissions, and
  cleanup guidance need product UI without reintroducing direct Agent
  registration.

## Current next actions

- Decide which local P0 Workbench API surfaces should move into the durable
  Lighthouse Console backend unchanged, and which should remain compatibility
  aliases for `/api/rooms`.
- Decide which parts of the P0 service become product backend and which remain
  prototype-only.
- Translate the local P0 Workbench lifecycle UX into Console-grade flows for
  rename/archive/restore/delete with owner confirmation, destructive-action
  copy, and audit review.
- Turn the local role-permission cues into a durable capability matrix before
  expanding supervisor, invite, Agent-management, or task-routing flows.
- Define GitHub, GitLab, Gongfeng, Feishu, WeCom, and QQ sync boundaries.
- Decide how room events, audit logs, and transcript links are retained.

## Recent evidence

- [done.md](../done.md#workbench-crud-and-terminal-operations-ui-framework)
  records the local P0 Workbench Hall, create/list/read APIs, owner-gated
  archive/restore/delete semantics, and deletion cleanup boundary.
- [done.md](../done.md#workbench-human-supervisor-one-time-invite-url)
  records named one-time human supervisor invite URLs and read-scoped
  supervisor access without token leakage.
- [done.md](../done.md#workbench-detail-collaboration-surface-and-audit-log-cleanup)
  records dynamic Agent mention buttons, compact composer, collapsed/paginated
  audit log, and role-gated finding mutation in local and remote preview.
- [done.md](../done.md#agent-and-supervisor-room-exit-lifecycle)
  records local and remote preview evidence for supervisor leave, Agent
  `leave_room`, owner revoke, audit events, and explicit server-side cleanup
  boundaries.

## Acceptance criteria

- Product UI makes Agent state visible without relying on terminal output.
- External sync uses preview plus owner decision records.
- Private credentials stay in the correct trust boundary.
- The architecture can support other room types after MR review.

## Open questions

- Should Agent Board state live in the main Lighthouse backend from P1, or stay
  in a service boundary first?
- What is the minimum Console UI needed before remote users can evaluate the
  product?
- Which sync adapter should ship first after MR comments?
- How much room history should be retained by default?
