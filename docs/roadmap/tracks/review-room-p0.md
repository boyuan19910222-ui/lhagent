# Track: Review Room P0

Status: `In progress`

## Purpose

Keep the Review Room experiment small, runnable, and honest while it proves the
Human-Agent Workspace primitives.

The P0 service lives in:

- [experiments/review-room/service](../../../experiments/review-room/service)

Core concept docs:

- [Review Room](../../concepts/review-room.md)
- [Review Room Execution Plan](../../concepts/review-room-execution-plan.md)
- [Review Room Protocol](../../concepts/review-room-protocol.md)

## Current scope

P0 should prove:

- room creation from demo, topic, or MR webhook context,
- owner and guest access,
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
- The owner can create a room and invite a real Agent.
- The Agent can discover context and tasks without private side channels.
- The Agent does not execute from normal chat alone.
- The room shows tasks, findings, handoffs, decisions, threads, and `agentRuns`.
- The room can explain what is still local-only, experimental, or unverified.

## Current next actions

- Run the full local test suite and update [done.md](../done.md) with verified
  status.
- Keep the service README current with the MCP Remote action loop, status
  semantics, SSE events, and scoped thread workflow.
- Add a compact manual scenario script for owner -> reviewer -> developer ->
  verification -> owner decision.
- Add a "known limitations" section for local P0, remote MCP, encoding, and
  cleanup boundaries.

## Recent evidence

- [review-room-remote-mcp-debugging-2026-06-13-14.md](../review-room-remote-mcp-debugging-2026-06-13-14.md)
  summarizes the two-day remote MCP debugging trail, including the standard
  action loop, UTF-8 guardrails, persistent test runner, active-wait status
  semantics, deployed smoke tests, and remaining limits.
- `python -m unittest discover experiments/review-room/service/tests` passed
  80 Review Room tests on 2026-06-14.

## Risks

- The local prototype can look more productized than it is.
- The built-in HTML can become the product UI before Lighthouse Console exists.
- Tests can prove API behavior without proving real Agent ergonomics.
- Remote Agent behavior can drift into scripted demo behavior unless we test
  with real constraints.
