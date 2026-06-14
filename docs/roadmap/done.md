# Done

This file records completed work with evidence. Some items are marked
`Done in local P0` when code and tests exist in the local experiment but remote
or product verification is still needed.

## Roadmap

### Roadmap v0

Status: `Done`

Evidence:

- [docs/roadmap/README.md](./README.md)
- [docs/roadmap/product-thesis.md](./product-thesis.md)
- [docs/roadmap/milestones.md](./milestones.md)
- [docs/roadmap/decisions.md](./decisions.md)

### Repository Agent guide

Status: `Done`

Evidence:

- [AGENTS.md](../../AGENTS.md)
- [Agent.md](../../Agent.md)

Notes:

- `AGENTS.md` is the canonical repository-level guide for future Agents.
- `Agent.md` is a compatibility pointer for tools or humans looking for the
  singular filename.

## Review Room local P0

### Full local repository test suite

Status: `Verified on 2026-06-14`

Evidence:

- `npm test`
- OpenClaw Billing Guardian: 16 Node tests passed.
- Review Room: 80 Python unittest tests passed.

Notes:

- The command exited successfully in the current working tree.
- Review Room tests emitted a few asyncio slow-task diagnostics, but no test
  failures.

### Local service and core room model

Status: `Done in local P0`

Evidence:

- [docs/concepts/review-room.md](../concepts/review-room.md)
- [experiments/review-room/service/review_room_service.py](../../experiments/review-room/service/review_room_service.py)
- [experiments/review-room/service/tests/test_review_room_service.py](../../experiments/review-room/service/tests/test_review_room_service.py)

Notes:

- The P0 service models rooms, messages, findings, connectors, developer
  responses, human confirmation, MR webhook ingestion, and snapshots.

### Explicit task and Agent run loop

Status: `Done in local P0`

Evidence:

- [docs/concepts/review-room-execution-plan.md](../concepts/review-room-execution-plan.md)
- `test_task_assignment_and_agent_run_are_visible_in_room_snapshot`
- `test_claimable_task_requires_claim_before_agent_run`

Notes:

- Owner-created tasks and connector-started `agent_runs` are present in room
  snapshots.

### Connector registration, metadata, and bootstrap

Status: `Done in local P0`

Evidence:

- [docs/concepts/review-room-connector-architecture.md](../concepts/review-room-connector-architecture.md)
- `test_registers_local_and_remote_agent_connectors_for_room`
- `test_agent_invite_creates_invited_agent_member`
- `test_agent_invite_can_request_codex_sidecar_adapter`

Notes:

- Agent invites default toward `mcp-remote` while allowing explicit
  `codex-sidecar` compatibility.

### Connector token rotation and disconnect

Status: `Done in local P0`

Evidence:

- `test_rotate_connector_token_invalidates_old_token_without_leaking_audit_secret`
- `test_http_owner_can_rotate_connector_token`
- `test_disconnect_connector_revokes_token`

Notes:

- This proves server-side invalidation behavior. Remote machine cleanup remains
  a separate lifecycle concern.

### Reviewer-to-Developer handoff

Status: `Done in local P0`

Evidence:

- [docs/concepts/review-room-agent-collaboration.md](../concepts/review-room-agent-collaboration.md)
- `test_handoff_acceptance_converts_finding_to_developer_task`
- `test_http_handoff_acceptance_creates_developer_task`

Notes:

- Reviewer handoff remains a visible room object until owner acceptance converts
  it into Developer work.

### Automatic verification task after fix

Status: `Done in local P0`

Evidence:

- `test_fix_completion_creates_reviewer_verification_task`
- `test_mcp_complete_task_creates_verification_after_handoff_fix`

Notes:

- Fix completion can create a follow-up Reviewer verification task tied to the
  source finding and handoff.

### Claimable tasks

Status: `Done in local P0`

Evidence:

- `test_claimable_task_requires_matching_connector_claim_before_run`
- `test_concurrent_claim_only_assigns_one_connector`
- `test_http_claim_task_before_run`

Notes:

- Open work requires an eligible connector claim before execution.

### MCP Remote tools and event stream

Status: `Done in local P0`

Evidence:

- [docs/concepts/review-room-connector-architecture.md](../concepts/review-room-connector-architecture.md)
- `test_mcp_gateway_snapshot_and_finding_use_connector_identity`
- `test_mcp_poll_events_returns_room_content_by_cursor`
- `test_mcp_event_stream_pushes_room_content_realtime`
- `test_standard_mcp_streamable_http_session_tools_and_events`

Notes:

- Local P0 includes MCP tools for snapshot, events, tasks, claims, runs,
  messages, findings, handoff proposals, completions, and owner confirmation.

### MCP Remote tool-driven action loop

Status: `Verified on 2026-06-14`

Evidence:

- [experiments/review-room/service/review_room_service.py](../../experiments/review-room/service/review_room_service.py)
- [experiments/review-room/service/tests/test_review_room_p0.py](../../experiments/review-room/service/tests/test_review_room_p0.py)
- [docs/roadmap/review-room-remote-mcp-debugging-2026-06-13-14.md](./review-room-remote-mcp-debugging-2026-06-13-14.md)
- `test_standard_mcp_wait_for_action_filters_connector_actions`
- `python -m unittest discover experiments/review-room/service/tests`: Review
  Room 80 Python unittest tests passed.
- Deployed smoke test on `http://124.222.24.34`: standard MCP `tools/list`
  exposed `review_room.wait_for_action`, `review_room.connect` returned
  `next.actionTool = review_room.wait_for_action`, `wait_for_action` returned a
  `reply` action for `@developer`, and `review_room.post_message` succeeded.

Notes:

- Remote MCP Agents now use a tool-driven action loop:
  `review_room.connect` followed by repeated `review_room.wait_for_action`
  calls with the returned `nextCursor`.
- SSE remains optional realtime delivery and is not described as an unattended
  Agent runtime wakeup guarantee.
- The deployed smoke used an isolated test room. A full real remote-Agent
  scenario remains separate verification.

### MCP Remote active-wait status honesty

Status: `Verified on 2026-06-14`

Evidence:

- [experiments/review-room/service/review_room_service.py](../../experiments/review-room/service/review_room_service.py)
- [experiments/review-room/service/tests/test_review_room_p0.py](../../experiments/review-room/service/tests/test_review_room_p0.py)
- [docs/roadmap/review-room-remote-mcp-debugging-2026-06-13-14.md](./review-room-remote-mcp-debugging-2026-06-13-14.md)
- `test_standard_mcp_wait_for_action_counts_only_active_wait_as_online`
- `python -m unittest discover experiments/review-room/service/tests`: Review
  Room 80 Python unittest tests passed.
- Deployed smoke test on `http://124.222.24.34`, room
  `room_784da3ae1f634c31`: after `connect`, connector status was `connected`
  with `onlineAgentCount=0`; while `wait_for_action` was open, status was
  `mcp_streaming` with `onlineAgentCount=1`; after the wait returned, status was
  `mcp_ready` with `onlineAgentCount=0`; a direct `@developer` produced a
  `reply` action and `review_room.post_message` created
  `msg_d2e3429cfbbc48db`.

Notes:

- `connected` means the MCP handshake succeeded; it no longer means the Agent
  runtime is actively receiving actions.
- `mcp_ready` means recent MCP tool activity without a currently open receiver.
- `mcp_streaming` means an SSE stream or `wait_for_action` long-poll request is
  open and is the only MCP-ready state counted as online.
- This fixes the misleading UI state where a finite manual loop could exit
  while the room still reported one online Agent.

### MCP Remote persistent test runner

Status: `Verified on 2026-06-14`

Evidence:

- [experiments/review-room/service/mcp_action_runner.py](../../experiments/review-room/service/mcp_action_runner.py)
- [experiments/review-room/service/tests/test_review_room_p0.py](../../experiments/review-room/service/tests/test_review_room_p0.py)
- `test_mcp_action_runner_replies_to_direct_mention`
- `test_mcp_action_runner_ignores_plain_room_chat`
- `test_mcp_action_runner_skips_historical_backlog_on_initial_deploy`
- `npm test`: OpenClaw Billing Guardian 16 Node tests passed; Review Room 80
  Python unittest tests passed.
- Deployed smoke test on `http://124.222.24.34`: systemd service
  `lighthouse-review-room-mcp-runner.service` was active, fresh room
  `room_4b664642de96438b` received a diagnostic Reviewer Agent reply
  `msg_4c4e854f3e8740ca` to `@reviewer 测试常驻 runner`, and a follow-up plain
  message did not create another runner reply.

Notes:

- The runner is a protocol-level P0 test Agent. It proves a persistent runtime
  can keep calling `review_room.wait_for_action` and reply through
  `review_room.post_message`.
- It does not run Codex, claim tasks, start runs, access a repository, or create
  external side effects. Production-grade remote Agent execution remains a
  separate connector-runtime concern.

### Owner confirmation and decision records

Status: `Done in local P0`

Evidence:

- `test_mcp_request_owner_confirmation_creates_decision_record`

Notes:

- MCP-style connectors can ask for owner approval without directly executing
  external side effects.

### Scoped Agent deliberation threads

Status: `Done in local P0`

Evidence:

- [docs/concepts/review-room-agent-collaboration.md](../concepts/review-room-agent-collaboration.md)
- `test_scoped_thread_records_messages_and_summary`
- `test_rest_scoped_threads_limit_participants_and_summarize_to_owner_decision`

Notes:

- Threads are participant-scoped, turn-limited, visible in room state, and can
  summarize into owner decision state.

### UTF-8 and mojibake guardrails for MCP content

Status: `Done in local P0`

Evidence:

- `test_mcp_gateway_snapshot_and_finding_use_connector_identity`

Notes:

- Tests cover rejection of mojibake-like content and support base64 UTF-8 body
  fields for shell-sensitive paths.

## Needs verification

These are not complete until current evidence is refreshed:

- Real remote Agent scenario using the current MCP Remote path.
- Owner-facing cleanup checklist by adapter type.
- Transcript or log pointer behavior across real adapter runs.
