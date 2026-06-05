import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { mkdtempSync, readFileSync, readdirSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { describe, it } from "node:test";
import { fileURLToPath } from "node:url";

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const patchScript = path.join(repoRoot, "scripts", "patch-openclaw-billing-message.mjs");

const replyFixture = `import { _ as isRateLimitErrorMessage, d as sanitizeUserFacingText, h as isOverloadedErrorMessage, i as formatRateLimitOrOverloadedErrorCopy, m as isBillingErrorMessage, t as BILLING_ERROR_USER_MESSAGE } from "./sanitize-user-facing-text-CY8fNjm7.js";

function demo() {
\treturn {
\t\ttext: isBilling ? BILLING_ERROR_USER_MESSAGE : isRateLimit && !isOverloadedErrorMessage(message) ? buildRateLimitCooldownMessage(err) : "ok"
\t};
}
`;

const sanitizeFixture = `function normalizeLowercaseStringOrEmpty(value) {
\treturn String(value ?? "").toLowerCase();
}

const ERROR_PATTERNS = {
\tbilling: [
\t\t"insufficient usd or diem balance",
\t\t"欠费"
\t]
};

function formatBillingErrorMessage(provider, model) {
\tconst providerName = provider?.trim();
\tconst modelName = model?.trim();
\tconst providerLabel = providerName && modelName ? \`\${providerName} (\${modelName})\` : providerName || void 0;
\tif (providerLabel) return \`⚠️ \${providerLabel} returned a billing error -- your API key has run out of credits or has an insufficient balance. Check your \${providerName} billing dashboard and top up or switch to a different API key.\`;
\treturn "⚠️ API provider returned a billing error -- your API key has run out of credits or has an insufficient balance. Check your provider's billing dashboard and top up or switch to a different API key.";
}
const BILLING_ERROR_USER_MESSAGE = formatBillingErrorMessage();
export { formatBillingErrorMessage as n };
`;

function makeDistFixture() {
  const dir = mkdtempSync(path.join(tmpdir(), "lhagent-openclaw-dist-"));
  writeFileSync(path.join(dir, "reply-turn-admission-BaGuBaDP.js"), replyFixture);
  writeFileSync(path.join(dir, "sanitize-user-facing-text-CY8fNjm7.js"), sanitizeFixture);
  return dir;
}

function runPatch(dist, ...extraArgs) {
  const result = spawnSync(process.execPath, [patchScript, "--dist", dist, ...extraArgs], {
    encoding: "utf8"
  });
  assert.equal(result.status, 0, result.stderr || result.stdout);
  return JSON.parse(result.stdout);
}

describe("patch-openclaw-billing-message", () => {
  it("patches OpenClaw dist files and is idempotent", () => {
    const dist = makeDistFixture();
    try {
      const first = runPatch(dist);
      assert.equal(first.changed, true);
      assert.equal(first.backups.length, 2);

      const reply = readFileSync(path.join(dist, "reply-turn-admission-BaGuBaDP.js"), "utf8");
      const sanitize = readFileSync(path.join(dist, "sanitize-user-facing-text-CY8fNjm7.js"), "utf8");

      assert.match(reply, /formatBillingErrorMessage/);
      assert.match(sanitize, /providerKey\.includes\("minimax"\)/);
      assert.match(sanitize, /console\.volcengine\.com\/ark\/region:ark\+cn-beijing\/apiKey/);
      assert.match(sanitize, /overdue\\s\+balance/);
      assert.match(sanitize, /platform\.minimaxi\.com\/console\/recharge-records/);

      const second = runPatch(dist);
      assert.equal(second.changed, false);
      assert.equal(second.backups.length, 0);
    } finally {
      rmSync(dist, { force: true, recursive: true });
    }
  });

  it("supports dry-run without writing files", () => {
    const dist = makeDistFixture();
    try {
      const result = runPatch(dist, "--dry-run");
      assert.equal(result.dryRun, true);
      assert.equal(result.changed, true);
      assert.equal(result.backups.length, 2);

      assert.equal(
        readFileSync(path.join(dist, "reply-turn-admission-BaGuBaDP.js"), "utf8"),
        replyFixture
      );
      assert.equal(
        readdirSync(dist).filter((name) => name.includes(".lhagent-bak-")).length,
        0
      );
    } finally {
      rmSync(dist, { force: true, recursive: true });
    }
  });

  it("supports soft-fail for service-start hooks", () => {
    const result = spawnSync(process.execPath, [
      patchScript,
      "--dist",
      path.join(tmpdir(), "lhagent-openclaw-missing-dist"),
      "--soft-fail"
    ], {
      encoding: "utf8"
    });

    assert.equal(result.status, 0);
    assert.match(result.stderr, /billing patch skipped/i);
  });
});
