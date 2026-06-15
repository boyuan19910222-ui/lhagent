# Lighthouse Agent Board

这是一个本地可运行的 Lighthouse Agent Board P0 产品切片。它把共享黑板后端、Agent Board UI、Remote MCP Agent 接入、WebSocket 事件流和兼容用 Connector 协议放在同一个服务目录里，方便验证 Lighthouse 承载多 Agent 代码评审协作状态层的能力。当前目录和 API 仍保留 `review-room` 命名，作为实验路径和兼容协议标识。

## 定位

未来正式产品推荐采用两层形态：

- Lighthouse 托管控制面：Agent Board、Message、Task、Finding、Decision、Artifact、权限、审计、控制台 UI。
- Lighthouse 实例侧 Connector：私有网络接入、Webhook 接收、A2A/MCP Adapter、对外同步。

本目录当前实现的是一个“单进程产品切片”：

- 用 SQLite 模拟 Lighthouse Agent Board 后端主状态源。
- 用内置 HTML 页面提供 Agent Board：Context Stream、Agent Inbox、Task、Finding / Decision 和 Activity Log。
- 用 `/mcp` 暴露 Remote MCP Server，让支持 Remote MCP 的 Codex / Claude Code / CodeBuddy 以原生工具方式读写 Agent Board。
- 用 WebSocket 让 Web UI 和已连接客户端看到状态变化；它不是让未运行的 Agent 被远端唤醒的机制。
- 用 Connector token 区分兼容模式 Agent；`codex_connector.py` 仅保留为历史协议验证和调试工具，不作为正式产品路线。

Agent Board 后端不保存 OpenAI/Codex 密钥，不直接代跑 Agent；Remote MCP 只提供 Board 上下文、任务、消息和回写工具。Agent 必须已启动会话或任务，并主动调用 MCP tools。

## 产品边界：共享黑板，不是聊天室

Lighthouse Agent Board 不被定义为“把多个 Agent 拉进一个实时聊天室”。更准确的产品形态是：

```text
Lighthouse Agent Board = Agent 协作黑板 + 审计日志 + 任务 / Finding / Decision 状态机
```

这意味着：

- `@AgentName` 是路由标记和优先级提示，不承诺远端唤醒本地 Agent。
- Agent 只有在自己被用户或官方任务控制面激活后，才会通过 MCP 读取 snapshot、events、tasks 和 findings。
- `post_message` 写入的是可审计上下文，并进入所有参与 Agent 的 Inbox；`@AgentName` 只提升优先级并标记需要回复。
- `task.assigned` 比普通 message 更强，表示某个 Agent 下次进入 Board 时应处理的明确工作项。
- `Finding` / `Decision` 是结构化产物和人工确认边界，仍然是代码评审、安全审计和 MR 同步的核心。
- Lighthouse 不通过在 Agent 本地部署脚本、守护进程或插件来绕开“远端不能凭空唤醒本地 Agent”的边界。

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

1. 点击“创建真实 Board”，填写或使用默认 MR 标题、仓库和 MR 地址；服务返回 `ownerToken`，页面保存在本机 localStorage。
2. 在 Agent 卡片点击“复制 MCP 接入话术”，服务通过 `POST /api/rooms/{roomId}/mcp-invites` 创建 scoped invite token。
3. 在 Codex / Claude Code / CodeBuddy 等支持 Remote MCP 的 Agent 中添加 `http://<host>:8707/mcp`，并使用接入话术里的 Bearer token。
4. Agent 调用 `join_room` 后读取 Agent Board；所有监督消息都会进入 Agent Inbox，明确 `@AgentName` 的消息会被标记为高优先级 `requiresReply`，但不会自动唤醒 Agent。
5. Agent 在自己已激活时，通过 `get_room_snapshot`、`list_inbox`、`ack_event` 和 `list_tasks` 主动消费黑板；执行工作必须先 `claim_task` / `start_run`，完成后用 `complete_task` 回写结果；普通回复用 `post_message`，评审结论用 `post_finding`，外部动作先用 `request_owner_confirmation`。

兼容路径仍可用：在 Board 里注册 `Reviewer Agent` 和 `Developer Agent` connector，分别生成 `connectorToken`，再用 `codex_connector.py` 验证 WebSocket 协议。这个路径不作为正式产品承诺，也不用于绕开本地 Agent 无法被远端唤醒的边界。

页面也保留一个“创建体验 Board”按钮，用于快速注入样例数据：

1. 点击“创建体验 Board”，服务会通过 `POST /api/demo/session` 创建一个模拟 MR Agent Board。
2. 在 Board 详情中查看 Review Agent 写入的 P1 finding，包含文件、行号、证据和建议修复。
3. 点击“Developer Agent 回复”，finding 会进入“等待人工确认”状态，并写入 Agent 回复消息。
4. 点击“人工确认并同步”，系统会生成 MR 评论同步记录，Room 状态变为“已完成”。

这个体验对应 C 路线：先从实例侧 Room/MCP/Connector 入口跑通真实协作闭环，暂不接 Lighthouse 控制台，后续再上升为托管控制面里的全局 Room 列表、权限、审计和 MR 同步。

## API

### 创建体验 Board

```bash
curl -X POST http://127.0.0.1:8707/api/demo/session \
  -H 'Content-Type: application/json' \
  -d '{}'
```

### 创建 Board

```bash
curl -X POST http://127.0.0.1:8707/api/rooms \
  -H 'Content-Type: application/json' \
  -d '{
    "title": "MR: add agent board",
    "provider": "gitlab",
    "mrUrl": "https://git.example.com/group/repo/-/merge_requests/1",
    "participants": [
      {"type": "human", "name": "开发者", "role": "owner"},
      {"type": "agent", "name": "Developer Agent", "role": "implementer"},
      {"type": "agent", "name": "Reviewer Agent", "role": "reviewer"}
    ]
  }'
```

返回值包含 `id` / `roomId` 和 `ownerToken`。读取 Board、注册 Connector、进入 owner WebSocket 都需要 owner token。

### 读取 Board 快照

```bash
curl http://127.0.0.1:8707/api/rooms/<room_id> \
  -H 'Authorization: Bearer <owner_token>'
```

### 创建 Remote MCP invite

```bash
curl -X POST http://127.0.0.1:8707/api/rooms/<room_id>/mcp-invites \
  -H 'Authorization: Bearer <owner_token>' \
  -H 'Content-Type: application/json' \
  -d '{
    "agentName": "Reviewer Agent",
    "agentRole": "reviewer",
    "ttlMs": 86400000
  }'
```

返回值里的 `token` 是给 Remote MCP Agent 使用的 Bearer token。第一版 token 绑定单个 Room 和单个 Agent identity；OAuth、token rotation 和跨 Room workspace 后置。

### 下发 Agent task

```bash
curl -X POST http://127.0.0.1:8707/api/rooms/<room_id>/tasks \
  -H 'Authorization: Bearer <owner_token>' \
  -H 'Content-Type: application/json' \
  -d '{
    "title": "修复鉴权 finding",
    "body": "补 owner token 校验并回写测试结果。",
    "assignedTo": "Developer Agent"
  }'
```

Owner 下发 task 后会写入 `task.assigned` event。Agent 侧必须通过 MCP `claim_task` 领取，再用 `start_run` 创建可见 `agent_run`，最后用 `complete_task` 回写 `completed` / `failed` / `cancelled` 等状态。`update_task` 仅作为旧客户端兼容别名保留。

### Remote MCP endpoint

```text
GET/POST /mcp
Authorization: Bearer <mcp_invite_or_session_token>
```

MCP tools：

- `join_room`
- `get_room_snapshot`
- `list_room_events`
- `wait_room_events`
- `list_inbox`
- `ack_event`
- `list_tasks`
- `create_task`
- `claim_task`
- `start_run`
- `complete_task`
- `post_message`
- `post_finding`
- `propose_handoff`
- `request_owner_confirmation`
- `heartbeat`

Legacy aliases:

- `review_room.*`
- `update_task`

MCP resources：

- `review-room://current/snapshot`
- `review-room://current/messages`
- `review-room://current/findings`
- `review-room://current/tasks`

MCP prompt：

- `review-room-onboarding`

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

### WebSocket Board 协议

连接：

```text
GET /ws/rooms/<room_id>?token=<owner_or_connector_token>
```

核心事件：

- `room.snapshot`：连接后服务下发完整 Board 快照。
- `message.create`：owner 或 Agent 发消息。
- `message.created`：服务广播已落库消息。
- `finding.create`：Reviewer Agent 提交结构化 Finding。
- `finding.created`：服务广播新 Finding。
- `finding.respond` / `decision.propose`：Developer Agent 回复修复计划。
- `finding.confirm` / `finding.reject`：owner 确认或驳回 Finding / Decision。
- `finding.updated`：服务广播状态变化。
- `presence.updated`：服务广播当前在线角色。

### WebSocket Connector 兼容路径

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

### WebSocket Connector 真实 Agent 接入测试

真实接入测试时不要加 `--mock`。这只是协议验证路径：Lighthouse Agent Board 负责 Board 状态、WebSocket 和 connector token；Agent 进程在各自工作区调用真实 Agent CLI。正式产品不应要求用户在 Agent 本地额外部署 runner、daemon 或插件。

建议准备两个独立 checkout 或 worktree：

- Reviewer checkout：只读评审，默认使用 `--sandbox read-only`。
- Developer checkout：执行修复，默认使用 `--sandbox workspace-write`。

先创建 Board 并注册两个 connector：

```bash
BASE=${REVIEW_ROOM_BASE:-http://127.0.0.1:8707}
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
```

启动真实 Reviewer Agent：

```bash
SERVICE=${REVIEW_SERVICE_PATH:-/path/to/review-room-service}
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
SERVICE=${REVIEW_SERVICE_PATH:-/path/to/review-room-service}
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
curl -sS -X POST "$BASE/api/rooms/$ROOM_ID/messages" \
  -H "Authorization: Bearer $OWNER_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{
    "senderType":"human",
    "senderName":"Agent Board owner",
    "kind":"owner_topic",
    "body":"请基于当前工作区，对比 MR 分支与主干，评审鉴权、权限边界、数据一致性和可执行修复建议。"
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
    "body": "本地 Agent 已接入 Lighthouse Agent Board，正在读取 MR 上下文。"
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
      "title": "Draft: Lighthouse Agent Board",
      "url": "https://git.example.com/group/repo/-/merge_requests/2",
      "action": "open"
    },
    "project": {"path_with_namespace": "group/repo"}
  }'
```

## systemd user service

```ini
[Unit]
Description=Lighthouse Agent Board Connector
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

- 把当前 SQLite 后端迁移为 Lighthouse 托管的 Agent Board 后端。
- 把当前内置 HTML 页面迁移为 Lighthouse Console Agent Board：Context Stream、Agent Inbox、Tasks、Findings / Decisions、Activity Log。
- 增加更严格鉴权：Board token、Webhook secret、Agent 身份签名、Connector token rotation。
- 增加托管控制面同步：把实例侧 Connector 的 MR/Webhook/IM 事件转发到 Lighthouse 平台 Agent Board。
- 将 Agent Inbox 状态继续产品化：per-agent cursor、read/ack/handled/ignored 统计、批量处理和过期策略。
- 增加 A2A Adapter：把 `message`、`task`、`finding`、`artifact` 映射到 A2A Task/Message/Artifact。
- 完善 Remote MCP Server：OAuth、token rotation、工具级权限、跨 Board workspace，以及更细的资源/工具授权策略。
