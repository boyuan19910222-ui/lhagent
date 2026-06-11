# Lighthouse Review Room

这是一个本地可运行的 Lighthouse Review Room P0 产品切片。它把 Review Room 后端、Web 实时聊天室、WebSocket Connector 协议和 Agent 侧 Codex Connector 放在同一个服务目录里，方便先验证 Lighthouse 实例承载多 Agent 代码评审房间的能力。

## 定位

未来正式产品推荐采用两层形态：

- Lighthouse 托管控制面：Room、Finding、Artifact、权限、审计、控制台 UI。
- Lighthouse 实例侧 Connector：私有网络接入、Webhook 接收、本地 Agent Bridge、A2A/MCP Adapter。

本目录当前实现的是一个“单进程产品切片”：

- 用 SQLite 模拟 Lighthouse Review Room 后端主状态源。
- 用内置 HTML 页面提供纯 Review Room Web 聊天室。
- 用 WebSocket 让 `review room owner`、`Reviewer Agent`、`Developer Agent` 实时进入同一个 Room。
- 用 Connector token 区分不同 Agent，真实 Codex/远端 Agent 在各自环境运行 `codex_connector.py`。

Review Room 后端不保存 OpenAI/Codex 密钥，不直接代跑 Agent；真实 Agent 执行发生在 Agent 侧 connector 环境。

## 启动

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python review_room_service.py --host 0.0.0.0 --port 8707 --db ./review-room.sqlite3
```

健康检查：

```bash
curl http://127.0.0.1:8707/health
```

## 直接体验

启动后打开：

```text
http://127.0.0.1:8707
```

真实路径：

1. 点击“创建真实 Room”，填写或使用默认 MR 标题、仓库和 MR 地址；服务返回 `ownerToken`，页面保存在本机 localStorage。
2. 在 Room 里注册 `Reviewer Agent` 和 `Developer Agent` connector，分别生成 `connectorToken`。
3. owner 页面通过 `GET /ws/rooms/{roomId}?token=<ownerToken>` 进入实时聊天室。
4. 两个 Agent 在各自环境运行 `codex_connector.py`，用 connector token 进入同一个 WebSocket 房间。
5. owner 发起代码评审话题，Reviewer Agent 产出 Finding，Developer Agent 回复修复计划，owner 对 Finding / Decision 确认或驳回。

页面也保留一个“创建体验房间”按钮，用于快速注入样例数据：

1. 点击“创建体验房间”，服务会通过 `POST /api/demo/session` 创建一个模拟 MR Review Room。
2. 在 Room 详情中查看 Review Agent 写入的 P1 finding，包含文件、行号、证据和建议修复。
3. 点击“Developer Agent 回复”，finding 会进入“等待人工确认”状态，并写入 Agent 回复消息。
4. 点击“人工确认并同步”，系统会生成 MR 评论同步记录，Room 状态变为“已完成”。

这个体验对应 C 路线：先从实例侧 Connector/Room 入口跑通真实协作闭环，暂不接 Lighthouse 控制台，后续再上升为托管控制面里的全局 Room 列表、权限、审计和 MR 同步。

## API

### 创建体验房间

```bash
curl -X POST http://127.0.0.1:8707/api/demo/session \
  -H 'Content-Type: application/json' \
  -d '{}'
```

### 创建房间

```bash
curl -X POST http://127.0.0.1:8707/api/rooms \
  -H 'Content-Type: application/json' \
  -d '{
    "title": "MR: add review room",
    "provider": "gitlab",
    "mrUrl": "https://git.example.com/group/repo/-/merge_requests/1",
    "participants": [
      {"type": "human", "name": "开发者", "role": "owner"},
      {"type": "agent", "name": "Developer Agent", "role": "implementer"},
      {"type": "agent", "name": "Reviewer Agent", "role": "reviewer"}
    ]
  }'
```

返回值包含 `id` / `roomId` 和 `ownerToken`。读取 Room、注册 Connector、进入 owner WebSocket 都需要 owner token。

### 读取房间快照

```bash
curl http://127.0.0.1:8707/api/rooms/<room_id> \
  -H 'Authorization: Bearer <owner_token>'
```

### 注册 Developer Agent Connector

```bash
curl -X POST http://127.0.0.1:8707/api/rooms/<room_id>/connectors \
  -H 'Authorization: Bearer <owner_token>' \
  -H 'Content-Type: application/json' \
  -d '{
    "name": "Developer Agent",
    "kind": "local-agent",
    "role": "developer"
  }'
```

返回值里会包含 `id`、`token` 和 `connectorToken`。Agent 侧 connector 用这个 token 进入 WebSocket。

### 注册 Reviewer Agent Connector

```bash
curl -X POST http://127.0.0.1:8707/api/rooms/<room_id>/connectors \
  -H 'Authorization: Bearer <owner_token>' \
  -H 'Content-Type: application/json' \
  -d '{
    "name": "Reviewer Agent",
    "kind": "remote-agent",
    "role": "reviewer"
  }'
```

### WebSocket 房间协议

连接：

```text
GET /ws/rooms/<room_id>?token=<owner_or_connector_token>
```

核心事件：

- `room.snapshot`：连接后服务下发完整 Room 快照。
- `message.create`：owner 或 Agent 发消息。
- `message.created`：服务广播已落库消息。
- `finding.create`：Reviewer Agent 提交结构化 Finding。
- `finding.created`：服务广播新 Finding。
- `finding.respond` / `decision.propose`：Developer Agent 回复修复计划。
- `finding.confirm` / `finding.reject`：owner 确认或驳回 Finding / Decision。
- `finding.updated`：服务广播状态变化。
- `presence.updated`：服务广播当前在线角色。

### Agent 侧 Codex Connector

Reviewer Agent：

```bash
.venv/bin/python codex_connector.py \
  --role reviewer \
  --room-url http://127.0.0.1:8707 \
  --room-id <room_id> \
  --token <reviewer_connector_token>
```

Developer Agent：

```bash
.venv/bin/python codex_connector.py \
  --role developer \
  --room-url http://127.0.0.1:8707 \
  --room-id <room_id> \
  --token <developer_connector_token>
```

本地无真实 Codex 时可加 `--mock`，先验证 WebSocket 协作闭环。

### Connector 写入消息

```bash
curl -X POST http://127.0.0.1:8707/api/connectors/<connector_id>/events \
  -H 'Authorization: Bearer <connector_token>' \
  -H 'Content-Type: application/json' \
  -d '{
    "type": "message",
    "senderName": "Developer Agent",
    "body": "本地 Agent 已接入 Review Room，正在读取 MR 上下文。"
  }'
```

### Connector 写入 Finding

```bash
curl -X POST http://127.0.0.1:8707/api/connectors/<connector_id>/events \
  -H 'Authorization: Bearer <connector_token>' \
  -H 'Content-Type: application/json' \
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

### 添加消息

```bash
curl -X POST http://127.0.0.1:8707/api/rooms/<room_id>/messages \
  -H 'Content-Type: application/json' \
  -d '{
    "senderType": "agent",
    "senderName": "Developer Agent",
    "kind": "finding_response",
    "body": "我接受这个 finding，会补充权限校验和测试。"
  }'
```

### 添加 Review Finding

```bash
curl -X POST http://127.0.0.1:8707/api/rooms/<room_id>/findings \
  -H 'Content-Type: application/json' \
  -d '{
    "severity": "P1",
    "filePath": "src/auth/session.ts",
    "line": 87,
    "claim": "权限校验可能被绕过",
    "evidence": "新增 early return 没有检查 role",
    "suggestedFix": "补充 role 校验并增加测试",
    "createdBy": "Reviewer Agent"
  }'
```

### 更新 Finding 状态

```bash
curl -X PATCH http://127.0.0.1:8707/api/findings/<finding_id> \
  -H 'Content-Type: application/json' \
  -d '{"status": "accepted"}'
```

### Developer Agent 回复 Finding

```bash
curl -X POST http://127.0.0.1:8707/api/findings/<finding_id>/developer-response \
  -H 'Content-Type: application/json' \
  -d '{
    "senderName": "Developer Agent",
    "body": "我接受这个 finding，会补充 webhook secret 校验和测试。"
  }'
```

### 人工确认并生成 MR 同步记录

```bash
curl -X POST http://127.0.0.1:8707/api/findings/<finding_id>/confirm \
  -H 'Content-Type: application/json' \
  -d '{
    "senderName": "开发者",
    "decision": "accepted",
    "syncTarget": "MR 评论",
    "body": "同意该修复方向，同步为 MR 评论。"
  }'
```

### 接收 MR Webhook

```bash
curl -X POST http://127.0.0.1:8707/api/webhooks/merge-request \
  -H 'Content-Type: application/json' \
  -d '{
    "object_attributes": {
      "title": "Draft: Review Room",
      "url": "https://git.example.com/group/repo/-/merge_requests/2",
      "action": "open"
    },
    "project": {"path_with_namespace": "group/repo"}
  }'
```

## systemd user service

```ini
[Unit]
Description=Lighthouse Review Room Connector
After=network.target

[Service]
WorkingDirectory=/home/ubuntu/review-room-service
ExecStart=/home/ubuntu/review-room-service/.venv/bin/python /home/ubuntu/review-room-service/review_room_service.py --host 0.0.0.0 --port 8707 --db /home/ubuntu/review-room-service/review-room.sqlite3
Restart=always
RestartSec=3

[Install]
WantedBy=default.target
```

## 后续产品化

- 把当前 SQLite 后端迁移为 Lighthouse 托管后端。
- 把当前内置 HTML 页面迁移为 Lighthouse Console Review Room 正式页面。
- 增加更严格鉴权：房间 token、Webhook secret、Agent 身份签名、Connector token rotation。
- 增加托管控制面同步：把本实例 Connector 中的事件转发到 Lighthouse 平台 Room。
- 增加 A2A Adapter：把 `message`、`finding`、`artifact` 映射到 A2A Task/Message/Artifact。
- 增加 MCP Server：给本地 Codex/CodeBuddy 暴露 `list_rooms`、`post_message`、`post_finding`、`update_finding` 工具。
