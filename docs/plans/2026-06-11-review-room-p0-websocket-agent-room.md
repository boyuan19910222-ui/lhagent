# Review Room P0 WebSocket Agent Room

## 核心结论

Review Room P0 先聚焦纯产品能力，不接 Lighthouse 控制台：在 Lighthouse 实例内运行一个 Review Room 后端，提供 Web 实时聊天室、WebSocket Connector 协议和 Agent 侧 Codex Connector，让 `review room owner` 能监督 `Reviewer Agent` 与 `Developer Agent` 围绕代码评审话题协作。

## 实现形态

- 后端：`services/review-room-service/review_room_service.py`，使用 `aiohttp` + SQLite。
- Web 页面：服务根路径 `/`，展示三角色、实时消息流和 Finding / Decision 卡片。
- 实时协议：`GET /ws/rooms/{roomId}?token=...`。
- 鉴权：创建 Room 返回 `ownerToken`；每个 Agent Connector 有独立 `connectorToken`。
- Agent 侧：`services/review-room-service/codex_connector.py` 在 Agent 自己的环境运行，连接 WebSocket，并在本地调用 mock 或 Codex 命令。

## P0 边界

- Review Room 后端只保存 Room、Message、Finding、Connector、确认状态。
- 后端不保存 OpenAI/Codex 密钥，不代跑真实 Agent。
- P0 不做 MR 评论回写、不接 Lighthouse Console、不做多节点同步。
- 兼容保留旧 REST Connector event 入口，但主体验走 WebSocket。

## 验证

```bash
.venv/bin/python -m unittest discover -s services/review-room-service/tests -v
```

覆盖项：

- owner token 与 connector token 鉴权。
- WebSocket 三角色入房、owner 发起话题、Reviewer 创建 Finding、Developer 回复、owner 确认。
- Web 页面包含实时房间入口和三角色体验。
- Agent 侧 connector 的 URL 生成与 mock reviewer/developer 事件。

## 2026-06-11 当前进展

- 已跑通公网实例 `http://124.222.24.34` 的真实 Agent 接入测试：Web owner 发起话题后，本地 Reviewer connector 通过 `codex exec --json` 读取 `lhagent` 工作区并回写结构化 Finding，Developer connector 收到 Finding 后以 `workspace-write` 模式运行真实 Codex 并回写修复摘要。
- 已确认 P0 的真实链路不再只是 demo：`review room owner -> Reviewer Agent -> Finding -> Developer Agent -> developer_response` 可以在同一个 Room 内闭环。
- 已修复真实接入测试暴露的两个 connector 问题：`service_tier = "default"` 与当前 Codex CLI 不兼容的问题改为本机配置修正；长耗时 `codex exec` 导致 WebSocket 空闲断开的问题通过 connector 内部异步 runner 和 ping keepalive 修正。
- 已补充真实接入运行文档，明确 Reviewer 默认只读 sandbox，Developer 默认 workspace-write sandbox，并要求两个 Agent 使用各自工作区和 connector token 接入。

## 仍需产品化的问题

- 当前 connector 只在最终结果出来后回写 Room，中间没有“Agent 正在分析 / 正在修复”的进度事件。真实任务中 Reviewer 约 2 分钟返回，Developer 可能 6 分钟以上，UI 看起来仍然偏静默。
- P0 仍以本地 connector 进程为主，没有守护进程、重连策略、任务取消、日志回放或多任务队列。
- Developer connector 使用 `workspace-write` 会真实修改本地工作区；正式产品需要单独 worktree、变更预览、人工确认和回滚策略。
- Review Room 控制面和 connector 的 token/权限边界需要继续收紧：P0 适合验证协作链路，不应直接视为生产安全边界。
