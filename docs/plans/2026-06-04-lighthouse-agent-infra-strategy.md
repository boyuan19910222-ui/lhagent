# Lighthouse 面向个人开发者的 AI Agent Infra 战略方案

> 本报告基于 2026-06-04 前后的公开资料调研、Lighthouse 既有 Agent Infra 讨论，以及最新定位校准整理。核心前提保持不变：Lighthouse 本身不是 Agent，而是承载、运行、连接和管理 Agent 的基础设施。最新校准是：Lighthouse 重点面向个人开发者群体，企业场景只做浅层覆盖和长期延展，不作为当前主叙事。

## 1. 核心结论

上一版方案把 Lighthouse 放在 “Agent Cloud Runtime + Agent Control Plane” 的位置，这个方向本身成立，但叙事重心偏企业：Registry、Identity、Governance、Audit、Policy 等能力讲得过重，容易把 Lighthouse 做成“小号 Agent 365 / AgentCore”。这不符合 Lighthouse 当前更适合服务个人开发者的产品基因。

个人开发者真正会被打动的不是“企业级控制面”，而是：

- 开源 Agent 能不能一键跑起来。
- 本地 Agent 能不能很快变成云端长期运行的 Agent。
- MCP、模型、Secret、回调、端口、存储这些麻烦事能不能少配一点。
- 我的 Agent 能不能 24 小时在线跑任务，而不是电脑关了就停。
- 我的 Prompt、技能、插件、MCP、记忆、工作流能不能复用和迁移。
- 我做出来的 Agent 能不能分享、展示、被别人 fork、被其他工具调用。
- 成本能不能低，资源能不能可控，失败时能不能看懂。

因此建议把 Lighthouse 的未来定位调整为：

**Lighthouse 是个人开发者的云端 Agent 主机与 Agent 工作台。**

更有产品感的表达是：

**把开源 Agent、MCP 工具、模型能力和个人工作流，装进一台随时在线、低门槛、可扩展的云端 Agent 主机。**

这个定位的关键不是“面向个人开发者做轻量版企业平台”，而是建立个人开发者独有的差异化：

- 比本地 Agent 更稳定：云端常驻、长任务、Webhook、定时任务、远程访问。
- 比开源 Agent 更易用：镜像化、面板化、自动探测、配置向导、内置日志。
- 比普通云主机更 Agent 原生：Manifest、MCP、模型、工具、记忆、任务时间线。
- 比低代码 Agent 平台更自由：支持自定义镜像、主流框架、CLI、代码优先。
- 比模型厂商工具更中立：多模型、多框架、多工具、多客户端。
- 比单个 Agent 产品更可复用：资产库、模板、Gallery、Remix、Share。

一句话总结：

**Lighthouse 不应该先做企业 Agent 控制面，而应该先做个人开发者最顺手的 Agent 云工作台：让任何人能把一个本地或开源 Agent 快速部署为长期在线、可连接、可观测、可分享的云端 Agent 应用。**

## 2. 为什么个人开发者是更合适的切入口

### 2.1 Agent 生态仍处在个人开发者探索期

Agent 生态虽然有大量企业叙事，但真正高频试错的人仍然是个人开发者、独立开发者、开源作者、AI 工具爱好者和小团队技术负责人。他们会频繁尝试：

- OpenClaw、Hermes、Dify、n8n、LangGraph、CrewAI、AutoGen、OpenAI Agents SDK、Google ADK 等工具。
- Claude Desktop、Cursor、Codex、ChatGPT、Comet、各类 IDE 和终端里的 MCP 配置。
- 自己写的小 Agent：GitHub issue 处理、定时报告、网页监控、代码分析、数据库问答、个人知识库、自动发帖、自动归档。
- 多模型组合：OpenAI、Anthropic、Gemini、DeepSeek、Qwen、混合 OpenAI-compatible API。

这类用户的问题不是“有没有企业级治理”，而是“怎么低成本、少折腾、快上线、可持续运行”。他们愿意动手，但不愿意每次都重复处理云主机、依赖、端口、HTTPS、Secret、日志、回调、持久化和模型配置。

Lighthouse 如果能成为这群人的默认 Agent 主机，就能在早期生态中抓住真实使用、真实模板、真实口碑和真实开发者资产。

### 2.2 个人开发者缺的是“Agent 的 Vercel / Railway / Docker Desktop + 云端”

开发者已经习惯了几类优秀工具：

- Vercel：前端项目快速部署、域名、预览、日志。
- Railway / Render：后端和数据库快速跑起来。
- Docker Desktop：本地镜像和服务管理。
- GitHub Actions：自动执行任务。
- VS Code / Cursor：本地开发和 AI 辅助。

但 Agent 的需求比普通 Web App 更复杂：

- 需要模型和工具配置。
- 需要 MCP / API / OAuth / Secret。
- 需要任务状态和长时间执行。
- 需要记忆、文件、产物和上下文。
- 需要看懂 Agent 每一步做了什么。
- 需要能被其他 AI 工具调用。

Lighthouse 的机会是成为：

**Agent 时代的个人开发者云工作台，介于云主机、Agent 应用商店、MCP Hub 和任务运行器之间。**

这个定位比“企业 Agent Control Plane”更贴近 Lighthouse 当前已有的镜像、应用面板、agent-cli、OpenClaw/Hermes 能力，也更容易在个人开发者中形成传播。

### 2.3 个人开发者愿意为“少折腾”和“可展示”付费

个人开发者不是不付费，而是不愿意为抽象平台能力付费。他们愿意为下面这些非常具体的结果付费：

- 我想 10 分钟跑起一个热门开源 Agent。
- 我想把自己的 Agent 分享给朋友试用。
- 我想让 Agent 每天早上自动给我发报告。
- 我想让 Claude / Cursor / Codex 都能用我配置好的同一组 MCP 工具。
- 我想把本地跑通的 Agent 放到云上，不再担心电脑关机。
- 我想看到任务失败在哪里，而不是翻一堆容器日志。
- 我想 fork 别人的 Agent 模板，改几个配置就变成自己的。

这意味着 Lighthouse 的产品包装应该尽量少讲“治理、合规、控制面”，多讲“开箱即用、云端常驻、一键分享、我的 MCP 工具箱、我的 Agent 资产库”。

## 3. Agent 生态趋势对个人开发者意味着什么

### 3.1 OpenAI：Agent 构建体验越来越产品化

OpenAI 通过 Responses API、Agents SDK、AgentKit、ChatKit、Connector Registry、Evals，把 Agent 从“模型调用”推进到“构建、连接、评估、前端嵌入、版本化”。它的方向说明：Agent 开发不再只是写 prompt 和 tool call，而是完整产品工程。

对 Lighthouse 的启发：

- 个人开发者也需要可视化、模板、版本、运行记录和 Eval，但应该轻量化。
- OpenAI 强在模型和 ChatGPT 入口，Lighthouse 不应比“谁的模型更强”。
- Lighthouse 应做中立的云端承载层，让个人开发者可以把 OpenAI、Claude、Gemini、DeepSeek、Qwen 及 OpenAI-compatible 模型混合起来用。

### 3.2 Anthropic / MCP：个人工具链会越来越碎片化

MCP 已经成为 AI 工具连接数据和外部系统的重要标准。个人开发者会在多个客户端里配置 MCP：Claude Desktop、Cursor、Codex、ChatGPT、各类 IDE、本地脚本。问题是配置分散、权限分散、日志分散、Secret 分散。

对 Lighthouse 的启发：

- **个人 MCP Hub** 可以成为 Lighthouse 最强差异点之一。
- 开发者把 MCP Server 配在 Lighthouse，其他客户端通过远程入口复用。
- Lighthouse 管理 MCP 的安装、健康检查、授权、调用记录、Secret、升级和分享。
- 个人开发者可以形成自己的“工具背包”：GitHub、数据库、浏览器、文件、日历、云资源、搜索、知识库。

这比企业治理更贴近个人开发者，也更容易形成日常入口。

### 3.3 Google / A2A：Agent 未来会互相调用，但个人开发者需要简单入口

A2A 的方向是让不同 Agent 可以跨平台协作。对个人开发者来说，A2A 不一定一开始就是复杂多 Agent 网络，而是更简单的需求：

- 我部署的 Agent 能不能被其他 Agent 找到。
- 我能不能把一个 Agent 当成另一个 Agent 的工具。
- 我能不能给自己的 Agent 生成一个 Agent Card。
- 我能不能公开一个只读/受限能力给别人调用。

对 Lighthouse 的启发：

- A2A 不应先做企业协作网络，而应先做“个人 Agent 可被发现和调用”。
- Agent Manifest 可以自然生成 Agent Card。
- Lighthouse 可以让用户选择：私有运行、链接分享、API 暴露、MCP 暴露、A2A 暴露。

### 3.4 AWS / Microsoft / Google Cloud：大厂会做企业平台，Lighthouse 应避开正面竞争

AWS AgentCore、Microsoft Foundry Agent Service、Agent 365、Google Gemini Enterprise 都在强调生产化、企业治理、安全、身份、可观测和多 Agent 协作。这说明 Agent Infra 是大方向，但也说明企业平台会成为大厂主战场。

Lighthouse 如果直接复制这条路，会面临两个问题：

- 个人开发者觉得太重，无法形成早期使用热情。
- 企业客户会自然比较大厂的身份、安全、合规、SaaS 集成能力。

更好的策略是：

- 用个人开发者的开箱即用和低成本建立入口。
- 用腾讯云资源和轻量实例形成运行优势。
- 用开源 Agent 镜像、MCP Hub、个人资产库和分享生态形成差异化。
- 企业治理只做必要底线：权限、日志、Secret、基础隔离，不作为短期卖点。

### 3.5 LangGraph / CrewAI / Dify：框架和低代码都会存在，Lighthouse 应做“运行与分发层”

LangGraph、CrewAI、Dify 代表三种构建方式：代码优先、多 Agent 编排、低代码工作流。个人开发者不会只选一种，他们会不断尝试、组合、迁移。

Lighthouse 的机会不是替代这些框架，而是：

- 让 LangGraph / CrewAI Agent 可以一键部署到云上。
- 让 Dify / n8n / OpenClaw / Hermes 这类应用镜像开箱即用。
- 让框架产出的 Agent 可以共享同一组 MCP、模型、Secret、记忆和运行日志。
- 让开发者从“写 Agent”进入“发布 Agent、分享 Agent、复用 Agent”。

## 4. Lighthouse 的新战略定位

建议用三句话定义 Lighthouse：

1. **对个人开发者：Lighthouse 是把本地 Agent 和开源 Agent 放到云端长期运行的最短路径。**
2. **对 AI 工具玩家：Lighthouse 是统一管理 MCP、模型、Secret、记忆和工作流的个人 Agent 工作台。**
3. **对开源作者：Lighthouse 是发布、展示、分享和复用 Agent 应用的轻量平台。**

不建议把“企业管理员”放进主定位。企业场景可以作为后续延展：

**当个人开发者的 Agent 进入小团队协作时，Lighthouse 再提供基础权限、团队共享、日志和简单审计。**

更完整的产品分层建议调整为：

| 层级 | 面向个人开发者的角色 | 典型能力 |
| --- | --- | --- |
| Agent App Host | 开源 Agent 与自定义 Agent 的云端主机 | 一键部署、镜像管理、端口、HTTPS、持久卷、环境变量 |
| Agent Manifest | Agent 应用说明书 | 能力、依赖、模型、工具、调用入口、默认配置、分享信息 |
| Always-on Runtime | 长期在线的任务执行环境 | 长任务、定时任务、Webhook、后台执行、失败恢复、Artifact |
| Personal MCP Hub | 个人工具连接中心 | MCP 安装、远程访问、健康检查、Secret、日志、客户端复用 |
| Agent Workspace | 个人 Agent 工作台 | 模型配置、Prompt、技能、插件、记忆、知识库、工作流 |
| AgentOps Lite | 看懂 Agent 的运行过程 | 任务时间线、日志、工具调用、Token/成本、错误定位 |
| Agent Gallery | 展示、分享和 Remix 入口 | 模板、公开 Demo、Fork、安装链接、README、API/MCP 暴露 |
| Team Lite | 浅层团队能力 | 成员共享、基础权限、项目空间、简单审计、成本汇总 |

这个结构里，企业治理不再是核心层，而是 Team Lite 的后续能力。

## 5. Lighthouse 面向个人开发者的七个差异化支点

### 5.1 一键开箱：热门开源 Agent 的云端应用商店

个人开发者对 Agent 的第一需求往往不是“从零开发”，而是“先让我跑起来”。Lighthouse 可以把 OpenClaw、Hermes、Dify、n8n、LangGraph 示例、CrewAI 示例、浏览器 Agent、代码 Agent、数据分析 Agent 做成一键应用。

关键体验：

- 点选模板或镜像。
- 选择轻量实例规格。
- 填模型 Key 或选择已保存模型配置。
- 自动检测端口、健康检查、默认账号、文档入口。
- 部署完成后直接进入 Agent 面板。

差异点不是“我也有镜像市场”，而是 Agent 原生：

- 镜像页面展示这个 Agent 能做什么、需要哪些模型和工具、能接哪些 MCP。
- 部署后自动生成 Agent Manifest。
- 面板里能看到任务、工具调用、成本和配置。
- 可一键公开 demo 或生成分享链接。

### 5.2 Personal MCP Hub：我的工具只配一次，到处可用

这是最适合个人开发者的核心卖点。

现在 MCP 最大的问题是碎片化：每个客户端都要配一遍，Secret 到处散落，工具是否可用很难检查，出了问题也没有统一日志。

Lighthouse 可以提供：

- MCP Server 一键安装和托管。
- 远程 MCP endpoint。
- Secret 和 OAuth 统一保存。
- 工具健康检查和调用测试。
- 调用日志和失败定位。
- 客户端配置片段生成：Claude、Cursor、Codex、ChatGPT、自定义脚本。
- 工具分组：开发、数据库、浏览器、云资源、办公、搜索、个人知识库。

产品表达：

**把 Lighthouse 变成你的云端 MCP 工具箱。一次配置，所有 Agent 和 AI 客户端都能用。**

这比企业级 MCP 治理更轻，但足够有吸引力。

### 5.3 Always-on Agent Runtime：让 Agent 从本地玩具变成长期在线的个人助手

本地 Agent 最大的问题是不能长期运行：

- 电脑关机就停。
- 网络回调接不进来。
- 定时任务不稳定。
- 浏览器、文件、依赖环境容易乱。
- 长任务跑一半失败很难恢复。

Lighthouse 可以把轻量云主机的优势转化为 Agent 叙事：

- 定时任务：每天生成报告、巡检网站、同步资料。
- Webhook：接 GitHub、飞书、邮件、RSS、监控告警。
- 长任务：研究、爬取、分析、批量生成、代码处理。
- 后台运行：任务跑完通知用户。
- 产物保存：报告、截图、代码 diff、文件包、数据结果。
- 失败恢复：保留中间产物，提示失败步骤。

产品表达：

**你的 Agent 不再只能在本地窗口里聊天，而是可以在云端替你持续干活。**

### 5.4 Agent Workspace：个人 Agent 资产库

个人开发者会积累很多 Agent 资产：

- Prompt。
- System instruction。
- 技能和插件。
- MCP Server。
- 模型配置。
- API Key / Secret。
- 记忆和知识库。
- 工作流。
- Agent 模板。
- 任务产物。

如果这些资产散落在不同 Agent、不同 IDE、不同机器里，复用成本会很高。Lighthouse 可以做成个人 Agent 资产库：

- 一个模型配置可被多个 Agent 使用。
- 一个 MCP 工具组可挂到多个 Agent。
- 一个 Prompt / skill 可 fork 和复用。
- 一个 Agent 的记忆或知识库可迁移到另一个 Agent。
- 一个工作流模板可复制成新的 Agent。

这会让 Lighthouse 从“部署工具”变成“个人 Agent 操作系统”的雏形，但仍然保持个人开发者语境。

### 5.5 AgentOps Lite：不是企业观测，而是个人开发者能看懂的任务时间线

AgentOps 在个人开发者场景里不应包装成复杂监控平台，而应回答几个直白问题：

- 我的 Agent 卡在哪里了？
- 这次为什么失败？
- 哪个工具调用错了？
- 花了多少 token 和钱？
- 生成了哪些文件？
- 它有没有进入死循环？
- 我能不能从某一步继续？

建议做“任务时间线”：

- 用户目标。
- Agent 计划摘要。
- 模型调用。
- 工具/MCP 调用。
- 文件和 Artifact。
- 错误和重试。
- 成本和耗时。
- 最终结果。

个人开发者不需要完整 APM，但需要“看得懂”。这会比普通容器日志强很多。

### 5.6 Share / Remix / Gallery：让个人开发者有展示和传播空间

个人开发者喜欢分享成果。Lighthouse 可以把 Agent 部署变成可展示资产：

- 公开 Agent Demo 页面。
- 一键生成 README 和部署说明。
- 分享运行链接。
- Fork 别人的 Agent 模板。
- Remix Prompt、MCP 工具组、模型配置。
- 生成 “Deploy on Lighthouse” 按钮。
- 将 Agent 暴露为 API / MCP Tool / A2A Agent。

产品表达：

**不只是自己跑 Agent，也能把 Agent 作品发布出去。**

这会帮助 Lighthouse 建立社区感，而不是只作为云控制台存在。

### 5.7 低成本和轻量化：个人开发者敢试、敢常驻

个人开发者对成本非常敏感。Lighthouse 的优势本来就是轻量云资源，需要在 Agent 场景里明确表达：

- 免费/低价试用模板。
- 轻量实例推荐。
- 空闲休眠。
- 按任务启动托管 Agent 应用（只适用于 Lighthouse 云端托管任务）。
- Token 和云资源成本估算。
- 成本上限提醒。
- 一键暂停 Agent。
- 删除实例前导出资产。

如果 Lighthouse 能让开发者放心试错，就比企业级平台更容易形成使用习惯。

## 6. 产品路线图建议

### 阶段一：Agent 应用主机化，用 OpenClaw / Hermes 做样板

目标：让用户看到 Lighthouse 不只是云主机，而是能一键运行 Agent 应用的云端主机。

建议优先事项：

- 统一 OpenClaw / Hermes 应用面板，但叙事改为“Agent 应用主机样板”。
- 每个 Agent 镜像提供清晰的能力说明、模型需求、工具需求、默认配置和文档入口。
- 部署后自动生成 Agent Manifest，并在面板中可视化。
- 提供模型配置向导、MCP 配置入口、Secret 管理、健康检查。
- 更新日志记录 Agent 能力、模型兼容性、工具变化、面板变化。

判断标准：

- 个人开发者能 10 分钟内跑起一个 Agent 应用。
- 跑起来后知道它能做什么、怎么配置模型、怎么接工具、怎么分享。

### 阶段二：Personal MCP Hub 成为高频入口

目标：让 Lighthouse 成为开发者管理 MCP 工具的默认位置。

建议能力：

- MCP Server 目录和一键安装。
- 远程 MCP endpoint。
- 客户端配置片段自动生成。
- Secret / OAuth 管理。
- 工具调用测试、健康检查、日志。
- MCP 工具组：按用途保存和复用。
- 支持 Agent 应用直接挂载某个 MCP 工具组。

判断标准：

- 用户愿意把 GitHub、数据库、浏览器、云资源等 MCP 工具放在 Lighthouse 管。
- 用户能在 Claude / Cursor / Codex / 自己的 Agent 中复用同一套工具。

### 阶段三：Always-on Runtime 与任务时间线

目标：让本地 Agent 变成长期在线的个人执行系统。

建议能力：

- 定时任务。
- Webhook 触发。
- 后台任务。
- 长任务状态。
- 任务产物保存。
- 失败重试和从中间步骤恢复。
- AgentOps Lite 任务时间线。
- Token、耗时、资源成本统计。

判断标准：

- 用户会把“每天/每周/每次事件触发”的 Agent 任务放到 Lighthouse 上跑。
- 任务失败时，用户能通过时间线定位问题，而不是只看容器日志。

### 阶段四：agent-cli 与主流框架导入

目标：服务 code-first 个人开发者。

建议能力：

- `agent-cli init`：生成 Manifest。
- `agent-cli probe`：探测端口、依赖、模型、MCP、健康检查。
- `agent-cli deploy`：部署 Agent。
- `agent-cli logs`：查看日志。
- `agent-cli tasks`：查看任务。
- `agent-cli export`：导出 Agent 资产。
- 首批支持 LangGraph、CrewAI、OpenAI Agents SDK / Google ADK 中的 2-3 个。

判断标准：

- 一个开发者能从本地 Agent repo 快速部署到 Lighthouse。
- 开发者感觉 Lighthouse 是“我的 Agent 发布工具”，不是只给官方镜像用。

### 阶段五：Agent Gallery / Remix / Share

目标：形成个人开发者社区和生态传播。

建议能力：

- Agent 模板库。
- 公开 Demo 页。
- “Deploy on Lighthouse” 按钮。
- Fork / Remix Agent。
- 分享 MCP 工具组和 Prompt 模板。
- Agent 暴露为 API / MCP Tool / A2A Agent。
- 作者页、项目页、使用统计。

判断标准：

- 用户不仅用 Lighthouse 跑 Agent，还愿意把作品发给别人。
- 社区模板能反向带动更多用户部署和改造。

### 阶段六：Team Lite，而不是重企业治理

目标：让个人项目自然扩展到小团队，而不是直接做企业控制面。

建议能力：

- 项目空间。
- 成员邀请。
- 基础权限：查看、编辑、运行、管理。
- 共享模型配置和 MCP 工具组。
- 简单成本汇总。
- 基础日志和操作记录。

判断标准：

- 两三个人的小团队可以一起维护一个 Agent 项目。
- 不引入复杂企业术语，不把产品体验做重。

## 7. 优先级建议

### P0：个人开发者最先感知的能力

- OpenClaw / Hermes Agent 应用主机样板。
- Agent Manifest 可视化。
- 模型配置向导。
- MCP Server 最小管理能力。
- 远程 MCP endpoint。
- Agent 任务时间线基础版。
- 成本和 Token 展示。
- 一键暂停/恢复 Agent。

### P1：形成差异化入口

- Personal MCP Hub 完整版。
- 定时任务和 Webhook 触发。
- Agent 产物保存。
- `agent-cli init / probe / deploy / logs`。
- 自定义 Agent 镜像导入。
- Agent 资产库：Prompt、MCP 工具组、模型配置复用。
- 分享链接和公开 Demo 页。

### P2：生态增长能力

- Agent Gallery。
- Fork / Remix。
- Deploy on Lighthouse 按钮。
- Agent 暴露为 API / MCP Tool / A2A Agent。
- 主流框架导入模板。
- 个人作者页。
- Team Lite。

### 暂缓：企业味过重的能力

- 影子 Agent 发现。
- 复杂 Agent Identity。
- 企业级 Policy。
- 合规审计报表。
- 大规模组织拓扑图。
- Defender / Purview 类安全叙事。

这些能力不是完全不要，而是不应作为当前方案的核心卖点。

## 8. 产品包装建议

### 8.1 主标题

可选方向：

1. **Lighthouse Agent Host：个人开发者的云端 Agent 主机**
2. **把你的 Agent 跑在云端，长期在线，随时可用**
3. **一键运行开源 Agent，统一管理 MCP 工具和模型配置**
4. **从本地 Agent 原型，到可分享的云端 Agent 应用**

推荐：

**Lighthouse Agent Host：个人开发者的云端 Agent 主机**

### 8.2 核心介绍语

建议文案：

**Lighthouse Agent Host 面向个人开发者，提供一台低门槛、可扩展、随时在线的云端 Agent 主机。你可以一键运行 OpenClaw、Hermes 等开源 Agent 应用，集中管理 MCP 工具、模型配置、Secret 和个人 Agent 资产，把本地原型部署为长期运行、可观测、可分享、可复用的云端 Agent。**

### 8.3 开发者卖点

- **一键跑 Agent**：热门开源 Agent 镜像开箱即用。
- **云端长期在线**：支持定时任务、Webhook、后台执行和长任务。
- **MCP 工具只配一次**：统一管理 MCP Server，多个客户端和 Agent 复用。
- **模型自由选择**：支持多模型和 OpenAI-compatible API。
- **任务过程看得懂**：时间线展示模型调用、工具调用、产物、成本和错误。
- **资产可复用**：Prompt、工具组、模型配置、记忆和工作流可迁移。
- **作品可分享**：公开 Demo、分享链接、Fork 模板、Deploy on Lighthouse。
- **低成本可控**：轻量实例、暂停恢复、成本上限和资源建议。

### 8.4 不建议的表达

短期不建议把这些词放在主标题或第一屏：

- 企业级 Agent 控制面。
- 统一治理平台。
- 合规审计。
- 影子 Agent 管理。
- 零信任 Agent Identity。
- 大规模组织 Agent Fleet。

这些词会让个人开发者觉得产品离自己很远。

## 9. 关键风险与取舍

### 风险一：被做成普通云主机的 Agent 皮肤

如果只是把 Agent 镜像放到云主机上，差异化不够。必须强化 Agent 原生能力：Manifest、MCP、模型配置、任务时间线、Artifact、分享。

### 风险二：被做成低代码 Agent 平台

Lighthouse 不应该变成另一个 Dify。个人开发者需要自由度，必须保留自定义镜像、CLI、框架导入和代码优先路径。

### 风险三：MCP Hub 做得太像企业网关

个人开发者想要的是“我的工具箱”，不是“安全网关”。优先做安装、复用、日志、Secret、客户端配置生成；风险评分和策略可以后置。

### 风险四：分享生态没有足够低门槛

如果分享 Agent 还要写文档、配域名、手动暴露 API，就很难传播。需要一键生成 Demo、README、部署按钮和复制模板。

### 风险五：成本不可控会直接劝退个人开发者

Agent 容易产生 token、工具调用、云资源和长任务成本。必须从第一天就给出暂停、上限、估算和提醒。

### 风险六：过早强调企业能力导致产品变重

基础权限和团队共享可以做，但不要把企业治理变成主线。Lighthouse 当前更适合先吃个人开发者和小团队，再自然长到更复杂场景。

## 10. 建议的一句话方向

如果要给内部定一个方向，可以这样写：

**Lighthouse 面向 AI Agent 时代，重点从“轻量云主机”升级为“个人开发者的云端 Agent 主机”：以开源 Agent 镜像和自定义 Agent 部署为入口，以 Personal MCP Hub 连接工具和数据，以 Always-on Runtime 承载长任务和自动化工作流，以 AgentOps Lite 让开发者看懂运行过程，以 Agent Gallery 支持分享、Fork 和 Remix，最终形成个人开发者构建、运行、复用和发布 Agent 的云工作台。**

## 11. 与上一版方案的关键调整

| 维度 | 上一版偏向 | 本版调整 |
| --- | --- | --- |
| 核心用户 | 开发者 + 企业 | 个人开发者优先，小团队次之，企业浅层延展 |
| 核心定位 | Agent Cloud Runtime + Agent Control Plane | 个人开发者的云端 Agent 主机与 Agent 工作台 |
| 主卖点 | 可治理、可审计、可管理 | 开箱即用、长期在线、MCP 复用、低成本、可分享 |
| Registry | 企业 Agent 目录 | 个人 Agent 资产库和 Gallery |
| Governance | 核心层 | 后置为 Team Lite / 基础权限 |
| AgentOps | 生产观测 | 个人开发者能看懂的任务时间线 |
| Marketplace | 企业/生态分发 | 开源 Agent 模板、Demo、Fork、Deploy on Lighthouse |
| MCP | 可治理连接层 | 个人 MCP Hub，我的工具只配一次 |

## 12. 参考资料

- OpenAI：[Introducing AgentKit](https://openai.com/index/introducing-agentkit/)
- OpenAI：[New tools for building agents](https://openai.com/index/new-tools-for-building-agents/)
- Anthropic：[Introducing the Model Context Protocol](https://www.anthropic.com/news/model-context-protocol)
- Google Developers Blog：[Announcing the Agent2Agent Protocol](https://developers.googleblog.com/en/a2a-a-new-era-of-agent-interoperability/)
- Google Cloud Blog：[Announcing a complete developer toolkit for scaling A2A agents on Google Cloud](https://cloud.google.com/blog/products/ai-machine-learning/agent2agent-protocol-is-getting-an-upgrade/)
- Google ADK：[Agent Development Kit technical overview](https://adk.dev/get-started/about/)
- Google Cloud：[Gemini Enterprise app](https://cloud.google.com/gemini-enterprise)
- Microsoft Learn：[Foundry Agent Service overview](https://learn.microsoft.com/en-us/azure/foundry/agents/overview)
- Microsoft 365 Blog：[Microsoft Agent 365: The control plane for AI agents](https://www.microsoft.com/en-us/microsoft-365/blog/2025/11/18/microsoft-agent-365-the-control-plane-for-ai-agents/)
- Microsoft Learn：[Agent Registry convergence with Microsoft Agent 365](https://learn.microsoft.com/en-us/entra/agent-id/agent-registry-convergence)
- AWS：[Amazon Bedrock AgentCore is now generally available](https://aws.amazon.com/about-aws/whats-new/2025/10/amazon-bedrock-agentcore-available/)
- AWS Docs：[Amazon Bedrock AgentCore overview](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/)
- LangChain：[LangGraph Platform is generally available](https://www.langchain.com/blog/langgraph-platform-ga)
- LangChain：[On Agent Frameworks and Agent Observability](https://www.langchain.com/blog/on-agent-frameworks-and-agent-observability)
- CrewAI Docs：[CrewAI AMP introduction](https://docs.crewai.com/en/enterprise/introduction)
- Dify：[Build Production-Ready AI Agent](https://dify.ai/)
- Cloud Security Alliance：[82% of enterprises have unknown AI agents](https://cloudsecurityalliance.org/press-releases/2026/04/21/new-cloud-security-alliance-survey-reveals-82-of-enterprises-have-unknown-ai-agents-in-their-environments)
- OWASP：[Agent Security Initiative](https://owasp.org/www-project-top-10-for-large-language-model-applications/initiatives/agent_security_initiative/)
- Deloitte：[State of AI in the Enterprise 2026 press release](https://www.deloitte.com/us/en/about/press-room/state-of-ai-report-2026.html)
- TrueFoundry / Business Wire：[Enterprise AI Gateway Report 2026 press release](https://www.businesswire.com/news/home/20260514715268/en/TrueFoundry-Survey-Finds-Most-Enterprises-Cannot-Audit-Their-AI-Systems-as-Agent-Adoption-Surges)
