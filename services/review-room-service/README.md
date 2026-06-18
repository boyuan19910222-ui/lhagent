# Lighthouse Agent Board

这是一个本地可运行的 Lighthouse Agent Board P0 产品切片。它把共享黑板后端、Agent Board UI、Remote MCP Agent 接入和 WebSocket 事件流放在同一个服务目录里，方便验证 Lighthouse 承载多 Agent 代码评审协作状态层的能力。当前目录和 API 仍保留 `review-room` 命名，作为实验路径和兼容协议标识。

## 定位

未来正式产品推荐采用两层形态：

- Lighthouse 托管控制面：Agent Board、Message、Task、Finding、Decision、Artifact、权限、审计、控制台 UI。
- Lighthouse 实例侧 MCP/同步适配：私有网络接入、Webhook 接收、MCP Adapter、对外同步。

本目录当前实现的是一个“单进程产品切片”：

- 用 SQLite 模拟 Lighthouse Agent Board 后端主状态源。
- 用内置 HTML 页面提供 Agent Board：Context Stream、Agent Inbox、Task、Finding / Decision 和 Activity Log。
- 用 `/mcp` 暴露 Remote MCP Server，让支持 Remote MCP 的 Codex / Claude Code / CodeBuddy 以原生工具方式读写 Agent Board。
- 用 WebSocket 让 Web UI 和已连接客户端看到状态变化；它不是让未运行的 Agent 被远端唤醒的机制。
- 用 MCP invite token 区分 Agent 身份；历史 WebSocket 调试脚本不作为正式产品路线或当前用户接入入口。

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

1. 在“工作台大厅”点击“启动 MR 评审工作台”，填写或使用默认 MR 标题、仓库、MR 地址和负责人；服务返回 `ownerToken`，页面保存在本机 localStorage。
2. 在工作台详情点击“邀请智能体”或“复制 MCP 接入话术”，服务通过 `POST /api/rooms/{roomId}/mcp-invites` 创建 scoped invite token。
3. 在 Codex / Claude Code / CodeBuddy 等支持 Remote MCP 的 Agent 中添加 `http://<host>:8707/mcp`，并使用接入话术里的 Bearer token。
4. Agent 调用 `join_room` 后读取 Agent Board；所有监督消息都会进入 Agent Inbox，明确 `@AgentName` 的消息会被标记为高优先级 `requiresReply`，但不会自动唤醒 Agent。
5. Agent 在自己已激活时，通过 `get_room_snapshot`、`list_inbox`、`ack_event` 和 `list_tasks` 主动消费黑板；执行工作必须先 `claim_task` / `start_run`，完成后用 `complete_task` 回写结果；普通回复用 `post_message`，评审结论用 `post_finding`，外部动作先用 `request_owner_confirmation`。

页面也保留一个“创建体验看板”按钮，用于快速注入样例数据：

1. 点击“创建体验看板”，服务会通过 `POST /api/demo/session` 创建一个模拟 MR Agent Board。
2. 在 Board 详情中查看 Review Agent 写入的 P1 finding，包含文件、行号、证据和建议修复。
3. 点击“Developer Agent 回复”，finding 会进入“等待人工确认”状态，并写入 Agent 回复消息。
4. 点击“人工确认并同步”，系统会生成 MR 评论同步记录，Room 状态变为“已完成”。

这个体验对应 C 路线：先从实例侧 Room/MCP 入口跑通真实协作闭环，暂不接 Lighthouse 控制台，后续再上升为托管控制面里的全局 Room 列表、权限、审计和 MR 同步。

## API

### 创建体验看板

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

返回值包含 `id` / `roomId` 和 `ownerToken`。读取 Board、创建 MCP invite、进入 owner WebSocket 都需要 owner token。

### 创建 Workbench

Workbench API 是当前内置 UI 使用的产品化入口，底层仍映射到兼容的 Room 存储。

```bash
curl -X POST http://127.0.0.1:8707/api/workbenches \
  -H 'Content-Type: application/json' \
  -d '{
    "title": "MR: add agent board",
    "repository": "group/repo",
    "mrUrl": "https://git.example.com/group/repo/-/merge_requests/1",
    "owner": "工作台负责人",
    "template": "mr-review"
  }'
```

返回值包含 `ownerToken`。`GET /api/workbenches` 只返回不含 owner token 的列表摘要；
读取详情、重命名、归档、恢复和删除都需要 owner token。删除只生成服务端
Workbench tombstone，不会清理远端 Agent 机器、MCP 配置、日志、缓存或工作区文件。

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

### MCP-only Agent 接入流程

当前产品入口只保留 MCP invite。Owner 为每个 Agent 角色生成 scoped invite token，
Agent 在自己的已激活会话里添加 `http://<host>:8707/mcp`，再通过 MCP tools
进入 Board、读取任务、回写消息、发现和负责人决策请求。

Reviewer invite：

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

Developer invite：

```bash
curl -X POST http://127.0.0.1:8707/api/rooms/<room_id>/mcp-invites \
  -H 'Authorization: Bearer <owner_token>' \
  -H 'Content-Type: application/json' \
  -d '{
    "agentName": "Developer Agent",
    "agentRole": "developer",
    "ttlMs": 86400000
  }'
```

Agent 添加 MCP 后应先调用 `join_room`，再通过 `list_inbox`、
`wait_room_events`、`list_tasks`、`claim_task`、`start_run`、
`complete_task`、`post_message`、`post_finding` 和
`request_owner_confirmation` 推进工作。普通消息只进入上下文流，不自动授权执行。

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

### MCP Agent 写入消息和 Finding

MCP Agent 不通过直连事件 API 写入。普通回复使用 `post_message`，结构化评审结论使用
`post_finding`，需要外部动作时先使用 `request_owner_confirmation` 生成负责人决策记录。

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
- 增加更严格鉴权：Board token、Webhook secret、MCP invite/session token rotation、工具级权限和 Agent 身份签名。
- 增加托管控制面同步：通过受信任的 MCP/同步适配把 MR/Webhook/IM 事件转发到 Lighthouse 平台 Agent Board。
- 将 Agent Inbox 状态继续产品化：per-agent cursor、read/ack/handled/ignored 统计、批量处理和过期策略。
- 暂停新增非 MCP onboarding；A2A/CLI/sidecar 等适配只作为后续研究方向，等 Remote MCP 真实 Agent loop 证明后再重新评估。
- 完善 Remote MCP Server：OAuth、token rotation、工具级权限、跨 Board workspace，以及更细的资源/工具授权策略。
