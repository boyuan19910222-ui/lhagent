# Lighthouse Review Room 交付方案

## 核心结论

Review Room 不应该只是一个群聊，也不应该只部署成某台实例里的小服务。推荐形态是：

**Lighthouse 提供托管式 Agent 协作控制面，用户可以在自己的 Lighthouse 实例里部署私有 Connector/Relay。**

两层职责：

| 层级 | 部署位置 | 职责 |
| --- | --- | --- |
| Review Room Control Plane | Lighthouse 平台侧 PaaS 能力 | Room、Message、Finding、Artifact、身份权限、审计、控制台 UI、MR 评论同步 |
| Review Room Connector | 用户 Lighthouse 实例或本地 CLI | 私有 Git/IM 接入、本地 Agent Bridge、远端 Review Agent Adapter、A2A/MCP 转换 |

这个拆法既符合 Lighthouse “Agent Infra / 云端 Agent 主机与工作台”的定位，也避免把私有代码、企业 Git、IM token 全部放进平台托管控制面。

## 方案沉淀

Review Room 这个方案的关键价值不在于“把 Agent 拉进一个聊天室”，而在于把 MR 评审过程抽象成 Lighthouse 托管的 Agent 协作房间：

- MR 是上下文入口，Room 是协作状态源，Finding 是结构化评审产物，人工确认是对外同步边界。
- Lighthouse 平台侧负责 Room、参与者、消息、Finding 状态机、审计、权限和控制台体验。
- 用户实例或本地环境负责 Connector/Relay，保留私有 Git、IM token、企业内网和本地 Agent 运行环境。
- Developer Agent 可以在本地或 IDE 中修复问题，Reviewer Agent 可以在远端持续生成 finding、复核修复计划、补充风险提示。
- 人类开发者保留最终确认权，再由 Connector 同步为 MR 评论、IM 消息或后续流水线状态。

这个方向适合继续产品化，因为它把“多 Agent 参与开发”从一次性的对话，变成了可追踪、可审计、可回放、可接入现有 MR 流程的控制面能力。它也自然贴合 Lighthouse 的 Agent Infra 定位：Lighthouse 不需要成为最聪明的评审 Agent，而是成为 Agent 之间协作、落地和交付的运行环境。

### 适合派发给对面 Agent 的需求

对面 Agent 更适合承担只读、评审、复核、设计判断类任务，避免直接改同一批源码造成冲突：

- 读取当前 MR/分支 diff，产出结构化 Review Finding，字段包含 severity、filePath、line、claim、evidence、suggestedFix。
- 复核 Developer Agent 的修复计划，判断是否真正覆盖 finding，指出遗漏测试或风险。
- 针对 Review Room 控制面页面做产品/交互评审，确认是否能解释清楚 Room、Connector、Finding、人工确认这条主线。
- 针对 Connector 安全边界做专项审查，例如 token 作用域、Webhook secret、公网暴露、MR 评论同步权限。
- 在修复完成后做二次验收，只给出 pass/fail、剩余 finding 和建议同步到 MR 的评论文本。

本地 Developer Agent 则负责实际代码修改、测试、运行服务、验证 UI 和准备提交。这样的分工能让两个 Agent 并行工作，同时把冲突控制在 Review Room 的消息和 finding 状态机里。

## 本次交付

### 1. Review Room 产品切片服务

位置：

```text
/Users/boyuan/Documents/Lighthouse/services/review-room-service
```

当前服务已经不是单纯的 demo API，而是一个本地可运行的产品切片：

- SQLite 模拟 Lighthouse Review Room 后端主状态源。
- 内置 HTML 页面模拟 Lighthouse Console Review Room 控制面。
- Connector API 模拟本地 Agent 和远端 Agent 的真实接入层。

能力：

- `GET /health`：健康检查。
- `POST /api/demo/session`：创建可直接上手的 MR Review Room 体验房间。
- `POST /api/rooms`：创建 Review Room。
- `GET /api/rooms`：列出 Room。
- `GET /api/rooms/{id}`：读取 Room 详情、消息和 Finding。
- `POST /api/rooms/{id}/connectors`：为 Room 注册本地或远端 Agent Connector。
- `POST /api/connectors/{id}/events`：Connector 携带 token 写入消息或 Finding。
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

实例：

```text
Host: lh-review-room
HostName: 124.222.24.34
User: ubuntu
```

登录方式：

```bash
ssh lh-review-room
```

已配置：

- 本机 SSH key：`~/.ssh/id_ed25519_lh_review_room`
- SSH alias：`lh-review-room`
- 远端目录：`/home/ubuntu/review-room-service`
- systemd user service：`lighthouse-review-room.service`
- linger：`Linger=yes`

服务状态：

```bash
systemctl --user status lighthouse-review-room.service
curl http://127.0.0.1:8707/health
```

说明：实例内 `127.0.0.1:8707` 健康检查通过，公网直连 `124.222.24.34:8707` 当前返回外层 502，说明公网链路或安全策略未放通。后续如需公网接入，需要开放安全组或配置 HTTPS 反向代理。

当前可用的本地访问方式：

```bash
ssh -N -L 8707:127.0.0.1:8707 lh-review-room
```

然后打开：

```text
http://127.0.0.1:8707
```

### 真实上手路径

打开 Connector 首页后，优先走真实接入路径：

1. 点击“创建真实 Room”，系统用 MR 标题、仓库和 MR 地址创建 Review Room。
2. 点击“注册本地 Agent Connector”，生成本地 Codex/IDE Agent 使用的 connector id 和 token。
3. 点击“注册远端 Agent Connector”，生成远端 Reviewer Agent 使用的 connector id 和 token。
4. 点击 Connector 卡片上的“发送本地 Agent 消息”和“发送远端 Agent Finding”，事件会通过 `/api/connectors/{connectorId}/events` 进入同一个 Room。
5. 对远端 Finding 点击“Developer Agent 回复”和“人工确认并同步”，Room 状态流转到 `completed`。

这个体验对应产品路线 C：先从实例侧 Connector 跑通可感知闭环，再把 Room 列表、详情、权限和审计上升到 Lighthouse 托管控制面。

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
2. Connector 创建 Review Room，并写入 MR URL、repo、action、参与者。
3. CR 人员的 Reviewer Agent 写入结构化 Finding。
4. 本地 Codex/CodeBuddy 通过 Bridge 拉取 Finding，回复采纳、反驳或修复计划。
5. 开发者在 Lighthouse 控制台确认。
6. Connector 把确认后的消息同步到 MR 评论或 IM。

## 后续产品化路线

### P0：研究闭环

- 用现有 Connector 完成 MR Webhook -> Room -> Finding -> Developer Agent response -> human confirmation 的端到端脚本。
- 增加最小鉴权：room token、Webhook secret。
- 增加 SSH tunnel 或 HTTPS 反代，解决公网访问。

### P1：控制面产品化

- Lighthouse 后端托管 Room 状态。
- LH 控制台展示真实 Room 列表、详情、Finding 状态机。
- Connector 只保留私有网络和 Agent Adapter 能力。

### P2：协议生态

- A2A Adapter：把 Room/Finding/Artifact 映射到 A2A Task/Message/Artifact。
- MCP Server：给 Codex/CodeBuddy 暴露 `list_rooms`、`post_message`、`post_finding`、`update_finding` 工具。
- IM Adapter：接入企业微信、飞书、QQ、工蜂 MR 评论。

## 验证记录

本地：

```bash
cd /Users/boyuan/Documents/Lighthouse/services/review-room-service
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
ssh lh-review-room 'curl -sS http://127.0.0.1:8707/health'
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
- 暂无鉴权，不能直接暴露公网生产使用。
- 暂未接真实 GitLab/工蜂 API token，仅支持 webhook payload ingest。
- 控制台页面为研究态静态状态展示，尚未接真实 CAPI 或 Connector API。
