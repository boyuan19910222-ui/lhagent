import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { describe, it } from "node:test";
import { fileURLToPath } from "node:url";

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const verifyScript = path.join(repoRoot, "scripts", "verify-openclaw-billing-message.mjs");

function makePatchedDistFixture() {
  const dir = mkdtempSync(path.join(tmpdir(), "lhagent-openclaw-verify-"));
  writeFileSync(
    path.join(dir, "sanitize-user-facing-text-CY8fNjm7.js"),
    [
      "function isBillingErrorMessage(raw) {",
      "  return /402|insufficient balance|overdue balance|欠费|余额不足/u.test(String(raw));",
      "}",
      "function formatBillingErrorMessage(provider, model) {",
      "  if (provider === 'doubao') return `⚠️ 火山引擎方舟/豆包模型服务返回了账单错误\\n当前模型：${model}\\nAPI 管理入口：https://console.volcengine.com/ark/region:ark+cn-beijing/apiKey`;",
      "  return `⚠️ MiniMax 模型服务余额不足或账户欠费\\n当前模型：${model}\\n充值入口：https://platform.minimaxi.com/console/recharge-records`;",
      "}",
      "export { isBillingErrorMessage as m, formatBillingErrorMessage as n };",
      ""
    ].join("\n")
  );
  return dir;
}

function runVerify(...args) {
  return spawnSync(process.execPath, [verifyScript, ...args], {
    encoding: "utf8"
  });
}

describe("verify-openclaw-billing-message", () => {
  it("verifies a patched OpenClaw sanitize module", () => {
    const dist = makePatchedDistFixture();
    try {
      const result = runVerify("--dist", dist);
      assert.equal(result.status, 0, result.stderr || result.stdout);

      const payload = JSON.parse(result.stdout);
      assert.equal(payload.ok, true);
      assert.equal(payload.isBilling, true);
      assert.equal(payload.isOverdueBilling, true);
      assert.equal(payload.containsRechargeUrl, true);
      assert.equal(payload.containsVolcengineApiUrl, true);
      assert.match(payload.message, /MiniMax/u);
    } finally {
      rmSync(dist, { force: true, recursive: true });
    }
  });

  it("fails when the OpenClaw sanitize file is missing", () => {
    const dist = mkdtempSync(path.join(tmpdir(), "lhagent-openclaw-verify-missing-"));
    try {
      mkdirSync(path.join(dist, "nested"));
      const result = runVerify("--dist", dist);
      assert.notEqual(result.status, 0);
      assert.match(result.stderr, /sanitize file not found/i);
    } finally {
      rmSync(dist, { force: true, recursive: true });
    }
  });
});
