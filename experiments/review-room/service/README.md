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

1. 点击“创建话题房间”，服务返回 `ownerToken`，页面保存在本机 localStorage。
2. 在右侧“邀请 Agent”里生成 Reviewer 或 Developer connector，并读取返回的 `bootstrap.command`。
3. Agent 在自己的工作区运行 `codex_connector.py`，用 connector token 进入同一个 WebSocket 房间。
4. owner 在右侧“任务与运行”里选择目标 Agent，填写任务内容，然后点击“分配任务”。
5. 页面会展示 `tasks` 和 `agentRuns`；Agent 完成后，Finding、回复和人工确认仍在同一条 Room 时间线里处理。

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

同时会返回 `adapterType`、`capabilities`、`forbidden` 和 `bootstrap.command`。最简接入方式是把 `bootstrap.command` 复制到有目标 checkout、Python 依赖和 Codex CLI 的机器上执行；真实工作仍发生在该 connector 机器，不发生在 Review Room 后端。

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

### 轮换 Connector token

如果 connector token 泄漏、过期或需要重新分发，owner 可以轮换指定 Agent 的 token。旧 token 会立即失效，已连接的 WebSocket connector 会被断开，新 token 和启动命令只在本次 owner 响应里返回：

```bash
curl -X POST http://127.0.0.1:8707/api/rooms/<room_id>/connectors/<connector_id>/rotate-token \
  -H 'Authorization: Bearer <owner_token>' \
  -H 'Content-Type: application/json' \
  -d '{}'
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
- `task.create`：owner 创建结构化任务。
- `task.created` / `task.assigned`：服务广播任务创建和分配结果。
- `agent_run.start` / `agent_run.started`：connector 开始执行任务并生成运行记录。
- `task.complete` / `task.completed`：connector 完成任务，服务更新任务和运行状态。
- `connector.token_rotated`：owner 轮换 connector token，旧连接会断开并等待新 token 重连。
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

### 用结构化任务触发 Agent

普通消息默认只是聊天，不应该自动触发所有 Agent。owner 应该通过任务路由指定执行者：

```bash
curl -X POST http://127.0.0.1:8707/api/rooms/<room_id>/tasks \
  -H 'Authorization: Bearer <owner_token>' \
  -H 'Content-Type: application/json' \
  -d '{
    "kind": "review",
    "instruction": "评审当前 MR 的鉴权和权限边界。",
    "target": {
      "mode": "connector",
      "connectorId": "<reviewer_connector_id>"
    }
  }'
```

已连接的 connector 收到 `task.assigned` 后会先发送 `agent_run.start`，完成后发送 finding/message/response 和 `task.complete`。Room 快照里的 `tasks` 和 `agentRuns` 会展示当前任务和后台执行状态。内置 Web 页面右侧的“任务与运行”面板调用同一个接口，可作为最简接入路径，不必先手写 curl。

页面右侧 Agent 成员行也提供“轮换 token”。轮换后复制新的启动命令重新启动 connector；旧进程会收到断开事件，旧 token 不能再读取房间或写入事件。

### 真实 Agent 接入测试

真实接入时不要加 `--mock`。Review Room 只负责 Room 状态、WebSocket 和 connector token；两个 Agent 进程在各自工作区调用真实 `codex exec --json`。

建议准备两个独立 checkout 或 worktree：

- Reviewer checkout：只读评审，默认使用 `--sandbox read-only`。
- Developer checkout：执行修复，默认使用 `--sandbox workspace-write`。

先创建 Room 并注册两个 connector：

```bash
BASE=http://124.222.24.34
REPO_NAME=boyuan19910222-ui/lhagent
MR_URL=https://github.com/boyuan19910222-ui/lhagent

ROOM_JSON=$(curl -sS -X POST "$BASE/api/rooms" \
  -H 'Content-Type: application/json' \
  -d '{
    "title":"MR: real agent review",
    "provider":"github",
    "mrUrl":"'"$MR_URL"'",
    "context":{"repository":"'"$REPO_NAME"'"}
  }')

ROOM_ID=$(jq -r '.id' <<< "$ROOM_JSON")
OWNER_TOKEN=$(jq -r '.ownerToken' <<< "$ROOM_JSON")

REVIEWER_JSON=$(curl -sS -X POST "$BASE/api/rooms/$ROOM_ID/connectors" \
  -H "Authorization: Bearer $OWNER_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"name":"Reviewer Agent","kind":"remote-agent","role":"reviewer"}')

DEVELOPER_JSON=$(curl -sS -X POST "$BASE/api/rooms/$ROOM_ID/connectors" \
  -H "Authorization: Bearer $OWNER_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"name":"Developer Agent","kind":"local-agent","role":"developer"}')

REVIEWER_TOKEN=$(jq -r '.connectorToken' <<< "$REVIEWER_JSON")
DEVELOPER_TOKEN=$(jq -r '.connectorToken' <<< "$DEVELOPER_JSON")
REVIEWER_ID=$(jq -r '.id' <<< "$REVIEWER_JSON")
DEVELOPER_ID=$(jq -r '.id' <<< "$DEVELOPER_JSON")
```

启动真实 Reviewer Agent：

```bash
SERVICE=/path/to/lhagent/experiments/review-room/service
REVIEW_REPO=/path/to/reviewer-checkout

cd "$REVIEW_REPO"

"$SERVICE/.venv/bin/python" "$SERVICE/codex_connector.py" \
  --role reviewer \
  --room-url "$BASE" \
  --room-id "$ROOM_ID" \
  --token "$REVIEWER_TOKEN" \
  --workspace "$REVIEW_REPO" \
  --repo "$REPO_NAME" \
  --mr-url "$MR_URL" \
  --task "对比 MR 分支与主干，评审鉴权、权限边界、数据一致性和可执行修复建议" \
  --timeout 600
```

启动真实 Developer Agent：

```bash
SERVICE=/path/to/lhagent/experiments/review-room/service
DEV_REPO=/path/to/developer-checkout

cd "$DEV_REPO"

"$SERVICE/.venv/bin/python" "$SERVICE/codex_connector.py" \
  --role developer \
  --room-url "$BASE" \
  --room-id "$ROOM_ID" \
  --token "$DEVELOPER_TOKEN" \
  --workspace "$DEV_REPO" \
  --repo "$REPO_NAME" \
  --mr-url "$MR_URL" \
  --task "针对 Reviewer Agent finding 进行真实修复，并回传修复摘要与验证结果" \
  --timeout 600
```

owner 触发真实评审：

```bash
curl -sS -X POST "$BASE/api/rooms/$ROOM_ID/tasks" \
  -H "Authorization: Bearer $OWNER_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{
    "kind":"review",
    "instruction":"请基于当前工作区，对比 MR 分支与主干，评审鉴权、权限边界、数据一致性和可执行修复建议。",
    "target":{"mode":"connector","connectorId":"'"$REVIEWER_ID"'"}
  }'
```

查看两个 connector 是否真实在线：

```bash
curl -sS "$BASE/api/rooms/$ROOM_ID" \
  -H "Authorization: Bearer $OWNER_TOKEN" \
  | jq '.connectors[] | {name,agentRole,status,eventCount,lastSeenAt}'
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

### MCP Gateway 实验接口

MCP Gateway 当前是实验性 HTTP 工具面，用来验证 `mcp-remote` adapter 路线。它复用 connector token，不给 owner/guest 伪装成 Agent 的权限。

列出工具和带 trust label 的资源：

```bash
curl http://127.0.0.1:8707/api/mcp/tools
```

读取房间快照：

```bash
curl -X POST http://127.0.0.1:8707/api/mcp/tools/get_snapshot \
  -H 'Authorization: Bearer <reviewer_connector_token>' \
  -H 'Content-Type: application/json' \
  -d '{"roomId":"<room_id>"}'
```

提交结构化 Finding：

```bash
curl -X POST http://127.0.0.1:8707/api/mcp/tools/create_finding \
  -H 'Authorization: Bearer <reviewer_connector_token>' \
  -H 'Content-Type: application/json' \
  -d '{
    "roomId": "<room_id>",
    "severity": "P1",
    "claim": "MCP Gateway 发现权限边界风险",
    "evidence": "该 finding 通过 connector token 和 finding:create capability 写入。",
    "suggestedFix": "继续保持 connector-scoped capability checks。"
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
  -H 'Authorization: Bearer <owner_or_guest_or_connector_token>' \
  -H 'Content-Type: application/json' \
  -d '{
    "kind": "finding_response",
    "body": "我接受这个 finding，会补充权限校验和测试。"
  }'
```

### 添加 Review Finding

```bash
curl -X POST http://127.0.0.1:8707/api/rooms/<room_id>/findings \
  -H 'Authorization: Bearer <reviewer_connector_token>' \
  -H 'Content-Type: application/json' \
  -d '{
    "severity": "P1",
    "filePath": "src/auth/session.ts",
    "line": 87,
    "claim": "权限校验可能被绕过",
    "evidence": "新增 early return 没有检查 role",
    "suggestedFix": "补充 role 校验并增加测试"
  }'
```

### 更新 Finding 状态

```bash
curl -X PATCH http://127.0.0.1:8707/api/findings/<finding_id> \
  -H 'Authorization: Bearer <owner_token>' \
  -H 'Content-Type: application/json' \
  -d '{"status": "accepted"}'
```

### Developer Agent 回复 Finding

```bash
curl -X POST http://127.0.0.1:8707/api/findings/<finding_id>/developer-response \
  -H 'Authorization: Bearer <developer_connector_token>' \
  -H 'Content-Type: application/json' \
  -d '{
    "body": "我接受这个 finding，会补充 webhook secret 校验和测试。"
  }'
```

### 人工确认并生成 MR 同步记录

```bash
curl -X POST http://127.0.0.1:8707/api/findings/<finding_id>/confirm \
  -H 'Authorization: Bearer <owner_token>' \
  -H 'Content-Type: application/json' \
  -d '{
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
WorkingDirectory=/home/ubuntu/lhagent/experiments/review-room/service
ExecStart=/home/ubuntu/lhagent/experiments/review-room/service/.venv/bin/python /home/ubuntu/lhagent/experiments/review-room/service/review_room_service.py --host 0.0.0.0 --port 8707 --db /home/ubuntu/lhagent/experiments/review-room/service/review-room.sqlite3
Restart=always
RestartSec=3

[Install]
WantedBy=default.target
```

## 后续产品化

- 把当前 SQLite 后端迁移为 Lighthouse 托管后端。
- 把当前内置 HTML 页面迁移为 Lighthouse Console Review Room 正式页面。
- 增加更严格鉴权：房间 token、Webhook secret、Agent 身份签名、Connector token rotation。
- 把当前 `tasks` / `agent_runs` 正式迁移到 Lighthouse 托管控制面，继续记录 workspace、sandbox、日志或 transcript，避免后台工作不可见。
- 把结构化任务路由沉淀为正式执行模型：用 `task.create` / `task.assigned` 驱动 Agent 执行，普通聊天消息默认不触发执行。
- 把当前 connector token rotation 扩展成完整凭据生命周期：过期时间、刷新令牌、轮换策略、审计查询和告警。
- 抽象通用 Connector Runtime：把当前 `codex_connector.py` 保留为 Codex adapter 样例，后续支持 CLI、HTTP、A2A、MCP、vendor API 等 adapter。
- 增加托管控制面同步：把本实例 Connector 中的事件转发到 Lighthouse 平台 Room。
- 增加 A2A Adapter：把 `message`、`finding`、`artifact` 映射到 A2A Task/Message/Artifact。
- 增加 MCP Gateway 实验：暴露 `get_snapshot`、`list_tasks`、`claim_task`、`start_run`、`create_finding`、`complete_task` 等工具，并验证远程 MCP、stdio MCP 和无 MCP Agent 的接入差异。

更完整的架构说明见 `docs/concepts/review-room-connector-architecture.md`、`docs/concepts/review-room-protocol.md`、`docs/concepts/review-room-security.md` 和 `docs/concepts/review-room-agent-collaboration.md`。
