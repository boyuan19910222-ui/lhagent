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
- Review Room: 74 Python unittest tests passed.

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

- Current lightweight cloud deployment status.
- Remote smoke test against the deployed Review Room service.
- Real remote Agent scenario using the current MCP Remote path.
- Owner-facing cleanup checklist by adapter type.
- Transcript or log pointer behavior across real adapter runs.
