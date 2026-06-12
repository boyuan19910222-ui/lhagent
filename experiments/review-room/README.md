# Review Room

## Purpose

This experiment models MR review as a Lighthouse-hosted Agent collaboration Room. Local Developer Agents, remote Reviewer Agents, and humans coordinate through Room messages, structured findings, connector events, Developer Agent responses, and human confirmation.

## Status

`prototype`

The local service is runnable and covered by Python `unittest` tests.

## How to Run

From the repository root:

```bash
npm run test:review-room
python3 -m venv experiments/review-room/service/.venv
experiments/review-room/service/.venv/bin/python -m pip install -r experiments/review-room/service/requirements.txt
experiments/review-room/service/.venv/bin/python experiments/review-room/service/review_room_service.py --host 127.0.0.1 --port 8707
```

Open:

```text
http://127.0.0.1:8707
```

From this experiment directory:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python review_room_service.py --host 127.0.0.1 --port 8707
```

## Main Files

```text
service/review_room_service.py
service/codex_connector.py
service/requirements.txt
service/tests/test_review_room_service.py
service/tests/test_review_room_p0.py
service/tests/test_codex_connector.py
service/README.md
service/lighthouse-review-room.service
```

## Lighthouse Relationship

The intended product shape is a two-layer split:

- Lighthouse control plane hosts Room state, permissions, audit, console UI, and MR sync state.
- User instance or local CLI hosts private connectors for Git, IM, local Agents, remote Reviewer Agents, MCP, and A2A adapters.

## Boundary

This prototype is not a production security boundary. Public deployment needs room-scoped tokens, webhook secret validation, connector token rotation, HTTPS or SSH tunnel controls, and MR/IM permission scoping.

## Concept Doc

See [../../docs/concepts/review-room.md](../../docs/concepts/review-room.md).

Related architecture notes:

- [Review Room Connector Architecture](../../docs/concepts/review-room-connector-architecture.md)
- [Review Room Protocol](../../docs/concepts/review-room-protocol.md)
- [Review Room Security](../../docs/concepts/review-room-security.md)
- [Review Room Agent Collaboration](../../docs/concepts/review-room-agent-collaboration.md)

## Next Steps

- Add webhook secret validation, connector token rotation, and connector version/heartbeat reporting.
- Add first-class `agent_runs` so background Agent work is visible in Review Room.
- Add `task.create` and direct `task.assigned` before normal room messages trigger Agent execution.
- Extract a generic connector runtime or sidecar from the current Codex-specific connector.
- Prototype a Review Room MCP Gateway as one adapter path, not the only connector architecture.
- Move Room listing and Finding state into a real Lighthouse control-plane surface.
