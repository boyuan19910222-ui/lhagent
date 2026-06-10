# Lighthouse Review Room Service

This is a local, dependency-free Review Room product slice for Lighthouse Agent collaboration research.

It models a small instance-side Connector/Relay service:

- SQLite is the Review Room state source.
- The built-in HTML page acts as a lightweight control-plane UI.
- Connector APIs let local and remote Agents join the same Room.
- Token-authenticated connector events write messages and findings into the Room timeline.

## Quick start

```bash
cd experiments/review-room/service
python3 review_room_service.py --host 127.0.0.1 --port 8707 --db ./review-room.sqlite3
```

Open:

```text
http://127.0.0.1:8707
```

## Main flow

1. Click `创建真实 Room` to create a Room with MR context.
2. Click `注册本地 Agent Connector` to create a local Developer Agent connector.
3. Click `注册远端 Agent Connector` to create a remote Reviewer Agent connector.
4. Send a local Agent message or remote Agent finding through connector events.
5. Respond to the finding as Developer Agent.
6. Confirm the finding as a human and generate the MR sync preview.

The demo seed button is intentionally still available, but the primary path is the real Room and connector path.

## HTTP examples

Create a Room:

```bash
curl -X POST http://127.0.0.1:8707/api/rooms \
  -H 'Content-Type: application/json' \
  -d '{
    "title": "MR: add review room",
    "provider": "gitlab",
    "mrUrl": "https://git.example.com/group/repo/-/merge_requests/1",
    "context": {"repository": "group/repo"}
  }'
```

Register a local connector:

```bash
curl -X POST http://127.0.0.1:8707/api/rooms/<room_id>/connectors \
  -H 'Content-Type: application/json' \
  -d '{
    "name": "本地 Codex",
    "kind": "local-agent",
    "agentRole": "developer",
    "endpoint": "http://127.0.0.1:8877/review-room"
  }'
```

Register a remote connector:

```bash
curl -X POST http://127.0.0.1:8707/api/rooms/<room_id>/connectors \
  -H 'Content-Type: application/json' \
  -d '{
    "name": "远端 Reviewer Agent",
    "kind": "remote-agent",
    "agentRole": "reviewer",
    "endpoint": "https://agent.example.com/review-room"
  }'
```

Send a connector message:

```bash
curl -X POST http://127.0.0.1:8707/api/connectors/<connector_id>/events \
  -H 'Content-Type: application/json' \
  -H 'Authorization: Bearer <connector_token>' \
  -d '{
    "type": "message",
    "senderName": "Developer Agent",
    "body": "本地 Agent 已接入 Review Room，正在读取 MR 上下文。"
  }'
```

Send a connector finding:

```bash
curl -X POST http://127.0.0.1:8707/api/connectors/<connector_id>/events \
  -H 'Content-Type: application/json' \
  -H 'Authorization: Bearer <connector_token>' \
  -d '{
    "type": "finding",
    "severity": "P1",
    "filePath": "src/auth/session.ts",
    "line": 87,
    "claim": "权限校验可能被绕过",
    "evidence": "新增 early return 没有检查 role",
    "suggestedFix": "补充 role 校验并增加测试"
  }'
```

## Tests

```bash
python3 -m unittest discover -s experiments/review-room/service/tests -v
```

## Deploying on a Lighthouse instance

Copy this directory to the instance, then run it directly or adapt `lighthouse-review-room.service` as a user-level systemd service.

The service should not be exposed to the public internet without additional controls:

- Room-scoped tokens.
- Webhook secret validation.
- Connector token rotation.
- HTTPS reverse proxy or SSH tunnel.
- MR/IM sync permission scoping.
