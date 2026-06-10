# OpenClaw 错误可读化方案

## 目标

当 OpenClaw 在 QQ 等通道中因为模型供应商异常而无法回复时，不把原始 API 错误直接抛给个人用户，而是返回一段“看得懂、知道去哪处理”的说明。

示例：MiniMax 账户余额不足时，用户看到：

```text
⚠️ MiniMax 模型服务余额不足或账户欠费，OpenClaw 暂时无法继续回复。

当前模型：abab6.5-chat
处理方式：请打开 MiniMax 平台充值或续费，然后回到当前对话重试。
充值入口：https://platform.minimaxi.com/console/recharge-records

如果已经充值仍然失败，请检查 OpenClaw 里配置的 MiniMax API Key 是否属于刚充值的账号。
```

## 服务器研究结论

本次研究的 Lighthouse 镜像中，OpenClaw 不是 Docker 部署，而是 pnpm 全局安装的 Node 服务：

```text
/home/ubuntu/.nvm/versions/node/v22.22.3/bin/node \
  /home/ubuntu/.local/share/pnpm/global/5/.pnpm/openclaw@2026.5.28/node_modules/openclaw/dist/index.js \
  gateway --port 10509
```

用户级 systemd 服务：

```text
/home/ubuntu/.config/systemd/user/openclaw-gateway.service
```

OpenClaw 自身已经有错误分类层：

```text
dist/sanitize-user-facing-text-CY8fNjm7.js
```

其中 `isBillingErrorMessage()` 已经能识别：

- `HTTP 402`
- `payment required`
- `insufficient credits`
- `insufficient quota`
- `insufficient balance`
- `余额不足`
- `欠费`

回复分发层位于：

```text
dist/reply-turn-admission-BaGuBaDP.js
```

账单错误原本统一返回 `BILLING_ERROR_USER_MESSAGE`，信息较通用，缺少供应商链接和面向小白用户的处理步骤。

后续实测中还观察到一类容易漏判的欠费错误：

```text
403 The request failed because your account has an overdue balance.
```

OpenClaw 原本会把这类 `403 + overdue balance` 归到认证/通用失败路径，最终用户可能只看到：

```text
⚠️ Something went wrong while processing your request. Please try again, or use /new to start a fresh session.
```

这不是 LHAgent MiniMax 文案，而是 OpenClaw 自带的通用失败兜底。当前补丁已经把 `overdue balance` 和 `account has an overdue balance` 也纳入账单错误识别。

对火山引擎方舟/豆包相关 provider，账单错误文案会直接给出 API 管理入口：

```text
https://console.volcengine.com/ark/region:ark+cn-beijing/apiKey
```

这样小白用户可以直接进入火山引擎方舟控制台检查账号状态、API Key 和计费配置。

## 本次服务器最小补丁

已经在服务器上做了一个窄补丁：

1. 在 `reply-turn-admission-BaGuBaDP.js` 中引入 `formatBillingErrorMessage`。
2. 在“模型运行失败且被判定为 billing error”的分支里，把固定文案替换为：

```js
formatBillingErrorMessage(
  attemptedRuntimeProvider ?? params.followupRun.run.provider,
  attemptedRuntimeModel ?? params.followupRun.run.model
)
```

3. 在 `sanitize-user-facing-text-CY8fNjm7.js` 的 `formatBillingErrorMessage(provider, model)` 中增加 MiniMax 专属中文文案和充值入口，并为火山引擎方舟/豆包增加 API 管理入口。

补丁验证：

- `node --check reply-turn-admission-BaGuBaDP.js` 通过
- `node --check sanitize-user-facing-text-CY8fNjm7.js` 通过
- `systemctl --user restart openclaw-gateway.service` 后服务为 `active`
- `formatBillingErrorMessage("minimax", "abab6.5-chat")` 能返回 MiniMax 专属文案

备份文件保留在服务器原目录下，文件名后缀为 `.lhagent-bak-<timestamp>`。

## 产品化建议

不建议长期依赖手改 OpenClaw 编译产物。更稳的产品化路线是做一个“错误可读化规则层”：

```mermaid
flowchart LR
  User["QQ 用户消息"] --> Channel["QQ 通道"]
  Channel --> OpenClaw["OpenClaw Gateway"]
  OpenClaw --> Model["模型供应商"]
  Model -->|正常响应| OpenClaw
  OpenClaw -->|正常回复| Channel
  Model -->|异常响应| Guard["错误可读化规则层"]
  Guard --> Channel
```

规则层可以有两种落地方式：

1. 内嵌到 OpenClaw 的错误格式化层：最少网络链路、最稳定，适合官方镜像或插件能力支持时使用。
2. 外挂独立网关：监听原 OpenClaw 端口前面，正常请求透传，只对错误响应做规则翻译，适合 Lighthouse 镜像快速灰度。

对于当前 OpenClaw 结构，优先推荐第 1 种：错误已经在 OpenClaw 内部被分类为 billing/rate limit/auth/context overflow，直接在这里增强文案，避免外层网关看不到完整 provider/model 上下文。

## 原型代码

`experiments/openclaw-billing-guardian/src/openclaw-error-translator.js` 提供一个可独立测试的规则模块，当前支持：

- MiniMax 欠费/余额不足识别
- 英文和中文账单错误关键词识别
- MiniMax 专属中文处理说明
- 火山引擎方舟/豆包专属中文处理说明和 API 管理入口
- 非目标错误返回 `null`，表示继续透传

为了避免把用户会话内容误判成模型错误，规则模块的新接入方式优先使用结构化 provider error：

```js
formatReadableProviderError({
  provider: "minimax",
  model: "abab6.5-chat",
  error: {
    source: "provider_error",
    status: 402,
    message: "MiniMax API error (402): insufficient balance"
  }
});
```

分类顺序是：先确认 `source` 是 `provider_error`，再优先读取 `status`、`code`、`type` 等结构化字段，最后才对 provider 返回的错误消息做关键词兜底。用户输入、聊天历史、普通回复文本即使包含 `HTTP 402`、`insufficient balance`、`余额不足` 等词，也应以 `source: "conversation"` 或不进入规则层的方式排除。

运行测试：

```bash
npm test
```

## 服务器补丁脚本

`experiments/openclaw-billing-guardian/scripts/patch-openclaw-billing-message.mjs` 可以在 OpenClaw 镜像服务器上重复应用这次最小补丁：

```bash
npm run patch:openclaw-billing -- --dry-run
npm run patch:openclaw-billing
systemctl --user restart openclaw-gateway.service
```

如果 OpenClaw 版本或安装路径变化，可以显式指定 dist 目录：

```bash
npm run patch:openclaw-billing -- --dist /path/to/openclaw/dist
```

脚本会：

- 修改账单错误分支，让它根据当前 provider/model 生成文案
- 将 `overdue balance` 纳入账单错误识别，避免欠费错误落到通用失败文案
- 增加 MiniMax 专属中文说明和充值入口
- 增加火山引擎方舟/豆包专属中文说明和 API 管理入口
- 给被修改文件创建 `.lhagent-bak-<timestamp>` 备份
- 对修改后的 OpenClaw 文件执行 `node --check`
- 已应用过时保持幂等，不重复改写

补丁后可以用只读验收脚本确认效果：

```bash
npm run verify:openclaw-billing
```

它会检查：

- OpenClaw 的 `sanitize-user-facing-text-*.js` 文件存在
- `isBillingErrorMessage()` 能把 `MiniMax API error (402): insufficient balance` 识别为账单错误
- `isBillingErrorMessage()` 能把 `account has an overdue balance` 识别为账单错误
- `formatBillingErrorMessage("minimax", "abab6.5-chat")` 返回 MiniMax 文案
- 返回文案包含当前模型名和 MiniMax 充值入口
- `formatBillingErrorMessage("doubao", "...")` 返回火山引擎方舟/豆包文案
- 返回文案包含火山引擎 API 管理入口

## 持久化安装

为了避免 OpenClaw gateway 重启后漏掉补丁，可以把补丁脚本安装为用户级 systemd 的 `ExecStartPre` 钩子：

```bash
npm run install:openclaw-billing-guardian -- --dry-run --no-systemctl
npm run install:openclaw-billing-guardian
systemctl --user restart openclaw-gateway.service
npm run verify:openclaw-billing
```

默认会写入：

```text
/home/ubuntu/.openclaw/lhagent/scripts/patch-openclaw-billing-message.mjs
/home/ubuntu/.openclaw/lhagent/scripts/verify-openclaw-billing-message.mjs
/home/ubuntu/.config/systemd/user/openclaw-gateway.service.d/lhagent-billing-guardian.conf
```

drop-in 内容会在 `openclaw-gateway.service` 启动前执行：

```text
ExecStartPre=<node> patch-openclaw-billing-message.mjs --dist <openclaw-dist> --soft-fail
```

`--soft-fail` 只用于服务启动钩子：如果未来 OpenClaw 升级后编译文件名变化，补丁脚本会记录跳过信息并允许 gateway 继续启动，避免因为错误提示增强能力失效而影响主服务可用性。手动执行补丁脚本时不建议加 `--soft-fail`，这样能尽早发现版本不兼容。

回滚持久化钩子：

```bash
rm ~/.config/systemd/user/openclaw-gateway.service.d/lhagent-billing-guardian.conf
systemctl --user daemon-reload
systemctl --user restart openclaw-gateway.service
```

如果需要回滚已改写的 OpenClaw 编译文件，可以使用同目录下 `.lhagent-bak-<timestamp>` 备份文件恢复。
