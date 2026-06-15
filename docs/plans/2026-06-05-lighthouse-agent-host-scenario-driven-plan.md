# Lighthouse Agent Host 场景驱动方案

> 本方案基于“Lighthouse 是个人开发者的云端 Agent 主机与 Agent 工作台”继续收敛。相比上一版，本版把需求场景进一步具象化：每个场景都补充公开市场信号、实际任务、可落地模板、效率收益口径和 Lighthouse 产品能力。

## 1. 核心判断

上一版的问题是场景还停留在概念层：一键试用、本地 Agent 长期在线、MCP 工具箱、自动化开发工作流、Agent 作品分享，这些方向成立，但用户还不一定能立刻感知“我到底拿它干什么”。

本版建议把 Lighthouse Agent Host 的叙事收敛成一句话：

**Lighthouse 帮个人开发者把 Agent 从一次性实验，变成能持续处理开发任务、复用工具、沉淀产物、分享给他人的云端自动化系统。**

产品不应先展示“Agent 应用 / MCP / Runtime / Workspace / AgentOps / Gallery”这些模块，而应该先展示 3 个高价值场景入口：

1. **我想试一个开源 Agent。**
2. **我想让我的 Agent 长期替我处理开发任务。**
3. **我想把 MCP 工具配置成云端工具箱，到处复用。**

后面的 Workspace、AgentOps、Gallery、成本、Team Lite 都应该作为这 3 个场景的结果页自然出现。

## 2. 场景一：一键试用热门开源 Agent

### 2.1 已有市场信号

开源 Agent 和低代码 Agent 工具已经很多，但个人开发者的“试用成本”仍然很高。Dify、n8n、LangGraph、CrewAI、OpenClaw、Hermes 这类工具都有自己的安装、模型、数据库、Secret、运行环境和升级问题。Dify 在 2026 年推出 Creator Center 和 Template Marketplace，说明“模板化发布、快速试用、复用工作流”已经是 Agent/Workflow 平台的明确方向。n8n 也有官方模板体系，并通过模板 API 暴露分类、集合和搜索能力。

### 2.2 真实任务

“我看到一个开源 Agent 项目，想 10 分钟内跑起来，接上自己的模型 Key，看它能不能解决我的问题。”

### 2.3 具体可以试什么

1. **OpenClaw Dev Agent**
   - 任务：代码仓库分析、模型探测、插件/技能调试。
   - 用户收益：不用本地配完整环境，先在云端试能力。

2. **Hermes Agent Host**
   - 任务：多模型通道、工具调用、轻量 Agent 面板。
   - 用户收益：把模型、工具、配置集中到一个可访问入口。

3. **Dify / n8n Agent Workflow**
   - 任务：试一个自动化工作流，比如 issue triage、RSS 总结、表格处理。
   - 用户收益：不用先理解完整部署体系，直接从模板开始。

4. **Browser / Research Agent**
   - 任务：抓网页、总结文档、生成调研报告。
   - 用户收益：把浏览器环境、截图、产物保存放在云上。

5. **Code Review Agent**
   - 任务：读取 repo、总结 PR、列风险和测试缺口。
   - 用户收益：把“AI 代码审查”从聊天窗口变成可重复任务。

### 2.4 当前痛点

- README 很长，Docker、端口、环境变量、数据库、模型 Key 都要自己配。
- 本地环境容易冲突，跑起来后外网回调、HTTPS、持久化还要另配。
- 不知道这个 Agent 需要什么模型、支持什么工具、有哪些默认账号和健康检查。
- 试完之后很难长期保留，也很难迁移到云端。

### 2.5 Lighthouse 能力

- Agent 应用目录：OpenClaw、Hermes、Dify、n8n、Code Reviewer、Daily Brief 等模板。
- 一键部署向导：规格、模型 Key、Secret、MCP 工具组、域名、成本上限。
- Agent Manifest 自动生成：运行需求、模型需求、工具需求、访问入口、健康检查。
- 部署后应用面板：访问地址、状态、日志、配置、更新日志、暂停/销毁。
- 试用保护：低价规格、试用时长提醒、删除前导出配置。

### 2.6 原型表达

首屏不应是 Dashboard，而是：

**“选择一个 Agent，10 分钟跑起来。”**

每个模板卡片必须回答：

- 这个 Agent 具体能帮我做什么。
- 需要什么模型和 MCP。
- 部署后会产生什么入口。
- 预计成本是多少。
- 是否能导出配置或继续长期运行。

## 3. 场景二：让本地 Agent 长期在线干活

### 3.1 已有市场信号

这不是想象出来的需求。Cursor Background Agents 官方文档描述的是：在远程环境中启动异步 Agent，让它编辑和运行代码，并在侧栏里查看所有后台 Agent。OpenAI Codex 的公开介绍也强调 cloud sandbox：可以写功能、回答代码库问题、修 bug、提出 PR，任务运行在预加载 repo 的云端环境里。GitHub Copilot coding agent 的学习材料和官方 Agentic Workflows 也指向类似模式：把 issue 分配给 Agent，Agent 在云端环境工作、运行测试、打开 PR。

这些产品共同说明一件事：开发者已经开始把“需要持续执行、需要环境、需要结果回收”的任务交给云端 Agent，而不是只在本地聊天窗口里问答。

### 3.2 “长期在线”具体干什么

这里不应该泛泛说“帮我自动化”，而要围绕个人开发者每天会重复遇到的活：

1. **GitHub Issue Triage**
   - 触发：新 issue 创建、加 label、被 @。
   - 行为：分类、判断是否缺少复现信息、生成回复草稿、推荐优先级。
   - 输出：label 建议、issue 评论草稿、待补充字段。

2. **PR Review Digest**
   - 触发：PR 创建或更新。
   - 行为：总结 diff、列风险点、列缺失测试、给出 review checklist。
   - 输出：PR 摘要、风险清单、测试建议。

3. **Release Note / Changelog**
   - 触发：合并到 main、打 tag、手动运行。
   - 行为：汇总 commits、PR、issues，生成发布说明。
   - 输出：Markdown changelog、面向用户的 release note。

4. **Daily Dev Brief**
   - 触发：每天早上。
   - 行为：汇总 GitHub 通知、RSS、收藏夹、待办、技术新闻。
   - 输出：个人开发日报、链接列表、待处理任务。

5. **Dependency / Security Watch**
   - 触发：每天或每周。
   - 行为：检查依赖更新、安全公告、breaking change。
   - 输出：升级建议、风险说明、可执行 checklist。

6. **Website / API Monitor**
   - 触发：定时任务或 webhook。
   - 行为：访问网页/API、截图、检测报错、生成异常摘要。
   - 输出：监控报告、截图、失败原因。

### 3.3 效率提升口径

这类场景的收益不应只说“提高效率”，建议用 4 个可量化口径：

- **减少启动成本**：本来每天要手动打开 GitHub、RSS、文档和 AI 客户端，现在定时触发。
- **减少上下文切换**：GitHub、浏览器、文件、模型和产物都在同一条任务时间线里。
- **减少重复整理**：日报、release note、review digest 这类文本产物自动生成初稿。
- **减少遗漏**：issue、PR、依赖、RSS 可以被定时扫一遍，先生成待办队列。

公开数据可以作为背景支撑：Stack Overflow 2025 调查显示，52% 开发者认为 AI 工具或 AI agents 对生产力有正向影响；在使用 AI agents 的开发者中，软件开发是最常见用途之一。Microsoft Research 对 GitHub Copilot 的实验研究显示，使用 AI pair programmer 的实验组完成特定编程任务快 55.8%。这些数据不能直接等同于 Lighthouse 的收益，但说明开发者愿意把重复开发工作交给 AI，并且“节省时间”是被验证过的核心价值。

### 3.4 Lighthouse 能力

- 自定义 Agent 导入：GitHub repo、镜像、压缩包或 `agent-cli deploy`。
- `agent-cli probe`：识别端口、启动命令、依赖、模型环境变量、健康检查。
- 任务触发器：定时、Webhook、手动、API、MCP 调用。
- 长任务队列：运行中、暂停、重试、失败、完成。
- Artifact 保存：Markdown、截图、文件、报告、代码 diff、数据结果。
- 任务时间线：目标、计划、模型调用、工具调用、产物、错误、成本。
- 云端任务实例的空闲休眠和事件启动：控制成本，只适用于 Lighthouse 托管的云端任务。

### 3.5 原型表达

主流程应该是：

**“把本地 Agent 变成每天自动运行的云端任务。”**

交互步骤：

1. 粘贴 GitHub repo 或导入镜像。
2. Probe 自动识别启动方式和依赖。
3. 选择任务模板：Issue Triage / PR Review / Daily Brief / Release Note。
4. 选择触发器：每天 08:30 / GitHub webhook / 手动。
5. 运行一次测试任务。
6. 展示任务时间线和产物。

## 4. 场景三：把 MCP 工具变成个人云端工具箱

### 4.1 已有市场信号和数据

MCP 已经从“新协议”进入快速扩张期。官方 `modelcontextprotocol/servers` 仓库是 reference implementations 和 community-built servers 的集合。公开 MCP 目录也在快速膨胀：PulseMCP 的服务器目录页面显示 12,700+ 个 servers；Smithery 的定位是发现、部署和管理 MCP servers，并包含 server deployments、releases、secrets、team API keys 等管理能力。

这些数据不能简单视为去重后的真实可用服务器数，但足以说明：MCP 的问题已经从“有没有工具”转向“工具太多、如何发现、安装、授权、复用和管理”。

### 4.2 什么样的 MCP 最适合个人开发者

Lighthouse 不应该先做全行业 MCP 网关，而应该先聚焦个人开发者高频工具：

1. **代码与仓库类**
   - GitHub、Git、Filesystem、Repo Memory。
   - 用途：issue、PR、代码阅读、commit、release note。

2. **浏览器与网页类**
   - Browser、Puppeteer/Playwright、网页抓取、搜索。
   - 用途：调研、截图、网页监控、文档总结。

3. **数据库与数据类**
   - Postgres、SQLite、MySQL、Sheets。
   - 用途：个人项目数据分析、报表、SQL 辅助。

4. **个人知识库类**
   - Notion、Obsidian、Google Drive、Markdown Vault、Memory。
   - 用途：让 Agent 读取个人资料、历史决策、项目笔记。

5. **消息与通知类**
   - Slack、Discord、飞书、邮件、Telegram。
   - 用途：任务完成通知、日报发送、告警摘要。

6. **云资源类**
   - 腾讯云资源、对象存储、数据库、监控告警。
   - 用途：轻量服务器巡检、资源查询、费用提醒。

### 4.3 真实任务

“我希望 GitHub、Browser、Memory、数据库这些 MCP 工具只配置一次，然后 Claude、Cursor、Codex、我的云端 Agent 都能复用。”

### 4.4 当前痛点

- 每个客户端都要配置一遍 MCP。
- Secret 分散在本地 JSON、环境变量、不同工具里。
- 某个 MCP 挂了，很难知道是命令错、token 过期、权限不足，还是客户端问题。
- 工具调用没有统一日志。
- 想把同一组工具挂到多个 Agent，要重复配置。

### 4.5 Lighthouse 能力

- MCP Server 目录和一键安装。
- 远程 MCP Endpoint。
- Secret / OAuth Vault。
- 工具健康检查、测试调用、版本更新。
- MCP 工具组：开发、浏览器、数据库、个人知识库、云资源。
- 客户端配置生成：Claude、Cursor、Codex、ChatGPT、自定义脚本。
- 调用日志：哪个客户端、哪个 Agent、调用了哪个工具、是否失败。
- Agent 挂载：一个工具组挂到多个 Agent。

### 4.6 原型表达

原型不要先展示 MCP 表格，而要展示结果：

**“GitHub + Browser + Memory 工具组，已被 5 个 Agent 和 3 个客户端复用。”**

关键交互：

1. 安装 GitHub MCP。
2. 保存 token。
3. 测试 list issues。
4. 生成 Claude/Cursor/Codex 配置。
5. 挂载到 Code Reviewer Agent。
6. 在调用日志里看到它被使用。

## 5. 场景四：自动化个人开发工作流

### 5.1 已有市场信号

n8n 官方模板库和社区模板里已经出现了 GitHub issue triage、AI Agent、Webhook、Cron、Slack 通知等组合。公开的 n8n 模板示例中，有“用 Gemini AI 自动 triage GitHub issues、自动打标签、发送 Slack alerts”的工作流；GitHub 文档也说明第三方 coding agents 和 Copilot cloud agent 可以异步处理开发任务并创建 PR。说明开发工作流自动化不是理论方向，而是已经有实际模板和平台机制。

### 5.2 实际案例一：Issue Triage Agent

**用户任务：** 开源项目维护者每天要看新 issue，判断 bug / feature / question，补标签，询问复现信息。

**自动化流程：**

1. GitHub webhook 收到新 issue。
2. Agent 读取 issue 内容、repo README、历史相似 issue。
3. 判断类型和优先级。
4. 生成 label 建议和回复草稿。
5. 如果置信度高，自动打标签；否则放入待确认队列。

**效率提升：**

- 从每天批量阅读 issue，变成只处理“需要人工判断”的少数 issue。
- 回复草稿减少重复沟通。
- label 和优先级更稳定，后续 backlog 更清晰。

**Lighthouse 需要：** GitHub MCP、Memory MCP、Webhook、任务时间线、人工确认、Artifact。

### 5.3 实际案例二：PR Review Digest Agent

**用户任务：** 个人开发者或小项目维护者要快速理解 PR 变化，判断是否有风险。

**自动化流程：**

1. PR 创建或更新后触发。
2. Agent 拉取 diff、相关文件、测试结果。
3. 总结核心改动。
4. 列出风险：权限、数据结构、兼容性、错误处理、缺失测试。
5. 生成 review checklist。

**效率提升：**

- 把“读 diff + 整理问题”的时间前置自动化。
- 人只需要 review Agent 摘要和高风险点。
- 对 AI 生成代码尤其有用，因为需要额外关注测试和副作用。

**Lighthouse 需要：** GitHub MCP、代码读取权限、AgentOps Lite、测试日志接入、成本上限。

### 5.4 实际案例三：Release Note Agent

**用户任务：** 每次发布前都要从 commits、PR、issues 里整理 changelog。

**自动化流程：**

1. main 分支合并或 tag 创建后触发。
2. Agent 汇总提交、PR、issue、版本信息。
3. 区分新增、修复、破坏性变更、文档更新。
4. 生成面向用户和面向开发者的两版 release note。
5. 产物保存为 Markdown，可手动编辑后发布。

**效率提升：**

- 减少发布前机械整理工作。
- 让 release note 更稳定，不依赖最后一分钟回忆。
- 产物可进入 Workspace，后续版本复用格式。

**Lighthouse 需要：** GitHub MCP、文档 Artifact、Workspace 模板、人工确认。

### 5.5 实际案例四：Daily Dev Brief Agent

**用户任务：** 每天早上快速知道：昨天仓库发生了什么、今天有什么 issue、关注的 Agent/MCP 有什么更新。

**自动化流程：**

1. 每天 08:30 触发。
2. Agent 拉取 GitHub 通知、RSS、收藏、MCP 更新、待办。
3. 生成 1 页日报。
4. 发送到邮箱/飞书/Markdown Vault。
5. 保存为历史 Artifact。

**效率提升：**

- 减少早上打开多个页面查信息的时间。
- 把信息摄取变成固定节奏。
- 每天的结果沉淀成个人知识库。

**Lighthouse 需要：** 定时任务、Browser/RSS/Memory MCP、Artifact、通知工具。

### 5.6 原型表达

这一页不应叫“自动化工作流”，而应该叫：

**“选择你今天想省掉的开发杂事。”**

卡片可以是：

- 自动处理 GitHub Issue。
- 自动生成 PR Review Digest。
- 自动生成 Release Note。
- 每天生成开发日报。
- 监控依赖和安全更新。

每张卡展示：触发器、所需 MCP、输出产物、预计节省时间、是否需要人工确认。

## 6. 场景五：把自己的 Agent 作品分享出去

### 6.1 已有类似机制和平台

已经有几类相近机制：

1. **OpenAI GPT Store**
   OpenAI 曾披露用户已创建超过 300 万个 custom GPTs；GPT 可以按链接分享，也可以发布到 GPT Store。这说明“个人创建 AI 应用并分享”已经是成熟需求。

2. **Dify Creator Center / Template Marketplace**
   Dify 在 2026 年推出 Creator Center 和 Template Marketplace，目标是让创作者发布 workflow templates，让用户快速发现、试用和采用。

3. **n8n workflow templates**
   n8n 有模板库和模板 API，社区也大量分享 workflow JSON、README 和部署说明。

4. **Agent / workflow marketplace**
   市面上已经出现 AgentDeploy、AIHive 等“AI Agent marketplace / ready-to-deploy templates”方向的平台，说明“可部署 Agent 模板”正在形成独立品类。

这些机制的共同点是：用户不只想自己用 Agent，还想把配置、流程、模板或作品发布给别人复用。

### 6.2 Lighthouse 的差异机会

GPT Store 更偏 ChatGPT 内部应用；Dify/n8n 更偏 workflow；LangGraph/LangSmith 更偏框架部署；Agent marketplace 更偏模板交易。

Lighthouse 可以做个人开发者更需要的中间层：

**把一个真实运行在云端的 Agent 实例，变成可试用、可 fork、可部署、可作为 MCP/API 调用的作品。**

它不只是“分享 Prompt”，也不只是“分享 workflow JSON”，而是分享一个带运行环境、工具依赖、成本护栏和部署入口的 Agent 应用。

### 6.3 真实任务

“我做了一个 Code Review Agent / Daily Brief Agent / Browser Research Agent，想让朋友先试用；如果他喜欢，可以一键部署成自己的版本。”

### 6.4 当前痛点

- 本地 Agent 无法分享。
- 自己做公网 Demo 需要域名、登录、限流、安全、成本控制。
- 如果别人想复用，需要看 README、配环境、填 Key、搭工具。
- 公开 Demo 容易泄露 Secret 或跑出成本。
- Agent 能力难以被其他工具调用。

### 6.5 Lighthouse 能力

- 公开 Demo 页面。
- “Deploy on Lighthouse” 按钮。
- Fork / Remix 模板。
- 公开能力控制：只读 Demo、API、MCP Tool、A2A Agent Card。
- 成本护栏：Demo 访问额度、单任务上限、排队、暂停。
- 安全边界：隐藏 Secret、只读工具、公开版本和私有版本分离。
- 作者页和模板统计。

### 6.6 原型表达

这里不是普通 Gallery，而是创作者发布流程：

**“把你的 Agent 变成可试用、可 fork、可部署的作品。”**

关键交互：

1. 选择要发布的 Agent。
2. 选择公开能力：Demo / API / MCP Tool / A2A。
3. 设置成本上限和访问限制。
4. 生成 Demo 链接和 Deploy 按钮。
5. 查看 fork 和使用数据。

## 7. 场景优先级

建议不要 5 个场景一起做。先选 3 个形成最小闭环：

| 优先级 | 场景 | 为什么先做 |
| --- | --- | --- |
| P0 | 一键试用热门开源 Agent | 最贴 Lighthouse 现有镜像能力，最容易让用户快速上手 |
| P0 | 把 MCP 工具变成个人云端工具箱 | 公开目录已上万级，碎片化明显，且能连接多个 AI 客户端 |
| P0 | 开发协作共享黑板 / Review Room | Codex/CodeBuddy 等 Agent 无法被远端凭空唤醒，但可以在被激活后通过 MCP 主动读写同一个审计黑板 |
| P1 | 自动化个人开发工作流 | 价值强，但需要 GitHub/MCP/Runtime 先稳定 |
| P1 | 把自己的 Agent 作品分享出去 | 有传播价值，但依赖部署、运行、成本护栏和安全边界 |

## 8. 基于场景的产品能力重排

### 第一层：快速跑起来

- Agent 模板目录。
- 一键部署。
- 模型 Key 配置。
- Agent Manifest 自动探测。
- 访问入口和健康检查。

### 第二层：工具只配一次

- MCP Server 安装。
- Secret / OAuth 管理。
- MCP 工具组。
- 远程 MCP Endpoint。
- 客户端配置生成。
- MCP 调用日志。

### 第三层：长期在线干活

- 定时任务。
- Webhook。
- 长任务队列。
- Artifact。
- 失败重试。
- 空闲休眠和成本上限。

### 第四层：开发者工作流模板

- Issue Triage。
- PR Review Digest。
- Release Note。
- Daily Dev Brief。
- Dependency Watch。
- Website/API Monitor。

### 第五层：协作黑板

- Room Board：围绕一个 MR、issue、incident 或发布任务沉淀上下文。
- Agent Inbox：按 Agent 聚合 mentions、assigned tasks、unread findings。
- Task / Finding / Decision 状态机。
- per-agent cursor / ack，区分“已提及”“已读取”“已处理”。
- 安全审计：token 作用域、Webhook secret、公网暴露、MR 评论同步权限、危险动作确认。
- MCP 读写工具：snapshot、events、tasks、post_message、post_finding、update_task、ack_event。

### 第六层：分享和复用

- Demo 页面。
- Deploy on Lighthouse。
- Fork / Remix。
- API / MCP / A2A 暴露。
- 作者页。

## 9. 原型重做建议

上一版 demo 的问题是从模块导航出发，用户先看到“总览、应用、MCP、Runtime、Workspace、Ops、Gallery”。这更像平台后台，缺少场景抓手。

新版原型建议改为 4 个主入口：

### 入口一：我要试一个 Agent

面向新用户。首屏展示热门模板：

- OpenClaw Dev Agent。
- Hermes Agent Host。
- Dify Workflow。
- Code Reviewer。
- Daily Dev Brief。

主流程：选择模板 -> 配模型 -> 配 MCP -> 选择规格 -> 跑一次 demo -> 进入应用面板。

### 入口二：我要让我的 Agent 长期运行

面向已有本地 Agent 的开发者。

主流程：导入 repo/镜像 -> Probe -> 选择任务模板 -> 配触发器 -> 运行测试任务 -> 查看时间线和产物。

建议默认任务模板：

- GitHub Issue Triage。
- PR Review Digest。
- Release Note。
- Daily Dev Brief。

### 入口三：我要管理我的 MCP 工具箱

面向多客户端 AI 工具用户。

主流程：安装 MCP -> 配 Secret -> 测试 -> 生成客户端配置 -> 挂载到 Agent -> 查看调用日志。

建议默认工具组：

- GitHub + Repo Memory。
- Browser + Search。
- Database + Sheets。
- Personal Memory + Notification。

### 入口四：我要让多个 Agent 接力评审一个 MR

面向已经在 Codex、CodeBuddy、Claude Code、云端 coding agent 之间切换的开发者。

主流程：创建 Review Room Board -> 绑定 repo/MR -> 复制 Remote MCP 接入 -> Agent 主动读取黑板 -> 写入 Finding / Task / Decision -> 人工确认同步。

这个入口不要包装成“Agent 群聊”。它是共享黑板：Lighthouse 负责保存上下文、路由提及、沉淀审计、展示状态；Agent 是否执行取决于它是否被用户或官方云端任务控制面激活。

建议默认模板：

- Security Review Board。
- PR Risk Review Board。
- Release Decision Board。
- Incident Fix Review Board。

这四个入口之后，再出现 Workspace、AgentOps、Gallery、成本、Team Lite，作为场景结果页，而不是第一层导航。

## 10. 推荐的新产品包装

### 主标题

**Lighthouse Agent Host：把 Agent 从本地实验变成云端运行、工具复用和协作黑板。**

### 副标题

**一键试用开源 Agent，统一管理 MCP 工具，把开发协作沉淀到可审计黑板，并生成可分享、可 fork 的云端 Agent 应用。**

### 三个首屏按钮

- **试用开源 Agent**
- **部署我的 Agent**
- **管理 MCP 工具箱**
- **创建协作黑板**

### 价值表达

- 不是“Agent 控制台”，而是“Agent 使用场景入口”。
- 不是“我有很多功能”，而是“你今天的一个开发任务可以交给它长期跑”。
- 不是“企业级治理”，而是“个人开发者少折腾、跑得久、看得懂、能分享”。

## 11. 补充：从开发效率扩展到个人生活自动化

前面的场景仍然偏“开发者工作流”。如果 Lighthouse 想在个人开发者群体里形成更大的想象空间，应该把“个人开发者”理解为会动手搭系统的人，而不是只写代码的人。很多个人开发者会为自己、家人、房子、设备、财务、出行、知识库搭一套长期运行的个人系统。

这类场景的共同点是：

- 需要长期在线。
- 需要接入多个设备、服务或数据源。
- 需要自动化，但又不能完全无脑自动执行。
- 需要人类确认、安全边界、日志和回滚。
- 需要低成本，因为多数是个人或家庭使用。

这比“开发效率”更贴近 Lighthouse 作为轻量云主机的天然优势。

### 11.1 场景六：智能家居管控 Agent

#### 已有市场信号

Home Assistant 已经是个人/家庭自动化的代表生态。官方 Assist 支持用自然语言控制智能家居，并可在本地硬件运行，强调隐私；Home Assistant Matter 集成支持通过本地 Wi-Fi 或 Thread 网络控制 Matter 设备，并运行自己的 Matter controller；Home Assistant 自动化体系支持基于触发器和动作响应家里的事件。

同时，社区已经出现多个 Home Assistant MCP Server 项目，用 MCP 让 Claude、Cursor、OpenAI 或其他 AI 客户端查询和控制 Home Assistant。这说明“AI Agent + 智能家居”不是拍脑袋，已经有人在把 Home Assistant 变成 Agent 可调用的工具。

#### 用户画像

懂一点技术的智能家居爱好者、个人开发者、租房/家庭自动化玩家。他家里可能已经有 Home Assistant、米家、Aqara、Matter、Zigbee、摄像头、空调、门锁、传感器、NAS 或软路由。

#### 真实任务

“我想搭一个家庭智能管家 Agent。它能理解家里的设备状态，帮我规划自动化规则，处理异常提醒，并在我确认后执行高风险动作。”

#### 具体能干什么

1. **家庭状态总结**
   - 每天早晚总结家里状态：门窗、温湿度、空气质量、用电、扫地机、摄像头、漏水传感器。
   - 输出：一页家庭日报，异常项置顶。

2. **自然语言创建自动化**
   - 用户说：“晚上 11 点后如果客厅没人，把灯关掉，空调调到睡眠模式。”
   - Agent 转成 Home Assistant automation blueprint 或 YAML 草稿。
   - 用户确认后再部署。

3. **异常监控和解释**
   - 发现门窗长时间打开、用电异常、温度过高、漏水传感器触发。
   - Agent 解释可能原因，给出建议动作。
   - 高风险动作，如关燃气、开门锁、关闭总电源，必须人工确认。

4. **节能优化**
   - 分析一周空调、热水器、照明、插座用电。
   - 推荐自动化规则：离家模式、睡眠模式、日照联动、峰谷电价策略。

5. **家庭设备维护**
   - 监控电池电量、离线设备、固件更新、传感器异常。
   - 输出维护清单：哪个传感器要换电池，哪个设备掉线频繁。

#### 当前痛点

- Home Assistant 很强，但自动化配置、实体命名、触发器、条件、动作对普通用户仍然复杂。
- 语音助手可以控制单个设备，但不擅长跨设备推理、总结和规则生成。
- 智能家居动作有安全风险，不能让 LLM 直接随便控制门锁、电源和摄像头。
- 家庭状态数据分散在多个生态和设备里。
- 用户需要的是“可解释 + 可确认”的智能，而不是黑箱自动执行。

#### Lighthouse 机会

Lighthouse 可以做“智能家居 Agent 的云端控制面和安全代理”，但不替代 Home Assistant 本身：

- Home Assistant 仍然做本地设备接入和实时控制。
- Lighthouse Agent 负责长期在线的推理、总结、规则生成、远程通知、MCP 管理和确认流。
- 通过 MCP / Webhook / Home Assistant API 与家庭系统连接。

#### 产品能力

- Home Assistant MCP / Connector 托管。
- 家庭设备实体映射和权限分级。
- 自动化规则生成与确认。
- 高风险动作审批：门锁、燃气、电源、摄像头、警报。
- 家庭状态日报和异常时间线。
- 能源/设备维护报告。
- 远程通知：微信/飞书/邮件/Telegram。
- 成本和隐私设置：本地控制优先，云端只处理摘要或授权数据。

#### 原型表达

这个场景的 demo 不应展示普通 Agent dashboard，而应该展示：

**“打造一个家庭智能管家：看懂家里状态，生成自动化规则，异常时提醒你确认。”**

主流程：

1. 连接 Home Assistant。
2. 扫描设备实体并分级：可读、低风险可控、高风险需确认。
3. 选择家庭目标：省电 / 安全 / 舒适 / 维护。
4. Agent 生成第一组自动化建议。
5. 用户确认其中一条，部署为 Home Assistant automation。
6. 后续在时间线里看到触发、执行、异常和回滚。

### 11.2 场景七：个人健康与生活节律 Agent

#### 真实任务

“我想让一个 Agent 长期汇总睡眠、运动、日程、天气、空气质量和家庭设备状态，每天给我一个生活建议，而不是只在 App 里看数据。”

#### 可连接数据

- Apple Health / Google Fit / Garmin / 小米运动等健康数据。
- 日历和待办。
- 天气、空气质量、通勤时间。
- 智能灯、空调、空气净化器、窗帘。

#### 具体能干什么

- 早上生成今日状态：睡眠、天气、会议、通勤、空气质量。
- 推荐起床灯光、空调、空气净化器策略。
- 晚上根据睡眠目标，提醒关屏、调灯光、降低噪音。
- 周报总结：睡眠、运动、工作节奏、环境影响。

#### Lighthouse 机会

Lighthouse 的价值不是替代健康 App，而是把多个个人数据源和家居设备串成“生活节律自动化”。这需要长期在线、数据连接、通知和低风险设备控制。

### 11.3 场景八：家庭账单与订阅管家 Agent

#### 真实任务

“我想知道这个月家庭固定开销、订阅、云资源、智能设备耗电有没有异常，快到期的服务能不能提醒我。”

#### 可连接数据

- 邮箱账单。
- 支付记录或手动导入表格。
- 云资源账单。
- 家庭用电数据。
- 订阅服务清单。

#### 具体能干什么

- 汇总本月订阅和账单。
- 找出重复订阅、涨价、异常扣费。
- 结合智能插座/电表，发现耗电异常。
- 到期前提醒续费或取消。

#### Lighthouse 机会

这个场景适合强调“个人数据 + Agent 解释 + 通知 + 人工确认”，但涉及隐私和财务，应先做只读分析，不做自动付款或取消。

### 11.4 场景九：旅行与远程看家 Agent

#### 真实任务

“我出差或旅行时，希望有一个 Agent 帮我看家：设备是否离线、门窗是否异常、耗电是否异常、是否有人经过、是否需要远程处理。”

#### 具体能干什么

- 离家模式自动检查：门窗、灯、空调、扫地机、摄像头、门锁。
- 异常事件解释：例如传感器触发是否可能是误报。
- 每天发送一页看家报告。
- 需要操作时发起确认：关闭灯、重启设备、打开扫地机、通知家人。

#### Lighthouse 机会

这是智能家居管控 Agent 的高价值子场景。它比“控制智能家居”更具象，也更容易做 demo：用户出差，Agent 每天看家，异常时请求确认。

## 12. 参考资料

- Cursor Docs：[Background Agents](https://docs.cursor.com/background-agent)
- OpenAI：[Introducing Codex](https://openai.com/index/introducing-codex/?video=1084810944)
- GitHub Agentic Workflows：[Assign to Copilot](https://github.github.com/gh-aw/reference/assign-to-copilot/)
- GitHub Copilot Learning Hub：[Using the Copilot Coding Agent](https://awesome-copilot.github.com/learning-hub/using-copilot-coding-agent/)
- Stack Overflow：[2025 Developer Survey - AI](https://survey.stackoverflow.co/2025/ai)
- Microsoft Research：[The Impact of AI on Developer Productivity](https://www.microsoft.com/en-us/research/publication/the-impact-of-ai-on-developer-productivity-evidence-from-github-copilot/)
- GitHub：[modelcontextprotocol/servers](https://github.com/modelcontextprotocol/servers)
- PulseMCP：[MCP Server Directory](https://www.pulsemcp.com/servers)
- Smithery：[MCP servers](https://smithery.ai/servers/smithery)
- n8n Docs：[Templates](https://docs.n8n.io/workflows/templates/)
- n8n Workflow Template：[Triage GitHub issues with Gemini AI](https://n8n.io/workflows/13874-triage-github-issues-with-gemini-ai-auto-label-them-and-send-slack-alerts/)
- OpenAI Help：[Sharing and publishing GPTs](https://help.openai.com/en/articles/8798868-introducing-the-gpt-store)
- OpenAI：[Introducing the GPT Store](https://openai.com/blog/introducing-the-gpt-store?Tag=lead%252520conversion)
- Dify Blog：[Creator Center & Template Marketplace](https://dify.ai/blog/dify-creator-center-template-marketplace-share-your-workflows)
- Home Assistant：[Assist - Talk to your smart home](https://www.home-assistant.io/voice_control/)
- Home Assistant：[Matter integration](https://www.home-assistant.io/integrations/matter/)
- Home Assistant：[Understanding automations](https://www.home-assistant.io/docs/automation/basics/)
- Home Assistant GitHub Community：[Home Assistant MCP Server](https://github.com/homeassistant-ai/ha-mcp)
