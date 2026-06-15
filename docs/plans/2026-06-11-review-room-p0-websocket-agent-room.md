# Review Room P0 Shared Blackboard

## 核心结论

Review Room P0 先聚焦纯产品能力，不接 Lighthouse 控制台：在 Lighthouse 实例内运行一个 Review Room 后端，提供 Agent 协作黑板、Remote MCP 工具、WebSocket 状态流和兼容 Connector 协议，让 `review room owner` 能监督 `Reviewer Agent` 与 `Developer Agent` 围绕代码评审异步交接上下文、任务、Finding 和 Decision。

重要校准：Review Room 不再承诺“远端主动唤醒本地 Agent”。它是一个持久黑板和审计状态机。Agent 只有在自己已被用户或官方任务控制面激活时，才会主动通过 MCP 读取黑板并回写结果。

## 实现形态

- 后端：`services/review-room-service/review_room_service.py`，使用 `aiohttp` + SQLite。
- Web 页面：服务根路径 `/`，展示 Room Board、Agent Inbox、消息流、Task、Finding / Decision 卡片。
- MCP 协议：`GET/POST /mcp`，给已激活的 Agent 提供 snapshot、events、tasks、message/finding/task 回写工具。
- 实时协议：`GET /ws/rooms/{roomId}?token=...`，用于 Web UI 和兼容客户端刷新状态，不是唤醒未运行 Agent 的机制。
- 鉴权：创建 Room 返回 `ownerToken`；每个 Agent Connector 有独立 `connectorToken`。
- Agent 侧兼容工具：`services/review-room-service/codex_connector.py` 可用于协议验证和调试，但不作为正式产品路线；正式路线不要求用户在 Agent 本地额外部署 runner、daemon 或插件。

## P0 边界

- Review Room 后端只保存 Room Board、Message、Task、Finding、Decision、Connector、确认状态和审计事件。
- 后端不保存 OpenAI/Codex 密钥，不代跑真实 Agent。
- P0 不做 MR 评论回写、不接 Lighthouse Console、不做多节点同步。
- P0 不做本地 Agent 唤醒；`@AgentName` 和 `task.assigned` 只是给 Agent 下次主动读取时消费的路由/工作项。
- 兼容保留旧 REST Connector event 和 WebSocket 入口，但主体验走 Remote MCP 读写黑板。

## 验证

```bash
.venv/bin/python -m unittest discover -s services/review-room-service/tests -v
```

覆盖项：

- owner token 与 connector token 鉴权。
- WebSocket 三角色入房、owner 发起话题、Reviewer 创建 Finding、Developer 回复、owner 确认。
- MCP join、snapshot、events、tasks、post_message、post_finding、update_task。
- Web 页面包含 Room Board 入口、Agent mention controls 和三角色体验。
- Agent 侧 connector 的 URL 生成与 mock reviewer/developer 事件。

## 2026-06-11 当前进展

- 已跑通公网实例 `http://124.222.24.34` 的真实 Agent 接入测试：Web owner 发起话题后，本地 Reviewer connector 通过 `codex exec --json` 读取 `lhagent` 工作区并回写结构化 Finding，Developer connector 收到 Finding 后以 `workspace-write` 模式运行真实 Codex 并回写修复摘要。
- 已确认 P0 的真实链路不再只是 demo：`review room owner -> Reviewer Agent -> Finding -> Developer Agent -> developer_response` 可以在同一个 Room 内闭环。
- 已修复真实接入测试暴露的两个 connector 问题：`service_tier = "default"` 与当前 Codex CLI 不兼容的问题改为本机配置修正；长耗时 `codex exec` 导致 WebSocket 空闲断开的问题通过 connector 内部异步 runner 和 ping keepalive 修正。
- 已补充真实接入运行文档，明确 Reviewer 默认只读 sandbox，Developer 默认 workspace-write sandbox，并要求两个 Agent 使用各自工作区和 connector token 接入。

## 2026-06-15 产品语义校准

- 真实接入测试证明“本地 connector 可以跑通”，但这不应成为正式产品目标。它依赖本地常驻进程，违背 Review Room 作为托管产品应有的边界。
- Remote MCP 证明 Agent 可以主动读取和回写 Room，但 MCP Server 不能反向唤醒 Codex / CodeBuddy 本地 Agent。
- P0 Roadmap 改为共享黑板：Room Board 持久保存上下文、Task、Finding、Decision、审计事件；Agent 在被激活后主动读取和消费。
- Web UI 应从“聊天室”改成“黑板”：Context Stream、Agent Inbox、Tasks、Findings / Decisions、Activity Log。
- 安全审计、权限边界、人工确认、Finding 状态机继续保留，并成为黑板模型的核心价值，而不是聊天体验的附属能力。

## 仍需产品化的问题

- 缺少 per-agent cursor / ack：现在 `mention.requires_reply` 是事件累计，不代表真正未处理。
- 缺少 Agent Inbox：需要把 mentions、assigned tasks、unread findings 聚合成每个 Agent 进入 Room 时的待办。
- 缺少官方云端 Agent 控制面接入：如果要真正自动执行，应接 Codex/CodeBuddy 官方 cloud task 或同类任务入口，而不是要求本地 runner。
- Developer 相关能力正式化前必须有单独 worktree、变更预览、人工确认和回滚策略。
- Review Room 控制面和 connector 的 token/权限边界需要继续收紧：P0 适合验证协作黑板，不应直接视为生产安全边界。
