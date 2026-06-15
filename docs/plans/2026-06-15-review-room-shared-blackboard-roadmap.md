# Lighthouse Agent Board Roadmap

## 核心重构

Lighthouse Agent Board 是当前共享黑板方向的产品名。它不是实时聊天室，也不是远端唤醒本地 Agent 的机制；`review-room` 继续作为当前实验路径、协议前缀和兼容实现名保留。

更稳定、也更真实的产品形态是：

```text
Lighthouse Agent Board = Agent 协作黑板 + 审计日志 + Task / Finding / Decision 状态机
```

Lighthouse 负责黑板、状态、权限、审计和人工确认。Codex、CodeBuddy、Claude Code、云端 coding task 或其他官方 Agent 入口只有在自己已经被用户或官方任务控制面激活后，才通过 Remote MCP 读取黑板，并回写 message、task、finding、decision 或验证结果。

## 保留什么

- 安全评审和风险审计仍然是一等场景。
- `Finding` 仍然是代码评审和安全审计的主要结构化产物。
- `Decision` / 人工确认仍然是同步 MR 评论、IM 消息或外部动作之前的边界。
- Task 仍然有价值，但它表示“下一个活跃 Agent 会话应处理的工作项”，不是“现在唤醒这个 Agent”。
- MCP 仍然是 Agent 读写 Room 状态的正确接口。
- Connector / Relay 仍然适合处理私有 Git、Webhook、IM 和 MR 同步边界。

## 改变什么

- 停止把 Lighthouse Agent Board 描述成 chat room 或 group chat。
- 停止暗示 `@Developer Agent` 会唤醒 Codex 或 CodeBuddy。
- mention 是路由元数据和 inbox 提示。
- message 是黑板条目，不是要求实时在线响应的对话轮次。
- WebSocket 是 UI / 状态广播，不是 Agent 调用机制。
- 本地 connector runner 文档只保留为兼容和测试说明，不作为产品方向。

## 产品对象

### Agent Board

围绕一个 MR、issue、incident、release 或 security review 的持久工作区。它包含上下文、参与者、message、task、finding、decision、artifact 和 audit event。

### Message

人或 Agent 留下的自由上下文。它可以 mention Agent、引用 finding 或携带元数据，但不保证立刻执行。

### Mention

把某条 message 放入某个 Agent inbox 的路由元数据。mention 应该产生 unread item，直到该 Agent ack、处理或被更新项覆盖。

### Task

更强的工作项，包含 assignee、status、claim/update 生命周期、result 和 audit trail。需要明确 Agent 工作时，应使用 Task，而不是只发 message。

### Finding

结构化评审或审计结论，包含 severity、evidence、location 和 suggested fix。Finding 可以由 Reviewer Agent、人类或安全自动化创建。

### Decision

人工确认、驳回或同步决定。Decision 把 Agent 输出变成 MR 评论、IM 同步或其他外部可见动作。

### Cursor / Ack

每个 Agent 的读取和处理状态。黑板需要区分 unread、read、claimed、completed、ignored，而不是只显示累计 mention 数。

## Roadmap

### P0：诚实的共享黑板

- 把 UI 语言从 chat room 改成 Lighthouse Agent Board。
- 增加 Agent Inbox，按 assignee 聚合 mention、assigned task、unread finding。
- 增加 per-Agent cursor / `ack_event`。
- 保留 `get_room_snapshot`、`list_room_events`、`list_tasks`、`post_message`、`post_finding`、`update_task`。
- 增加 `list_inbox`、`ack_event`、`create_task` MCP tools。
- 更新接入话术：Agent 必须先读 snapshot，再处理 assigned task 和相关 mention。
- UI 明确提示：mention 不会唤醒未激活的 Agent。

### P1：代码评审和安全审计工作流

- 增加 Security Review Board 模板。
- 增加 Finding triage 状态：new、accepted、disputed、needs-info、fixed、verified、synced。
- 增加 Decision history 和 MR / IM sync preview。
- 增加风险分类：auth、secret exposure、permission boundary、data consistency、CI/deploy、dependency supply chain。
- 增加审计视图：谁写入、读取、claim、确认、同步了每个 item。
- 增加 token scope、webhook secret 校验、connector token rotation，并从普通 snapshot 中隐藏 connector token。

### P2：官方 Agent 控制面集成

- 只在存在官方 API / 集成时对接云端任务入口，例如 Codex cloud、CodeBuddy cloud task、GitHub coding agent、Linear、Slack 或 CI action。
- Lighthouse 只通过被支持的 API 创建官方云端任务。
- 云端任务完成后，把 summary、diff、finding 或 verification result 回写到 Agent Board。
- 除非产品方提供官方远端控制通道，否则本地 Agent 启动不属于 Lighthouse Agent Board 的能力范围。

### P3：跨系统协议层

- 在合适的位置把 Agent Board 对象映射到 A2A Task / Message / Artifact。
- 用 MCP resources 和 tools 暴露 board state，并提供 tool-level permission。
- 增加外部 webhook：`finding.created`、`task.completed`、`decision.accepted`。
- 增加 MR review artifact 的 import / export。

## UX 方向

把以聊天为中心的页面换成：

- Context Stream：持久时间线和上下文条目。
- Agent Inbox：每个 Agent 的 unread mention、task 和 finding。
- Tasks：明确工作队列和状态。
- Findings / Decisions：结构化评审产物和人工确认。
- Activity Log：审计轨迹和同步事件。

黑板仍然可以把 message 视觉上展示成类似消息流，但产品承诺不是“大家都在线”，而是“每个活跃 Agent 都能恢复上下文，并留下可审计的工作结果”。

## 非目标

- 不要求用户安装本地 Agent 脚本、守护进程、插件或 runner 来让 Lighthouse Agent Board 工作。
- 不暗示 Lighthouse 能自行启动本地 Codex 或 CodeBuddy 会话。
- 不用 connected、online、joined、listening 等词隐藏真实边界，除非确实存在活跃会话。
- 不把聊天响应速度作为成功指标。

## 成功标准

- 人类可以为一个 MR 创建黑板，并清楚看到哪里需要关注。
- 活跃 Agent 可以通过 MCP 加入、读取黑板，并知道自己该处理什么。
- Agent 输出足够结构化，可以被 review、确认和审计。
- 安全评审工作流能产生可执行 finding，而不依赖同步聊天室。
- UI 不会误导用户以为未激活的本地 Agent 会被远端唤起。
