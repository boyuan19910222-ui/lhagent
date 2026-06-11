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
