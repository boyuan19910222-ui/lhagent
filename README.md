# LHAgent

LHAgent 是一个面向腾讯云 Lighthouse 场景的 AI Agent 产品边界研究仓库。

当前第一版聚焦一个很具体但高频的体验问题：当 OpenClaw 接入的模型供应商因为欠费、余额不足、额度耗尽或 API Key 配置异常而失败时，不让 QQ/IM 里的普通用户只看到一段英文报错或通用失败提示，而是返回一段“看得懂、知道去哪处理”的中文说明。

## 当前能力

- 识别模型供应商账单类错误，例如 `HTTP 402`、`insufficient balance`、`overdue balance`、`余额不足`、`欠费`。
- 为 MiniMax 返回中文处理说明和充值入口。
- 为火山引擎方舟/豆包返回中文处理说明，并直接给出 API 管理入口：
  <https://console.volcengine.com/ark/region:ark+cn-beijing/apiKey>
- 提供可重复执行的 OpenClaw 编译产物补丁脚本。
- 提供只读验收脚本，确认 OpenClaw 当前版本是否已经具备目标文案能力。
- 提供 systemd 用户服务 drop-in 安装脚本，让补丁在 OpenClaw gateway 重启前自动补齐。

## 为什么做这个

Lighthouse 很适合作为个人或小团队运行 AI Agent 的轻量云主机，但 AI 时代的“可用性”不只取决于服务器是否在线，还取决于模型账号、API Key、余额、额度、供应商控制台配置等外部依赖是否健康。

如果这些错误直接暴露给小白用户，用户通常不知道：

- 是服务器坏了，还是模型账号欠费了；
- 该去哪个平台处理；
- 处理完以后是否可以直接重试；
- API Key 是否属于刚充值的账号。

LHAgent 的研究方向，是把这些底层依赖错误翻译成面向用户和运维者的下一步动作，让 Lighthouse 上运行的 Agent 更像一个完整产品，而不是一组脆弱脚本。

## 快速开始

安装依赖不是必须的，当前项目只使用 Node.js 标准库。建议使用 Node.js 22 或更新版本。

```bash
npm test
```

本地规则模块位于：

```text
src/openclaw-error-translator.js
```

它可以把供应商原始错误翻译成更可读的中文提示；非目标错误会返回 `null`，由上层继续走原有逻辑。

## OpenClaw 服务器补丁

在 OpenClaw 所在服务器上，可以先 dry-run 看看将要修改什么：

```bash
npm run patch:openclaw-billing -- --dry-run
```

确认后应用补丁：

```bash
npm run patch:openclaw-billing
systemctl --user restart openclaw-gateway.service
```

验证当前 OpenClaw 是否已经返回目标文案：

```bash
npm run verify:openclaw-billing
```

如果 OpenClaw 安装路径不是默认路径，可以显式指定 dist 目录：

```bash
npm run patch:openclaw-billing -- --dist /path/to/openclaw/dist
npm run verify:openclaw-billing -- --dist /path/to/openclaw/dist
```

## 持久化安装

为了避免 OpenClaw gateway 重启后补丁丢失，可以安装 systemd 用户服务启动前钩子：

```bash
npm run install:openclaw-billing-guardian -- --dry-run --no-systemctl
npm run install:openclaw-billing-guardian
systemctl --user restart openclaw-gateway.service
npm run verify:openclaw-billing
```

默认会写入：

```text
~/.openclaw/lhagent/scripts/patch-openclaw-billing-message.mjs
~/.openclaw/lhagent/scripts/verify-openclaw-billing-message.mjs
~/.config/systemd/user/openclaw-gateway.service.d/lhagent-billing-guardian.conf
```

drop-in 会在 `openclaw-gateway.service` 启动前执行补丁脚本。服务启动场景下默认使用 `--soft-fail`，避免未来 OpenClaw 升级导致文件名变化时影响 gateway 主服务启动。

## 项目结构

```text
docs/
  openclaw-error-guardian.md        # 研究记录、服务器结论和产品化建议
scripts/
  patch-openclaw-billing-message.mjs
  verify-openclaw-billing-message.mjs
  install-openclaw-billing-guardian.mjs
src/
  openclaw-error-translator.js
test/
  *.test.js
```

## 当前研究结论

本次实测的 Lighthouse 镜像中，OpenClaw 是 pnpm 全局安装的 Node 服务，并通过用户级 systemd 运行 `openclaw-gateway.service`。OpenClaw 已经有错误分类层，但原始账单错误文案较通用，且 `403 + overdue balance` 容易落到通用失败兜底。

当前补丁把 `overdue balance` 纳入账单错误识别，并在 billing 分支按 provider/model 生成更具体的中文说明。

更完整的研究记录见：

```text
docs/openclaw-error-guardian.md
```

## 后续方向

- 扩展更多模型供应商的错误可读化规则。
- 增加 Lighthouse 运维侧健康检查，例如模型账号余额、API Key 可用性、网关服务状态。
- 将错误规则层从“补丁脚本”演进成 OpenClaw 插件或独立网关能力。
- 沉淀成面向小白用户的一键修复流程，让 Lighthouse 上的 AI Agent 更容易被非工程用户稳定使用。
