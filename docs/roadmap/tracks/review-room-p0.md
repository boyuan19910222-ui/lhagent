# Track: Lighthouse Agent Board P0

Status: `In progress`

## Purpose

Keep the Lighthouse Agent Board experiment small, runnable, and honest while it
proves the Human-Agent Workspace primitives. The repository path and protocol
identifiers still use `review-room`; product and UI copy should use Agent Board.

The canonical P0 service lives in:

- [services/review-room-service](../../../services/review-room-service)

The older [experiments/review-room/service](../../../experiments/review-room/service)
tree remains a legacy protocol reference and should not receive new product
features.

Core concept docs:

- [Lighthouse Agent Board](../../concepts/review-room.md)
- [Lighthouse Agent Board Execution Plan](../../concepts/review-room-execution-plan.md)
- [Lighthouse Agent Board Protocol](../../concepts/review-room-protocol.md)

## Current scope

P0 should prove:

- board creation from demo, topic, or MR webhook context,
- owner and guest access,
- Workbench messages that feed every participating Agent's Inbox without
  triggering execution,
- per-Agent Inbox ack states,
- connector registration and token auth,
- explicit task assignment,
- visible Agent run lifecycle,
- structured findings,
- Developer response and human confirmation,
- handoff from Reviewer to Developer,
- verification task after a Developer fix,
- MCP remote tools and event stream,
- scoped Agent deliberation threads,
- owner decisions before external effects.

## What counts as success

- The owner can run the service locally.
- The owner can create a board and invite a real activated Agent.
- The Agent can discover context and tasks without private side channels.
- The Agent does not execute from normal chat alone.
- The board shows tasks, findings, handoffs, decisions, threads, and `agentRuns`.
- The board can explain what is still local-only, experimental, or unverified.

## Current next actions

- Run the full local test suite and update [done.md](../done.md) with verified
  status.
- Keep the service README current with the MCP Remote action loop, status
  semantics, SSE events, and scoped thread workflow.
- Add a compact manual scenario script for owner -> reviewer -> developer ->
  verification -> owner decision.
- Add a "known limitations" section for local P0, remote MCP, encoding, and
  cleanup boundaries.
- Keep root `npm run test:review-room` pointed at the canonical service tests.

## Recent evidence

- [review-room-remote-mcp-debugging-2026-06-13-14.md](../review-room-remote-mcp-debugging-2026-06-13-14.md)
  summarizes the two-day remote MCP debugging trail, including the standard
  action loop, UTF-8 guardrails, persistent test runner, active-wait status
  semantics, deployed smoke tests, and remaining limits.
- `python -m unittest discover experiments/review-room/service/tests` passed
  80 legacy Agent Board tests on 2026-06-14.

## Risks

- The local prototype can look more productized than it is.
- The built-in HTML can become the product UI before Lighthouse Console exists.
- Tests can prove API behavior without proving real Agent ergonomics.
- Remote Agent behavior can drift into scripted demo behavior unless we test
  with real constraints.
