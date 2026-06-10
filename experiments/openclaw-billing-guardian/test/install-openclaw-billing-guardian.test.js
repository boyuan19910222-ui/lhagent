import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { describe, it } from "node:test";
import { fileURLToPath } from "node:url";

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const installScript = path.join(repoRoot, "scripts", "install-openclaw-billing-guardian.mjs");

describe("install-openclaw-billing-guardian", () => {
  it("prints planned files in dry-run mode", () => {
    const installDir = mkdtempSync(path.join(tmpdir(), "lhagent-install-plan-"));
    try {
      const result = spawnSync(process.execPath, [
        installScript,
        "--dry-run",
        "--no-systemctl",
        "--install-dir",
        installDir,
        "--dist",
        "/tmp/openclaw/dist",
        "--node",
        "/usr/bin/node"
      ], {
        encoding: "utf8"
      });

      assert.equal(result.status, 0, result.stderr || result.stdout);
      const payload = JSON.parse(result.stdout);
      assert.equal(payload.ok, true);
      assert.equal(payload.dryRun, true);
      assert.equal(payload.dist, "/tmp/openclaw/dist");
      assert.equal(payload.node, "/usr/bin/node");
      assert.equal(payload.planned.length, 3);
      assert(payload.planned.some((file) => file.endsWith("patch-openclaw-billing-message.mjs")));
      assert(payload.planned.some((file) => file.endsWith("verify-openclaw-billing-message.mjs")));
      assert(payload.planned.some((file) => file.endsWith("lhagent-billing-guardian.conf")));
    } finally {
      rmSync(installDir, { force: true, recursive: true });
    }
  });
});
