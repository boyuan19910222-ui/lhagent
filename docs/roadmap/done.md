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

## Lighthouse Agent Board local P0

### Workbench CRUD and Terminal Operations UI framework

Status: `Done in local P0 on 2026-06-16`

Evidence:

- [services/review-room-service/review_room_service.py](../../services/review-room-service/review_room_service.py)
- [services/review-room-service/tests/test_review_room_service.py](../../services/review-room-service/tests/test_review_room_service.py)
- [services/review-room-service/tests/test_review_room_p0.py](../../services/review-room-service/tests/test_review_room_p0.py)
- [docs/roadmap/tracks/lighthouse-productization.md](./tracks/lighthouse-productization.md)
- `.venv/bin/python -m py_compile services/review-room-service/review_room_service.py`
- `.venv/bin/python -m unittest discover -s services/review-room-service/tests -p test_review_room_service.py`
- `.venv/bin/python -m unittest discover -s services/review-room-service/tests -p test_review_room_p0.py -k test_workbench_api_create_list_read_and_lifecycle -k test_workbench_lifecycle_api_requires_owner_token_and_confirmation`
- `npm test`: OpenClaw Billing Guardian 16 Node tests passed; Agent Board
  canonical service 51 Python unittest tests passed.
- Browser smoke on `http://127.0.0.1:8707`: Workbench Hall opens, MR Review
  Workbench creation opens detail, workflow rail renders Intake/Review/Fix/
  Verify/Decision, Create Task remains explicit, Context Stream and Activity /
  Audit Log render, desktop and 390px mobile had no horizontal overflow and no
  console or failed-response errors.

Notes:

- Product UI now uses Workbench and Agent Board language while backend
  compatibility keeps room identifiers and existing `/api/rooms` routes.
- `/api/workbenches` supports create, list, and read summaries for the MR Review
  template.
- Rename, archive, restore, and delete are implemented as owner-gated lifecycle
  operations that create audit events.
- Delete creates a server-side Workbench tombstone only; it does not clean
  remote Agent machines, shell history, MCP config, transcripts, logs,
  caches, or workspace files.
- The built-in HTML is still a local P0 productization surface, not the final
  Lighthouse Console product.

### Workbench remote lightweight preview

Status: `Verified preview on 2026-06-16`

Evidence:

- [services/review-room-service/review_room_service.py](../../services/review-room-service/review_room_service.py)
- [services/review-room-service/tests/test_review_room_service.py](../../services/review-room-service/tests/test_review_room_service.py)
- Remote service: `lighthouse-review-room.service` on `ubuntu@124.222.24.34`
  active on port 80.
- `http://124.222.24.34/health`: HTTP 200 with `{"ok": true}`.
- `http://124.222.24.34/api/workbenches`: HTTP 200 after smoke cleanup, with no
  remaining `Codex remote smoke` rooms.
- Remote API smoke: `POST /api/workbenches` returned 201, authenticated
  `GET /api/workbenches/{id}` returned 200, and list summary returned 200.
- Browser smoke on `http://124.222.24.34`: Workbench Hall rendered on desktop
  and 390px mobile, no horizontal overflow, no console errors, and no failed
  responses.
- Chinese-copy browser smoke on local and remote preview: visible Hall and
  Detail copy use Chinese labels for the terminal console, workflow rail,
  actions, panels, metrics, findings, decisions, and audit log; legacy English
  UI phrases were not present in `innerText`.
- `npm test`: OpenClaw Billing Guardian 16 Node tests passed; Agent Board
  canonical service 53 Python unittest tests passed.

Notes:

- Deployment uploaded the current local service file to the existing lightweight
  server and restarted systemd; it did not pull remote code or install
  dependencies.
- Remote preview exposed legacy SQLite schema drift in `agent_runs`,
  `decisions`, `handoffs`, and `threads`. Startup migrations and regression
  tests now cover those older P0 tables.
- Smoke data created during verification was removed from the remote database.
- This is a remote preview deployment, not a complete real remote-Agent
  scenario verification.

### Workbench MCP-only onboarding cleanup

Status: `Verified preview on 2026-06-16`

Evidence:

- [services/review-room-service/review_room_service.py](../../services/review-room-service/review_room_service.py)
- [services/review-room-service/tests/test_review_room_service.py](../../services/review-room-service/tests/test_review_room_service.py)
- [services/review-room-service/README.md](../../services/review-room-service/README.md)
- [docs/roadmap/decisions.md](./decisions.md)
- [docs/roadmap/tracks/connector-and-mcp.md](./tracks/connector-and-mcp.md)
- `.venv/bin/python -m py_compile services/review-room-service/review_room_service.py`
- `.venv/bin/python -m unittest discover -s services/review-room-service/tests -p test_review_room_service.py`
- `.venv/bin/python -m unittest discover -s services/review-room-service/tests -p test_review_room_p0.py -k test_workbench_api_create_list_read_and_lifecycle -k test_workbench_lifecycle_api_requires_owner_token_and_confirmation`
- `npm test`: OpenClaw Billing Guardian 16 Node tests passed; Agent Board
  canonical service 53 Python unittest tests passed.
- Documentation scan for deprecated onboarding terms returned no matches.
- Local browser smoke on `http://127.0.0.1:8710`: Workbench detail showed two
  `复制 MCP 接入话术` buttons, no deprecated onboarding strings in visible text or
  HTML, no console or failed-response errors, and no desktop/mobile horizontal
  overflow.
- Remote deployment to `ubuntu@124.222.24.34` restarted
  `lighthouse-review-room.service`; `http://124.222.24.34/health` returned HTTP
  200 with `{"ok": true}`.
- Remote browser smoke on `http://124.222.24.34`: temporary Workbench detail
  showed two `复制 MCP 接入话术` buttons, no deprecated onboarding strings in
  visible text or HTML, no console or failed-response errors, and no
  desktop/mobile horizontal overflow.

Notes:

- Workbench product UI and current docs now expose MCP invite copy plus `/mcp`
  only for Agent onboarding.
- Backend compatibility names such as `Room` and `connectors` remain where they
  support schema compatibility, MCP identity state, and older tests; they are
  not presented as user-facing setup paths.
- Remote smoke data created for this verification was removed from the remote
  database.

### Workbench human supervisor one-time invite URL

Status: `Verified preview on 2026-06-19`

Evidence:

- [services/review-room-service/review_room_service.py](../../services/review-room-service/review_room_service.py)
- [services/review-room-service/tests/test_review_room_service.py](../../services/review-room-service/tests/test_review_room_service.py)
- [services/review-room-service/tests/test_review_room_p0.py](../../services/review-room-service/tests/test_review_room_p0.py)
- `python -m py_compile services/review-room-service/review_room_service.py`
- `python -m unittest discover -s services/review-room-service/tests -v`: 60
  Python unittest tests passed.
- `npm run test:openclaw-billing-guardian`: 16 Node tests passed.
- Remote deployment to `lighthouse-review-room.service` on
  `ubuntu@124.222.24.34`; `http://124.222.24.34/health` returned HTTP 200.
- Remote HTML smoke showed `detailInviteSupervisor`,
  `supervisorInviteModal`, and `/api/rooms/{roomId}/supervisor-invites`.
- Remote API smoke created a temporary workbench, generated a supervisor URL,
  consumed it once into an `rrs_` access token, read the workbench as a human
  supervisor, rejected second consume with HTTP 403, rejected supervisor
  archive with HTTP 403, and confirmed the public snapshot did not include
  `ownerToken`.
- The temporary remote smoke workbench was removed from the remote SQLite
  database by exact room id.

Notes:

- Supervisor now means a human collaborator. It is invited through a named,
  one-time authorized URL, not through MCP Agent role selection.
- MCP Agent invites keep reviewer, developer, and general Agent roles.
- Public room snapshots strip owner and connector bearer tokens before being
  returned to browser or WebSocket clients.

### Workbench detail collaboration surface and audit log cleanup

Status: `Verified preview on 2026-06-19`

Evidence:

- [services/review-room-service/review_room_service.py](../../services/review-room-service/review_room_service.py)
- [services/review-room-service/tests/test_review_room_service.py](../../services/review-room-service/tests/test_review_room_service.py)
- [services/review-room-service/tests/test_review_room_p0.py](../../services/review-room-service/tests/test_review_room_p0.py)
- [package.json](../../package.json)
- [scripts/test-review-room.mjs](../../scripts/test-review-room.mjs)
- `python -m py_compile services/review-room-service/review_room_service.py`
- `python -m unittest discover -s services/review-room-service/tests -v`: 65
  Python unittest tests passed.
- `npm test`: OpenClaw Billing Guardian 16 Node tests passed; Agent Board
  canonical service 65 Python unittest tests passed.
- Remote deployment to `lighthouse-review-room.service` on
  `ubuntu@124.222.24.34`; `http://127.0.0.1/health` on the host returned
  `{"ok": true}` after restart.
- Remote HTML/API smoke on `http://124.222.24.34`: page contained
  `AUDIT_PAGE_SIZE = 20`, `composer-box`, and `supervisorTokens`; it did not
  contain `????? Agent` or the removed `发现 / 负责人决策` panel.
- Remote API smoke created a temporary workbench, connected Reviewer and
  Developer Agents, created a finding, consumed a supervisor invite, confirmed
  the supervisor could read without `ownerToken` or connector token leakage,
  rejected supervisor message write with HTTP 403, accepted Developer response
  and owner confirmation, and rejected Reviewer confirmation with HTTP 403.
- Remote WebSocket smoke confirmed a Developer connector and owner token from
  room A cannot mutate a finding from room B; both received
  `finding must belong to the same room`.
- Remote smoke data was removed from the remote SQLite database by exact room
  ids after verification.

Notes:

- The message composer now renders `@` buttons from successfully connected
  `room.connectors` instead of hard-coded Reviewer/Developer aliases; when no
  Agent is connected, it renders no placeholder button.
- The send action is a compact `发送` button positioned inside the lower-right
  of the message input.
- The separate right-side `发现 / 负责人决策` panel was removed from the detail
  page. Decisions still remain board state and render with tasks/runs in the
  inspector when present.
- The Activity / Audit Log is collapsed by default, expands on demand, and
  paginates newest-first at 20 events per page.
- Supervisor sessions can post coordination messages and mention Agents, but
  finding, task, invite, lifecycle, and owner-decision writes remain rejected.
- Finding mutation routes are role-gated: Developer responses require a
  Developer connector, and owner confirmation or generic finding updates
  require the owner token.
- WebSocket finding response and confirmation events are scoped to the socket
  room so a token from one room cannot mutate another room's finding.
- Root `npm test` now invokes the canonical Agent Board Python tests through a
  cross-platform Node wrapper instead of a POSIX-only `sh -c` command.

### Real remote MCP Agent Board inbox and messaging scenario

Status: `Verified partial real-Agent scenario on 2026-06-16`

Evidence:

- Deployed Agent Board endpoint: `http://124.222.24.34/mcp`.
- Real board: `room_9ca7dd3449614fc3`.
- Real MCP Agents joined the same board as `评审智能体` with reviewer role and
  `开发智能体` with developer role.
- `评审智能体` successfully called `join_room`, `get_room_snapshot`,
  `heartbeat`, `list_tasks`, `wait_room_events`, and `post_message` through the
  deployed `/mcp` endpoint.
- Owner messages that explicitly mentioned `@评审智能体` created
  high-priority Inbox items with `requiresReply=true`.
- Owner messages that mentioned `@开发智能体` created a high-priority Inbox item
  for the Developer Agent while still entering other Agents' Inbox as normal
  supervision context.
- Normal messages remained discussion only: `list_tasks` stayed empty, no
  `agentRuns` were created, and `评审智能体` did not call task claim/run tools.
- `评审智能体` used only `post_message` for ordinary replies and read MR !965
  only after the owner explicitly allowed read-only access.
- `评审智能体` and `开发智能体` exchanged visible board messages after both Agents
  were connected.

Notes:

- This verifies the real remote MCP message, Inbox, mention, and Agent-to-Agent
  coordination path with activated Agents.
- It does not yet verify task claim, `agent_run`, completion, handoff, or owner
  decision flows with real activated Agents.
- The deployed MCP tool surface used in this scenario did not expose
  `request_owner_confirmation`; the attempted call returned
  `unknown tool: request_owner_confirmation`, so owner confirmation was handled
  in visible board conversation rather than through a first-class decision
  record.

### Full local repository test suite

Status: `Verified on 2026-06-15`

Evidence:

- `npm test`
- OpenClaw Billing Guardian: 16 Node tests passed.
- Lighthouse Agent Board canonical service: 46 Python unittest tests passed.

Notes:

- The command exited successfully in the current working tree.
- Agent Board tests emitted a `ResourceWarning` about an unclosed sqlite
  connection in one WebSocket test, but no test
  failures.

### Canonical Agent Board route convergence

Status: `Done in local P0`

Evidence:

- [services/review-room-service/review_room_service.py](../../services/review-room-service/review_room_service.py)
- [services/review-room-service/review_room_mcp.py](../../services/review-room-service/review_room_mcp.py)
- [services/review-room-service/tests/test_review_room_mcp.py](../../services/review-room-service/tests/test_review_room_mcp.py)
- `./.venv/bin/python -m unittest discover -s services/review-room-service/tests -v`: 46 tests passed.
- `npm test`: OpenClaw Billing Guardian 16 Node tests passed; Agent Board
  canonical service 46 Python unittest tests passed.

Notes:

- Canonical P0 work now lands in `services/review-room-service`.
- `experiments/review-room/service` remains a legacy P0 protocol reference.
- Workbench messages feed Agent Inbox and Context Stream; execution still
  requires Task, Claim, Run, and completion state.

### Local service and core room model

Status: `Done in local P0`

Evidence:

- [docs/concepts/review-room.md](../concepts/review-room.md)
- [experiments/review-room/service/review_room_service.py](../../experiments/review-room/service/review_room_service.py)
- [experiments/review-room/service/tests/test_review_room_service.py](../../experiments/review-room/service/tests/test_review_room_service.py)

Notes:

- The P0 service models rooms, messages, findings, MCP Agent identities,
  developer responses, human confirmation, MR webhook ingestion, and snapshots.

### Explicit task and Agent run loop

Status: `Done in local P0`

Evidence:

- [docs/concepts/review-room-execution-plan.md](../concepts/review-room-execution-plan.md)
- `test_task_assignment_and_agent_run_are_visible_in_room_snapshot`
- `test_claimable_task_requires_claim_before_agent_run`

Notes:

- Owner-created tasks and Agent-started `agent_runs` are present in room
  snapshots.

### MCP identity metadata and bootstrap

Status: `Done in local P0`

Evidence:

- [docs/concepts/review-room-connector-architecture.md](../concepts/review-room-connector-architecture.md)
- `test_agent_invite_defaults_to_mcp_remote`
- `test_agent_invite_creates_invited_agent_member`
- MCP invite and identity tests in the canonical service suite.

Notes:

- Current Workbench UI and docs expose MCP invite copy and `/mcp` only. Older
  non-MCP onboarding evidence is retained in git history, not as current
  product guidance.

### Connector token rotation and disconnect

Status: `Done in local P0`

Evidence:

- `test_rotate_connector_token_invalidates_old_token_without_leaking_audit_secret`
- `test_http_owner_can_rotate_connector_token`
- `test_disconnect_connector_revokes_token`

Notes:

- This proves server-side invalidation behavior. Remote machine cleanup remains
  a separate lifecycle concern.

### Agent and supervisor room exit lifecycle

Status: `Verified remote preview smoke on 2026-06-20`

Evidence:

- `python -m py_compile services\review-room-service\review_room_service.py services\review-room-service\review_room_mcp.py`
- `python -m unittest discover -s services/review-room-service/tests -v`: 80
  Python unittest tests passed.
- `npm test`: OpenClaw Billing Guardian 16 Node tests passed; Agent Board
  canonical service 80 Python unittest tests passed.
- Remote deployment to `lighthouse-review-room.service` on
  `ubuntu@124.222.24.34`; `http://124.222.24.34/health` returned HTTP 200.
- Remote HTML smoke on `http://124.222.24.34` found `supervisorLeaveModal`,
  `agentRevokeModal`, `leave_room`, and the owner revoke endpoint wiring.
- Remote API/MCP smoke room `room_82bca931456c41e9` verified supervisor leave,
  supervisor token invalidation, Developer `get_agent_briefing` role-specific
  capabilities, MCP `leave_room`, blocked tools while disconnected, reconnect
  with `join_room`, owner revoke blocking rejoin, and audit events; the smoke
  room was deleted through the service API after verification.
- `test_supervisor_leave_revokes_session_and_records_audit_event`
- `test_mcp_agent_leave_disconnects_without_revoking_and_can_rejoin`
- `test_owner_revoke_connector_blocks_token_and_records_cleanup_boundary`
- `test_mcp_agent_can_leave_and_must_rejoin_before_tools_work`
- `test_mcp_revoked_agent_cannot_rejoin_or_use_tools`
- `test_mcp_agent_briefing_uses_role_specific_default_capabilities`
- `test_supervisor_session_leave_invalidates_token_and_broadcasts_snapshot`
- `test_owner_revoke_connector_invalidates_agent_token_and_broadcasts_snapshot`

Notes:

- Supervisor leave invalidates only the current supervisor session token,
  removes the human participant, writes `supervisor.left`, broadcasts a room
  snapshot, closes the local UI connection, and clears
  `reviewRoomSupervisorTokens[roomId]`.
- MCP `leave_room` / `review_room.leave_room` sets the connector to
  `disconnected`; the same MCP token can call `join_room` to reconnect, while
  other tools are blocked until rejoin.
- Owner revoke sets the connector to `revoked`; the MCP token cannot rejoin,
  read, post, wait, or execute tools after revocation.
- Agent leave and owner revoke events record active task/run counts and the
  cleanup boundary. Neither action cancels tasks/runs or cleans remote MCP
  config, logs, shell history, caches, workspaces, or local files.
- This is remote preview/API smoke evidence, not a full real remote-Agent
  scenario.

### Agent Board Matrix Terminal visual theme and font stack

Status: `Verified remote preview on 2026-06-20`

Evidence:

- [services/review-room-service/review_room_service.py](../../services/review-room-service/review_room_service.py)
- [services/review-room-service/tests/test_review_room_service.py](../../services/review-room-service/tests/test_review_room_service.py)
- `python -m py_compile services\review-room-service\review_room_service.py`
- `python -m unittest discover -s services/review-room-service/tests -p test_review_room_service.py -v`: 37
  Python unittest tests passed.
- `npm test`: OpenClaw Billing Guardian 16 Node tests passed; Agent Board
  canonical service 82 Python unittest tests passed.
- Local browser smoke on `http://127.0.0.1:8707`: desktop Hall, Workbench
  detail, and 390px mobile rendered with `data-theme="matrix-terminal"`,
  `Share Tech Mono` loaded, terminal and CJK font tokens present, no horizontal
  overflow, and no console/runtime errors.
- Remote deployment to `lighthouse-review-room.service` on
  `ubuntu@124.222.24.34`; `http://124.222.24.34/health` returned HTTP 200.
- Remote HTML/browser smoke on `http://124.222.24.34`: page contained
  `@font-face`, `Share Tech Mono`, `--font-terminal`, `--font-cjk`,
  `data-theme="matrix-terminal"`, `class="matrix-noise"`, and
  `class="terminal-scanline"` with no combined texture-layer class; desktop and
  390px mobile confirmed the font loaded with no horizontal overflow and no
  console/runtime errors.
- Remote backup before deployment:
  `/home/ubuntu/review-room-service/backups/review_room_service.py.20260620-235257.matrix-font-cr.bak`.

Notes:

- The built-in P0 UI now uses a product-grade Matrix Terminal theme: near-black
  surfaces, phosphor green tokens, low-intensity grid/noise/scanline texture,
  green focus/selection glow, amber waiting state, and red dangerous actions.
- `Share Tech Mono` is embedded as a WOFF2 data URI for terminal headings,
  labels, metrics, tags, tabs, and buttons; readable Chinese text and form
  controls keep CJK fallbacks such as `Noto Sans SC` and `Microsoft YaHei UI`.
- This was a visual-theme and font-stack change only. It did not change APIs,
  schemas, MCP tools, routes, room data, task execution semantics, onboarding
  copy, or the MCP-only product boundary.

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
- `npm test`: OpenClaw Billing Guardian 16 Node tests passed; Agent Board 80
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

- Real remote task/run scenario using the current MCP Remote path.
- Owner-facing cleanup checklist by adapter type.
- Transcript or log pointer behavior across real adapter runs.
