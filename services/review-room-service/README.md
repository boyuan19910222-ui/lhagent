# Lighthouse Review Room

这是一个本地可运行的 Lighthouse Review Room 产品切片。它把 Lighthouse Review Room 后端、控制面页面、Connector 注册和 Agent 事件接入放在同一个无依赖服务里，方便先真实体验完整链路。

## 定位

未来正式产品推荐采用两层形态：

- Lighthouse 托管控制面：Room、Finding、Artifact、权限、审计、控制台 UI。
- Lighthouse 实例侧 Connector：私有网络接入、Webhook 接收、本地 Agent Bridge、A2A/MCP Adapter。

本目录当前实现的是一个“单进程产品切片”：

- 用 SQLite 模拟 Lighthouse Review Room 后端主状态源。
- 用内置 HTML 页面模拟 Lighthouse Console 的 Review Room 控制面。
- 用 Connector API 模拟本地 Agent 和远端 Agent 的接入层。

为了便于在全新 Lighthouse 实例或本机直接运行，它只依赖 Python 标准库和 SQLite。

## 启动

```bash
python3 review_room_service.py --host 0.0.0.0 --port 8707 --db ./review-room.sqlite3
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

1. 点击“创建真实 Room”，填写或使用默认 MR 标题、仓库和 MR 地址。
2. 在 Room 详情里点击“注册本地 Agent Connector”，生成本地 Agent 的 connector id 和 token。
3. 点击“注册远端 Agent Connector”，生成远端 Review Agent 的 connector id 和 token。
4. 在 Connector 卡片里点击“发送本地 Agent 消息”和“发送远端 Agent Finding”，观察它们进入同一个 Room 时间线。
5. 对远端 Finding 点击“Developer Agent 回复”和“人工确认并同步”，完成 Review Room 状态闭环。

页面也保留一个“创建体验房间”按钮，用于快速注入样例数据：

1. 点击“创建体验房间”，服务会通过 `POST /api/demo/session` 创建一个模拟 MR Review Room。
2. 在 Room 详情中查看 Review Agent 写入的 P1 finding，包含文件、行号、证据和建议修复。
3. 点击“Developer Agent 回复”，finding 会进入“等待人工确认”状态，并写入 Agent 回复消息。
4. 点击“人工确认并同步”，系统会生成 MR 评论同步记录，Room 状态变为“已完成”。

这个体验对应 C 路线：先从实例侧 Connector/Room 入口跑通真实协作闭环，后续再上升为 Lighthouse 托管控制面里的全局 Room 列表和详情页。

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

### 注册本地 Agent Connector

```bash
curl -X POST http://127.0.0.1:8707/api/rooms/<room_id>/connectors \
  -H 'Content-Type: application/json' \
  -d '{
    "name": "本地 Codex Agent",
    "kind": "local-agent",
    "agentRole": "developer",
    "endpoint": "http://127.0.0.1:8877/review-room"
  }'
```

返回值里会包含 `id` 和 `token`。本地 Agent 后续用这个 token 写入 Room。

### 注册远端 Agent Connector

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
ExecStart=/usr/bin/python3 /home/ubuntu/review-room-service/review_room_service.py --host 0.0.0.0 --port 8707 --db /home/ubuntu/review-room-service/review-room.sqlite3
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
