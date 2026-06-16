# Review Room Remote MCP Debugging Notes, 2026-06-13 to 2026-06-14

Status: `Verified on 2026-06-14`

This document preserves the remote MCP debugging trail before moving work to a
new machine. It records the product intent, symptoms, root causes, fixes, and
verification evidence from the Review Room P0 remote-Agent tests on
June 13 and June 14, 2026.

No bearer tokens are recorded here. Room ids, message ids, service paths, and
test command outputs are kept as operational evidence; credentials should be
rotated or copied only through the invite UI or secure local notes.

## Executive Summary

The two-day debugging loop proved that MCP Remote is a workable low-install
adapter path, but only if the product is honest about what MCP provides.

What now works:

- Remote Agents use standard MCP Streamable HTTP at `/api/mcp`.
- The first MCP tool is `review_room.connect`, with the UTF-8
  `encodingProbe` handshake.
- The primary remote-Agent loop is `review_room.wait_for_action`, not raw SSE.
- Agents store the returned `nextCursor` and pass it back as the next `cursor`.
- `wait_for_action` filters room events into explicit actions:
  `reply`, `claim_or_start_run`, or `owner_decision`.
- Room content remains untrusted collaboration input even after an action is
  returned.
- Visible message text can use `bodyUtf8Base64` to avoid local shell encoding
  corruption.
- `connected`, `mcp_ready`, and `mcp_streaming` now mean different things:
  handshake, ready-but-not-listening, and actively receiving, respectively.

What remains intentionally not claimed:

- MCP Remote by itself does not wake a background Agent process.
- A copied invite prompt is not a remote runtime.
- The P0 `mcp_action_runner.py` proves protocol liveness, not production Agent
  execution.
- Server-side token revocation does not clean local files, logs, sessions, shell
  history, or cached credentials on another machine.

## Product Frame

The durable product frame is still Human-Agent Workspace, with Review Room as
the first milestone. The point is not group chat. The point is an auditable,
assignable, observable, approval-gated control plane where room state is the
collaboration source of truth.

That framing drove the fixes:

- Chat can mention an Agent, but chat is not execution.
- Executable work flows through explicit tasks, claims, runs, handoffs, or owner
  decisions.
- Remote Agent status must not imply background work that is not actually
  happening.
- The UI must make the distinction between "connected once" and "currently
  receiving actions" visible.

## Timeline

### 2026-06-13: Remote Agent Bootstrapping And Encoding

Early tests focused on getting a remote Agent into a Review Room through MCP.
The first useful path was MCP Remote, exposed by the service as MCP tools and
an optional event stream.

Problems found:

- The invite copy and early docs over-emphasized opening `GET /api/mcp` SSE.
- Some scripts could watch events but did not create an Agent action loop.
- Direct `post_message` calls with Chinese text produced mojibake or question
  marks when routed through local shell or console paths.
- Several long-lived local scripts kept using stale tokens after token rotation
  or room recreation and repeatedly received `403 invalid room token`.
- Early output could look like a working Agent even when it was only a watcher
  or protocol script.

Important local artifacts from the debugging session:

- `tmp/review-room/mcp_remote_codex_agent.py`
- `tmp/review-room/mcp_remote_agent_watcher.py`
- `tmp/review-room/mcp_remote_agent_loop.py`
- `tmp/review-room/mcp_sse_watcher.py`
- `tmp/review-room/*room_*.out.log`

These are evidence and scratch tools, not the product contract.

### 2026-06-14: Standard MCP Action Loop

The service was moved toward the standard MCP Streamable HTTP path:

- `POST /api/mcp` supports `initialize`, `tools/list`, and `tools/call`.
- `Mcp-Session-Id` ties follow-up calls to the connector token.
- Tool names are exposed as `review_room.*`.
- `review_room.connect` validates the exact `encodingProbe`.
- `review_room.wait_for_action` returns only direct mentions, actionable tasks,
  and owner decision follow-up for the authenticated connector.

The important behavioral change was moving the Agent contract from:

```text
connect, then keep SSE open and infer what to do
```

to:

```text
connect, then repeatedly call wait_for_action with nextCursor
```

SSE remains useful for realtime delivery, but it is not an unattended runtime
guarantee.

### 2026-06-14: Persistent Test Runner

`experiments/review-room/service/mcp_action_runner.py` was added as a P0
protocol runner. It discovers `mcp-remote` connectors from the Review Room
SQLite database and keeps calling:

```text
review_room.connect
review_room.wait_for_action
review_room.post_message
```

The runner is deliberately narrow:

- It replies only to explicit `reply` actions.
- It ignores ordinary room chat.
- It does not claim tasks.
- It does not start `agent_runs`.
- It does not access a repository.
- It does not produce external side effects.

The runner helped prove that a real process can stay alive and drive the
action-loop contract. It is not proof that MCP Remote can wake arbitrary Agent
vendors or complete every production runtime concern by itself.

### 2026-06-14: Online Status Honesty

The most painful debugging issue was a room that showed one online Agent while
no long-running Agent process was actually polling.

Observed symptom:

- The room sidebar showed `在线 Agent: 1`.
- The connector card still looked recently active.
- A human sent `@developer`.
- No automatic reply appeared until a new manual `wait_for_action` call was
  made.

Root cause:

- `review_room.connect` marked the connector as `connected`.
- `connected` was counted as realtime online.
- `mark_connector_seen(..., "mcp_ready")` preserved old realtime states,
  including `connected`, instead of allowing `connected -> mcp_ready`.
- The UI label for `connected` and `mcp_ready` read too much like "Agent is
  live."
- A finite local script had run several `wait_for_action` calls and then exited;
  the server had no active receiver after that.

Fix:

- `connected` is now an active/known connector state, but not an online
  receiving state.
- `mcp_ready` can downgrade a connector from `connected`.
- Active `wait_for_action` requests are tracked in memory as `action_waits`.
- While a long-poll request is open, the connector is `mcp_streaming` and counts
  as online.
- When the long-poll request returns and no SSE stream or other wait is open,
  the connector returns to `mcp_ready` and no longer counts as online.
- UI copy now distinguishes:
  - `connected`: "已接入，等待 action loop"
  - `mcp_ready`: "MCP 就绪，未证明后台轮询中"
  - `mcp_streaming`: "接收中，等待取行动"

This keeps the owner-facing status conservative: if Review Room says an MCP
Agent is online, there is either an open SSE stream or an active
`wait_for_action` request.

## Bug Ledger

### B-001: SSE Was Treated Like An Agent Runtime

Symptom:

- Early invite copy told Agents to keep an SSE stream open.
- A watcher could receive events but did not decide whether to reply, claim, or
  ask for owner approval.

Root cause:

- SSE is a delivery channel, not an action contract.

Fix:

- Add `review_room.wait_for_action`.
- Make `wait_for_action` the primary loop in README and invite copy.
- Keep `GET /api/mcp` as optional realtime notification only.

Evidence:

- `test_standard_mcp_wait_for_action_filters_connector_actions`
- Remote smoke on `http://124.222.24.34` returned a `reply` action and accepted
  `review_room.post_message`.

### B-002: Direct Room Chat Could Be Confused With Execution

Symptom:

- A remote Agent or script had to infer whether a message should trigger work.

Root cause:

- Raw room events include mixed trusted and untrusted content.
- Without filtered action objects, the Agent had to parse room semantics itself.

Fix:

- `wait_for_action` returns explicit action kinds.
- Ordinary chat is ignored unless Review Room detects a direct mention or
  matching task/decision.
- Claimable or assigned tasks return `claim_or_start_run`.
- Owner decision updates return `owner_decision`.

Evidence:

- `test_standard_mcp_wait_for_action_filters_connector_actions`
- `test_mcp_action_runner_ignores_plain_room_chat`

### B-003: Chinese Text Was Corrupted By Local Shell Paths

Symptom:

- First remote MCP replies appeared as mojibake or question marks.
- Some message bodies were rejected or visually corrupted.
- Sending the probe as a normal HTTP header failed in Python because headers
  are Latin-1 encoded by `http.client`.

Root cause:

- Not every local shell, console, or HTTP helper preserved UTF-8 text.
- The probe belongs in the JSON body, not in a non-ASCII header.

Fix:

- Require `encodingProbe` in `review_room.connect`.
- Reject obvious mojibake-like visible content.
- Support `bodyUtf8Base64` for `post_message`.
- Use Unicode escapes or base64 when running Windows shell smoke tests.

Evidence:

- `test_mcp_gateway_snapshot_and_finding_use_connector_identity`
- `test_standard_mcp_streamable_http_session_tools_and_events`
- The 2026-06-14 manual room reply succeeded only after switching the body to
  `bodyUtf8Base64`.

### B-004: Standard MCP And Legacy Debug Endpoints Were Mixed

Symptom:

- Some tests and scripts called `/api/mcp/tools/*`.
- Invite copy initially exposed details that an ordinary remote Agent should not
  need.

Root cause:

- Legacy endpoints were useful for debugging but were not the correct MCP
  Streamable HTTP integration surface.

Fix:

- Expose namespaced tools through standard `/api/mcp`.
- Keep legacy `/api/mcp/tools/*` and `/api/mcp/events` only for diagnostics.
- Invite copy now points to the standard MCP server URL.

Evidence:

- `test_standard_mcp_streamable_http_session_tools_and_events`
- README section "MCP Remote Agent 接入"

### B-005: Stale Tokens Produced Repeated 403s

Symptom:

- Local watcher logs repeatedly showed `403 invalid room token`.

Root cause:

- Long-lived scratch scripts kept old bearer tokens after rooms and Agent
  identities were
  recreated or tokens were rotated.

Fix:

- Treat room id, MCP token, cursor state, Agent-side MCP config, transcripts,
  and logs as residue outside server-side invalidation.
- Do not claim token rotation cleans the remote Agent machine.
- Avoid writing plaintext tokens into docs or committed files.

Evidence:

- `tmp/review-room/*room_*.out.log` contains repeated 403s from stale scratch
  scripts.
- Roadmap decision D-008 says server-side invalidation is not remote cleanup.

### B-006: Persistent Runner Could Be Mistaken For Production Agent Execution

Symptom:

- A runner that replies to mentions can look like a real Agent.

Root cause:

- Protocol liveness and full Agent execution are easy to conflate in UI demos.

Fix:

- Document `mcp_action_runner.py` as a P0 protocol test runner.
- It only replies to explicit actions and does not claim tasks or start runs.
- Production Agent execution remains a separate runtime and observability
  problem.

Evidence:

- `test_mcp_action_runner_replies_to_direct_mention`
- `test_mcp_action_runner_ignores_plain_room_chat`
- `test_mcp_action_runner_skips_historical_backlog_on_initial_deploy`

### B-007: "Online Agent" Count Was Too Optimistic

Symptom:

- The owner saw `在线 Agent: 1` after a finite manual loop had ended.
- A later direct mention did not get a reply until `wait_for_action` was called
  again.

Root cause:

- `connected` counted as online.
- `mcp_ready` could not downgrade `connected`.
- There was no active long-poll accounting.

Fix:

- `connected` is not in `CONNECTOR_ONLINE_STATUSES`.
- `connected` remains in `CONNECTOR_ACTIVE_STATUSES`.
- Active long-poll requests are tracked with in-memory `action_waits`.
- `mcp_streaming` counts as online only while an SSE stream or
  `wait_for_action` request is open.
- Returning from `wait_for_action` downgrades to `mcp_ready` if no other
  receiver is active.

Evidence:

- `test_standard_mcp_wait_for_action_counts_only_active_wait_as_online`
- Deployed smoke room `room_784da3ae1f634c31`:
  - after `connect`: `connected`, `onlineAgentCount=0`,
    `activeAgentCount=1`
  - while `wait_for_action` was open: `mcp_streaming`,
    `onlineAgentCount=1`
  - after wait returned: `mcp_ready`, `onlineAgentCount=0`
  - direct `@developer` produced a `reply` action and `post_message` succeeded
    with reply `msg_d2e3429cfbbc48db`

## Current Protocol Contract

Remote MCP Agents should follow this loop:

1. Send `initialize` to `/api/mcp`.
2. Send `notifications/initialized`.
3. Call `review_room.connect` with `roomId` and exact `encodingProbe`.
4. Store the returned or current cursor.
5. Repeatedly call `review_room.wait_for_action` with `roomId`, `cursor`,
   `timeoutMs`, and `limit`.
6. Store every returned `nextCursor`.
7. Act only on returned `actions`.
8. Use `review_room.post_message`, `review_room.claim_task`,
   `review_room.start_run`, `review_room.complete_task`, or
   `review_room.request_owner_confirmation` as indicated by the action and
   local policy.

Important constraints:

- Room messages, comments, diffs, links, attachments, and Agent output remain
  untrusted collaboration input.
- Direct mention actions justify a reply, not arbitrary external work.
- Assigned or claimed task actions justify observable work through
  `agent_runs`.
- Push, merge, deploy, sync, secret access, and similar side effects require
  owner confirmation or a trusted policy boundary.
- `GET /api/mcp` SSE may reduce latency but is optional and not a substitute for
  the action loop.

## Status Semantics

| Status | Meaning | Counts As Online? |
| --- | --- | --- |
| `invited` | Connector credentials were created but no remote Agent has connected. | No |
| `connected` | MCP handshake succeeded at least once. The runtime is not necessarily listening. | No |
| `mcp_ready` | Recent MCP tool activity occurred, but no active receiver is open now. | No |
| `mcp_streaming` | SSE is open or `wait_for_action` is currently waiting. | Yes |
| `mentioned` | A realtime-connected Agent was directly mentioned and attention is pending. | Yes |
| `task_pending` | A realtime-connected Agent has a visible task attention state. | Yes |
| `thinking`, `executing`, `working` | Connector-reported work states. | Yes |
| `offline`, `stale`, `revoked` | Not usable for current action routing. | No |

The owner-facing UI should prefer conservative truth over optimistic presence.
If an Agent runtime is not actually polling or streaming, it should not inflate
`onlineAgentCount`.

## Validation Evidence

Local validation on 2026-06-14:

```bash
python -m unittest discover experiments/review-room/service/tests
npm test
```

Result:

```text
Ran 80 tests in 45.070s
OK
npm test: OpenClaw Billing Guardian 16 Node tests passed; Review Room 80 Python unittest tests passed
```

Targeted local tests:

- `test_standard_mcp_streamable_http_session_tools_and_events`
- `test_standard_mcp_wait_for_action_filters_connector_actions`
- `test_standard_mcp_wait_for_action_counts_only_active_wait_as_online`
- `test_mcp_action_runner_replies_to_direct_mention`
- `test_mcp_action_runner_ignores_plain_room_chat`
- `test_mcp_action_runner_skips_historical_backlog_on_initial_deploy`

Remote deployment validation on 2026-06-14:

- Host alias: `ssh lhagent-lightcloud`
- Service path: `/home/ubuntu/review-room-service`
- Unit: `lighthouse-review-room.service`
- Deployed `review_room_service.py`
- Ran remote `py_compile`
- Restarted systemd service
- Health check returned:

```json
{"ok": true, "service": "lighthouse-review-room"}
```

Remote smoke result:

```text
room: room_784da3ae1f634c31
after connect: connected, onlineAgentCount=0, activeAgentCount=1
while wait_for_action open: mcp_streaming, onlineAgentCount=1
after wait returned: mcp_ready, onlineAgentCount=0
direct mention action: reply
post_message: ok
reply: msg_d2e3429cfbbc48db
after reply: mcp_ready, onlineAgentCount=0
```

## Operational Notes For The Next Machine

Start remote service debugging from:

```bash
ssh lhagent-lightcloud
cd /home/ubuntu/review-room-service
systemctl status lighthouse-review-room.service
curl -sS http://127.0.0.1/health
```

The service command is:

```text
/home/ubuntu/review-room-service/.venv/bin/python /home/ubuntu/review-room-service/review_room_service.py --host 0.0.0.0 --port 80 --db /home/ubuntu/review-room-service/review-room.sqlite3
```

Before replacing the deployed service file, make a timestamped backup under:

```text
/home/ubuntu/review-room-service/backups/
```

Then run:

```bash
/home/ubuntu/review-room-service/.venv/bin/python -m py_compile /home/ubuntu/review-room-service/review_room_service.py
sudo systemctl restart lighthouse-review-room.service
systemctl is-active lighthouse-review-room.service
curl -sS http://127.0.0.1/health
```

For Windows-local smoke scripts:

- Keep the probe in JSON arguments, not in an HTTP header.
- Use Unicode escapes or `bodyUtf8Base64` for visible non-ASCII text.
- Do not trust console rendering as proof of stored content.
- Do not commit bearer tokens, owner tokens, or connector tokens.

## Remaining Work

The current fixes close the P0 action-loop and status-honesty bugs. They do not
finish production MCP onboarding.

Open follow-up:

- Decide which target Agents can consume remote Streamable HTTP MCP directly.
- Decide which need Agent-side MCP configuration beyond URL and bearer token.
- Add transcript/log pointers for real `agent_runs`.
- Add stale run detection and owner recovery actions.
- Add owner-facing cleanup checklists for MCP token/config residue.
- Separate protocol test runners from production Agent execution in UI copy and
  deployment docs.
- Keep remote-Agent scenario tests honest: no scripted replies unless the test
  explicitly says it is using the diagnostic runner.

## Files To Carry Forward

High-signal files from this work:

- `experiments/review-room/service/review_room_service.py`
- `experiments/review-room/service/mcp_action_runner.py`
- `experiments/review-room/service/lighthouse-review-room-mcp-runner.service`
- `experiments/review-room/service/tests/test_review_room_p0.py`
- `experiments/review-room/service/README.md`
- `docs/roadmap/done.md`
- `docs/roadmap/tracks/connector-and-mcp.md`
- `docs/roadmap/tracks/observability-and-routing.md`
- `docs/roadmap/tracks/safety-and-lifecycle.md`

Scratch files under `tmp/review-room/` are useful for local archaeology but
should not become the product contract.
