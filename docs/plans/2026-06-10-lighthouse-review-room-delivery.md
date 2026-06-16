# Lighthouse Review Room 交付方案

## 核心结论

Review Room 不应该被设计成能远端唤醒本地 Agent 的群聊，也不应该只部署成某台实例里的小服务。推荐形态是：

**Lighthouse 提供托管式 Agent 协作黑板，Agent 通过 Remote MCP 主动读取任务并把外部代码评审结果写入黑板。**

两层职责：

| 层级 | 部署位置 | 职责 |
| --- | --- | --- |
| Review Room Control Plane | Lighthouse 平台侧 PaaS 能力 | Room Board、Message、Task、Finding、Decision、Artifact、身份权限、审计、控制台 UI、MR 评论同步 |
| Review Room MCP/Sync Adapter | 用户 Lighthouse 实例或受控服务 | 私有 Git/IM/Webhook 接入、Remote MCP 转换、MR 评论同步 |

这个拆法既符合 Lighthouse “Agent Infra / 云端 Agent 主机与工作台”的定位，也避免把私有代码、企业 Git、IM token 全部放进平台托管控制面。关键调整是：Review Room 不承诺唤醒未运行的本地 Codex/CodeBuddy；它承诺保存、路由、审计和展示 Agent 在被激活后主动读写的协作状态。

## 方案沉淀

Review Room 这个方案的关键价值不在于“把 Agent 拉进一个聊天室”，而在于把 MR 评审过程抽象成 Lighthouse 托管的 Agent 协作黑板：

- MR 是上下文入口，Room Board 是协作状态源，Task 是可消费工作项，Finding 是结构化评审产物，Decision/人工确认是对外同步边界。
- Lighthouse 平台侧负责 Room Board、参与者、消息、Task、Finding 状态机、审计、权限和控制台体验。
- 用户实例或受控同步适配负责私有 Git、IM token、企业内网和 MR 评论同步，不承担唤醒未激活 Agent 的职责。
- Developer Agent / Reviewer Agent 在各自被用户或官方云端任务控制面激活后，通过 MCP 读取 snapshot/events/tasks，再把观察、修复计划、审计结论或验证结果写回黑板。
- 人类开发者保留最终确认权，再由同步适配发布为 MR 评论、IM 消息或后续流水线状态。

这个方向适合继续产品化，因为它把“多 Agent 参与开发”从一次性的对话，变成了可追踪、可审计、可回放、可被 Agent 主动消费、可接入现有 MR 流程的状态层。它也自然贴合 Lighthouse 的 Agent Infra 定位：Lighthouse 不需要成为最聪明的评审 Agent，也不需要伪装成能唤醒本地 Agent；它要成为 Agent 之间交接上下文、沉淀结论和受人监督交付的共享黑板。

### 适合派发给对面 Agent 的需求

对面 Agent 更适合在被激活后承担只读、评审、复核、设计判断类任务，避免直接改同一批源码造成冲突：

- 读取当前 MR/分支 diff，产出结构化 Review Finding，字段包含 severity、filePath、line、claim、evidence、suggestedFix。
- 复核 Developer Agent 的修复计划，判断是否真正覆盖 finding，指出遗漏测试或风险。
- 针对 Review Room 控制面页面做产品/交互评审，确认是否能解释清楚 Room、MCP Agent、Finding、人工确认这条主线。
- 针对 MCP 和同步适配安全边界做专项审查，例如 token 作用域、Webhook secret、公网暴露、MR 评论同步权限。
- 在修复完成后做二次验收，只给出 pass/fail、剩余 finding 和建议同步到 MR 的评论文本。

Developer Agent 则负责实际代码修改、测试、运行服务、验证 UI 和准备提交。这样的分工不依赖“同时在线聊天”，而是依赖黑板上的 Task、Finding、Decision、Cursor/Ack，让多个 Agent 可以异步接力，同时把冲突控制在 Review Room 的消息和 finding 状态机里。

## 本次交付

### 1. Review Room 产品切片服务

位置：

```text
<workspace>/services/review-room-service
```

当前服务已经不是单纯的 demo API，而是一个本地可运行的共享黑板产品切片：

- SQLite 模拟 Lighthouse Review Room 后端主状态源。
- 内置 HTML 页面模拟 Lighthouse Console Review Room Board。
- Remote MCP 模拟 Agent 的真实接入层。

能力：

- `GET /health`：健康检查。
- `POST /api/demo/session`：创建可直接上手的 MR Review Room 体验房间。
- `POST /api/rooms`：创建 Review Room。
- `GET /api/rooms`：列出 Room。
- `GET /api/rooms/{id}`：读取 Room Board 详情、消息、Task、Finding 和事件。
- `POST /api/rooms/{id}/mcp-invites`：为 Agent 创建 Remote MCP 接入 token。
- `POST /api/rooms/{id}/messages`：写入 Agent 或人工消息。
- `POST /api/rooms/{id}/findings`：写入结构化 Review Finding。
- `PATCH /api/findings/{id}`：更新 Finding 状态。
- `POST /api/findings/{id}/developer-response`：Developer Agent 对 finding 给出处理意见。
- `POST /api/findings/{id}/confirm`：人工确认 finding 并生成 MR 同步记录。
- `POST /api/webhooks/merge-request`：接收 GitLab/GitHub MR 事件并创建 Room。

技术选择：

- Python 标准库 `http.server` + `sqlite3`。
- 无外部依赖，适合全新 Lighthouse 实例。
- SQLite 落盘，便于调研验证和后续迁移。

### 2. 新 Lighthouse 实例部署

实例信息应放在私有 runbook。公开计划只保留可替换占位：

```text
Host: <deployment-host>
HostName: <public-ip>
User: <ssh-user>
```

登录方式：

```bash
ssh <deployment-host>
```

已配置：

- 本机 SSH key：`<private-ssh-key>`
- SSH alias：`<deployment-host>`
- 远端目录：`<service-path>`
- systemd user service：`<service-name>`
- linger：`Linger=yes`

服务状态：

```bash
systemctl --user status <service-name>
curl http://127.0.0.1:<service-port>/health
```

说明：如需公网接入，需要开放安全组或配置 HTTPS 反向代理；具体网络排障记录应放在私有运维文档。

当前可用的本地访问方式：

```bash
ssh -N -L <local-port>:127.0.0.1:<service-port> <deployment-host>
```

然后打开：

```text
http://127.0.0.1:<local-port>
```

### 真实上手路径

打开 Workbench 首页后，优先走真实接入路径：

1. 点击“创建真实 Room”，系统用 MR 标题、仓库和 MR 地址创建 Review Room Board。
2. 在 Agent 卡片点击“复制 MCP 接入话术”，生成 scoped invite token。
3. 在支持 Remote MCP 的 Agent 中添加 `/mcp` 服务并调用 `join_room`。
4. Agent 使用 `post_message`、`post_finding`、`claim_task`、`start_run` 和
   `complete_task` 回写工作。
5. 对 Finding 点击“Developer Agent 回复”和“人工确认并同步”，Room 状态流转到 `completed`。

这个体验对应产品路线 C：先从实例侧 Remote MCP 跑通可感知的黑板写入、Finding、Decision 和审计闭环，再把 Room Board 列表、详情、权限和审计上升到 Lighthouse 托管控制面。

页面仍保留“创建体验房间”作为样例数据入口，但它不再是主路径。

### 3. LH 控制台研究副本

仓库：

```text
/Users/boyuan/Documents/Lighthouse/remote-repos/tea-app-lighthouse
```

新增隐藏路由：

```text
/lighthouse/review-room
```

文件：

```text
src/routes/lighthouse-review-room/ReviewRoomDuck.ts
src/routes/lighthouse-review-room/ReviewRoom.tsx
src/routes/lighthouse-review-room/ReviewRoom.css
src/routes/lighthouse-review-room/index.tsx
src/app.ts
```

控制台页面职责：

- 展示 Review Room 的部署形态。
- 展示实例侧 Connector 状态和 API。
- 展示 MR Review 协作流。
- 提供健康检查和 Connector 打开入口。

遵守的仓库规则：

- 使用 `purify + DuckCmpProps<T>`。
- 新增 `PageDuck`。
- 不使用内联 style。
- 新路由隐藏，不接菜单，不影响现有 OpenClaw/Hermes/MCP 路由。
- 不提交、不推送远端。

## 数据模型

### Room

```json
{
  "id": "room_xxx",
  "title": "MR: add review room",
  "provider": "gitlab",
  "mrUrl": "https://git.example.com/group/repo/-/merge_requests/1",
  "status": "open",
  "context": {},
  "participants": [
    {"type": "human", "name": "开发者", "role": "owner"},
    {"type": "agent", "name": "Developer Agent", "role": "implementer"},
    {"type": "agent", "name": "Reviewer Agent", "role": "reviewer"}
  ]
}
```

### Message

```json
{
  "senderType": "agent",
  "senderName": "Developer Agent",
  "kind": "finding_response",
  "body": "我接受这个 finding，会补充权限校验和测试。",
  "payload": {}
}
```

### Finding

```json
{
  "severity": "P1",
  "status": "needs_developer_response",
  "filePath": "src/auth/session.ts",
  "line": 87,
  "claim": "权限校验可能被绕过",
  "evidence": "新增 early return 没有检查 role",
  "suggestedFix": "补充 role 校验并增加测试",
  "createdBy": "Reviewer Agent"
}
```

## 协作流

1. MR 创建或更新，GitLab/GitHub/工蜂 Webhook 进入 Connector。
2. Connector 创建 Review Room Board，并写入 MR URL、repo、action、参与者和初始上下文。
3. Reviewer Agent 在被激活后读取 Room Board，写入结构化 Finding 或安全审计结论。
4. Developer Agent 在被激活后读取相关 Task/Finding，回复采纳、反驳、修复计划或验证结果。
5. 开发者在 Lighthouse 控制台确认。
6. Connector 把确认后的消息同步到 MR 评论或 IM。

## 后续产品化路线

### P0：研究闭环

- 用现有 Connector 完成 MR Webhook -> Room Board -> Finding / Task -> Agent 主动消费 -> human confirmation 的端到端脚本。
- 增加最小鉴权：room token、Webhook secret。
- 增加 SSH tunnel 或 HTTPS 反代，解决公网访问。
- 增加 per-agent cursor / ack，区分“被提及”“已读取”“已处理”。

### P1：控制面产品化

- Lighthouse 后端托管 Room 状态。
- LH 控制台展示真实 Room 列表、详情、Finding 状态机。
- Connector 只保留私有网络、Webhook、MR/IM 同步和协议 Adapter 能力。
- UI 从“聊天室”改为 Room Board：Context Stream、Agent Inbox、Tasks、Findings / Decisions、Activity Log。

### P2：协议生态

- A2A Adapter：把 Room/Finding/Artifact 映射到 A2A Task/Message/Artifact。
- MCP Server：给 Codex/CodeBuddy 暴露 `get_room_snapshot`、`list_room_events`、`list_tasks`、`post_message`、`post_finding`、`update_task`、`ack_event` 工具。
- IM Adapter：接入企业微信、飞书、QQ、工蜂 MR 评论。

## 验证记录

本地：

```bash
cd <workspace>/services/review-room-service
python3 -m unittest discover -s tests -v
python3 -m py_compile review_room_service.py tests/test_review_room_service.py
```

结果：

```text
Ran 4 tests in 0.019s
OK
```

远端：

```bash
ssh <deployment-host> 'curl -sS http://127.0.0.1:<service-port>/health'
```

结果：

```json
{"ok":true,"service":"lighthouse-review-room"}
```

API 冒烟：

- 创建 Room 成功。
- 写入 P1 Finding 成功。
- 更新 Finding 状态为 `accepted` 成功。
- 读取 Room 详情时可看到 messages 和 findings。

## 当前限制

- 还不是 Lighthouse 平台正式 PaaS，只是实例侧 Connector 和控制台研究入口。
- Review Room 不是远端 Agent 唤醒系统；MCP 接入只提供 Agent 已激活后的读写工具。
- 暂无鉴权，不能直接暴露公网生产使用。
- 暂未接真实 GitLab/工蜂 API token，仅支持 webhook payload ingest。
- 控制台页面为研究态静态状态展示，尚未接真实 CAPI 或 Connector API。
