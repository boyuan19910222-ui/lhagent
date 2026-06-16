# Track: Lighthouse Productization

Status: `Planned`

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
- connector status and lifecycle controls,
- invite and bootstrap UX,
- audit and sync preview,
- integration settings.

The user-side connector should keep private repo, IM, and Agent execution access
inside the user's trusted environment.

## Workbench CRUD and UI framework

Status: `Planned`

The next productization step is to define the Workbench framework before
building full CRUD. The current P0 already has useful object primitives, but it
does not yet have a complete Workbench management model or Console-grade UI.

Framework first means:

- Treat the Agent Board as a Workbench surface, not a chat room.
- Define Workbench-level lifecycle operations: create, list, read, rename,
  archive, restore, and delete.
- Map existing P0 objects into product surfaces: Context Stream, Agent Inbox,
  Tasks, Findings, Runs, Handoffs, Decisions, Connectors, Threads, and Audit.
- Record which operations are already supported by P0 APIs or MCP tools and
  which are planned for Console CRUD.
- Design the UI information architecture before expanding implementation:
  board list, board detail, object panels, inspector, activity/audit rail, and
  owner action bar.
- Keep deletion and destructive lifecycle actions behind owner confirmation,
  audit records, and clear remote-cleanup boundaries.

Initial capability framing:

- Workbench: create/list/read exist through room APIs; rename/archive/delete are
  planned.
- Messages: create/read exist; edit/delete are not part of the execution path
  and need product policy before implementation.
- Inbox: MCP read/ack states exist; Console inbox UI and batch handling are
  planned.
- Tasks and Runs: create/list/claim/start/complete exist across REST and MCP;
  Console edit, cancel, retry, reassign, and timeline views are planned.
- Findings, Handoffs, and Decisions: core objects exist; Console-first review
  and owner-decision flows need a dedicated UI framework.
- Connectors and Invites: register/invite exist; lifecycle controls such as
  rotate, revoke, disconnect, permissions, and cleanup guidance need product UI.

## Current next actions

- Define the Lighthouse backend data model for rooms, tasks, findings, runs,
  handoffs, decisions, threads, and connectors.
- Draft the Workbench CRUD capability matrix and UI information architecture
  before expanding implementation.
- Decide which parts of the P0 service become product backend and which remain
  prototype-only.
- Sketch the Lighthouse Console room view from the existing built-in HTML
  workflow.
- Define GitHub, GitLab, Gongfeng, Feishu, WeCom, and QQ sync boundaries.
- Decide how room events, audit logs, and transcript links are retained.

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
