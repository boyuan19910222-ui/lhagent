#!/usr/bin/env node
import { spawnSync } from "node:child_process";
import { existsSync, readFileSync, writeFileSync } from "node:fs";
import path from "node:path";

const DEFAULT_DIST =
  "/home/ubuntu/.local/share/pnpm/global/5/.pnpm/openclaw@2026.5.28/node_modules/openclaw/dist";

function parseArgs(argv) {
  const args = {
    dist: process.env.OPENCLAW_DIST || DEFAULT_DIST,
    dryRun: false,
    softFail: false
  };

  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index];
    if (arg === "--dry-run") {
      args.dryRun = true;
      continue;
    }
    if (arg === "--soft-fail") {
      args.softFail = true;
      continue;
    }
    if (arg === "--dist") {
      const value = argv[index + 1];
      if (!value) throw new Error("--dist requires a path");
      args.dist = value;
      index += 1;
      continue;
    }
    if (arg === "--help" || arg === "-h") {
      args.help = true;
      continue;
    }
    throw new Error(`Unknown argument: ${arg}`);
  }

  return args;
}

function usage() {
  return [
    "Usage: node experiments/openclaw-billing-guardian/scripts/patch-openclaw-billing-message.mjs [--dist <openclaw-dist>] [--dry-run] [--soft-fail]",
    "",
    "Patches OpenClaw 2026.5.28 compiled gateway files so MiniMax billing errors",
    "are shown as beginner-readable Chinese guidance with a recharge link.",
    "",
    "Default dist path:",
    `  ${DEFAULT_DIST}`,
    "",
    "After a real patch, restart the gateway:",
    "  systemctl --user restart openclaw-gateway.service",
    "",
    "Use --soft-fail only from service-start hooks so OpenClaw can still start",
    "if a future version changes compiled file names."
  ].join("\n");
}

function backupPath(file) {
  return `${file}.lhagent-bak-${Math.floor(Date.now() / 1000)}`;
}

function replaceOnce(text, from, to, label) {
  if (text.includes(to)) return { text, changed: false };
  const count = text.split(from).length - 1;
  if (count !== 1) {
    throw new Error(`${label}: expected one patch target, found ${count}`);
  }
  return { text: text.replace(from, to), changed: true };
}

function patchReplyFile(text) {
  const oldImport =
    'import { _ as isRateLimitErrorMessage, d as sanitizeUserFacingText, h as isOverloadedErrorMessage, i as formatRateLimitOrOverloadedErrorCopy, m as isBillingErrorMessage, t as BILLING_ERROR_USER_MESSAGE } from "./sanitize-user-facing-text-CY8fNjm7.js";';
  const newImport =
    'import { _ as isRateLimitErrorMessage, d as sanitizeUserFacingText, h as isOverloadedErrorMessage, i as formatRateLimitOrOverloadedErrorCopy, m as isBillingErrorMessage, n as formatBillingErrorMessage, t as BILLING_ERROR_USER_MESSAGE } from "./sanitize-user-facing-text-CY8fNjm7.js";';

  const oldBillingText = "text: isBilling ? BILLING_ERROR_USER_MESSAGE :";
  const newBillingText =
    "text: isBilling ? formatBillingErrorMessage(attemptedRuntimeProvider ?? params.followupRun.run.provider, attemptedRuntimeModel ?? params.followupRun.run.model) :";

  const importResult = replaceOnce(text, oldImport, newImport, "reply import");
  const billingResult = replaceOnce(
    importResult.text,
    oldBillingText,
    newBillingText,
    "reply billing message"
  );

  return {
    text: billingResult.text,
    changed: importResult.changed || billingResult.changed
  };
}

function patchSanitizeFile(text) {
  const billingPatternPatch = patchBillingPatterns(text);
  text = billingPatternPatch.text;

  const hasProviderSpecificBillingFormatter =
    text.includes("console.volcengine.com/ark/region:ark+cn-beijing/apiKey");
  if (hasProviderSpecificBillingFormatter) {
    return { text, changed: billingPatternPatch.changed };
  }

  const start = text.indexOf("function formatBillingErrorMessage(provider, model) {");
  const end = text.indexOf(
    "const BILLING_ERROR_USER_MESSAGE = formatBillingErrorMessage();",
    start
  );

  if (start < 0 || end < 0) {
    throw new Error("sanitize billing formatter range not found");
  }

  const replacement = [
    "function formatBillingErrorMessage(provider, model) {",
    "\tconst providerName = provider?.trim();",
    "\tconst modelName = model?.trim();",
    "\tconst providerLabel = providerName && modelName ? `${providerName} (${modelName})` : providerName || void 0;",
    "\tconst providerKey = normalizeLowercaseStringOrEmpty(providerName);",
    "\tif (providerKey.includes(\"minimax\")) return \"\\u26a0\\ufe0f MiniMax \\u6a21\\u578b\\u670d\\u52a1\\u4f59\\u989d\\u4e0d\\u8db3\\u6216\\u8d26\\u6237\\u6b20\\u8d39\\uff0cOpenClaw \\u6682\\u65f6\\u65e0\\u6cd5\\u7ee7\\u7eed\\u56de\\u590d\\u3002\\n\\n\\u5f53\\u524d\\u6a21\\u578b\\uff1a\" + (modelName || \"MiniMax\") + \"\\n\\u5904\\u7406\\u65b9\\u5f0f\\uff1a\\u8bf7\\u6253\\u5f00 MiniMax \\u5e73\\u53f0\\u5145\\u503c\\u6216\\u7eed\\u8d39\\uff0c\\u7136\\u540e\\u56de\\u5230\\u5f53\\u524d\\u5bf9\\u8bdd\\u91cd\\u8bd5\\u3002\\n\\u5145\\u503c\\u5165\\u53e3\\uff1ahttps://platform.minimaxi.com/console/recharge-records\\n\\n\\u5982\\u679c\\u5df2\\u7ecf\\u5145\\u503c\\u4ecd\\u7136\\u5931\\u8d25\\uff0c\\u8bf7\\u68c0\\u67e5 OpenClaw \\u91cc\\u914d\\u7f6e\\u7684 MiniMax API Key \\u662f\\u5426\\u5c5e\\u4e8e\\u521a\\u5145\\u503c\\u7684\\u8d26\\u53f7\\u3002\";",
    "\tif (providerKey.includes(\"doubao\") || providerKey.includes(\"volcengine\") || providerKey.includes(\"ark\") || providerKey.includes(\"tencenthytokenplan\") || providerKey.startsWith(\"hy\")) return \"\\u26a0\\ufe0f \\u706b\\u5c71\\u5f15\\u64ce\\u65b9\\u821f/\\u8c46\\u5305\\u6a21\\u578b\\u670d\\u52a1\\u8fd4\\u56de\\u4e86\\u8d26\\u5355\\u9519\\u8bef\\uff0c\\u8d26\\u53f7\\u53ef\\u80fd\\u6b20\\u8d39\\u3001\\u4f59\\u989d\\u4e0d\\u8db3\\uff0c\\u6216\\u5f53\\u524d API Key \\u4e0d\\u53ef\\u7528\\u3002\\n\\n\\u5f53\\u524d\\u6a21\\u578b\\uff1a\" + (modelName || \"\\u706b\\u5c71\\u5f15\\u64ce\\u65b9\\u821f\") + \"\\n\\u5904\\u7406\\u65b9\\u5f0f\\uff1a\\u8bf7\\u6253\\u5f00\\u706b\\u5c71\\u5f15\\u64ce\\u65b9\\u821f API \\u7ba1\\u7406\\u9875\\uff0c\\u68c0\\u67e5\\u8d26\\u53f7\\u72b6\\u6001\\u3001API Key \\u548c\\u8ba1\\u8d39\\u914d\\u7f6e\\uff0c\\u7136\\u540e\\u56de\\u5230\\u5f53\\u524d\\u5bf9\\u8bdd\\u91cd\\u8bd5\\u3002\\nAPI \\u7ba1\\u7406\\u5165\\u53e3\\uff1ahttps://console.volcengine.com/ark/region:ark+cn-beijing/apiKey\\n\\n\\u5982\\u679c\\u786e\\u8ba4\\u8d26\\u53f7\\u5df2\\u6062\\u590d\\uff0c\\u8bf7\\u68c0\\u67e5 OpenClaw \\u91cc\\u914d\\u7f6e\\u7684 API Key \\u662f\\u5426\\u6765\\u81ea\\u8fd9\\u4e2a\\u53ef\\u7528\\u8d26\\u53f7\\u3002\";",
    "\tif (providerLabel) return `\\u26a0\\ufe0f ${providerLabel} \\u6a21\\u578b\\u670d\\u52a1\\u8fd4\\u56de\\u4e86\\u8d26\\u5355\\u9519\\u8bef\\uff0cAPI Key \\u53ef\\u80fd\\u4f59\\u989d\\u4e0d\\u8db3\\u3001\\u8d26\\u53f7\\u6b20\\u8d39\\u6216\\u989d\\u5ea6\\u7528\\u5c3d\\u3002\\n\\n\\u5904\\u7406\\u65b9\\u5f0f\\uff1a\\u8bf7\\u8fdb\\u5165 ${providerName} \\u7684\\u63a7\\u5236\\u53f0\\u5145\\u503c\\u6216\\u7eed\\u8d39\\uff0c\\u7136\\u540e\\u56de\\u5230\\u5f53\\u524d\\u5bf9\\u8bdd\\u91cd\\u8bd5\\uff1b\\u4e5f\\u53ef\\u4ee5\\u5728 OpenClaw \\u4e2d\\u5207\\u6362\\u5230\\u53ef\\u7528\\u7684 API Key\\u3002`;",
    "\treturn \"\\u26a0\\ufe0f \\u6a21\\u578b\\u670d\\u52a1\\u5546\\u8fd4\\u56de\\u4e86\\u8d26\\u5355\\u9519\\u8bef\\uff0cAPI Key \\u53ef\\u80fd\\u4f59\\u989d\\u4e0d\\u8db3\\u3001\\u8d26\\u53f7\\u6b20\\u8d39\\u6216\\u989d\\u5ea6\\u7528\\u5c3d\\u3002\\n\\n\\u5904\\u7406\\u65b9\\u5f0f\\uff1a\\u8bf7\\u8fdb\\u5165\\u5bf9\\u5e94\\u6a21\\u578b\\u670d\\u52a1\\u5546\\u7684\\u63a7\\u5236\\u53f0\\u5145\\u503c\\u6216\\u7eed\\u8d39\\uff0c\\u7136\\u540e\\u56de\\u5230\\u5f53\\u524d\\u5bf9\\u8bdd\\u91cd\\u8bd5\\uff1b\\u4e5f\\u53ef\\u4ee5\\u5728 OpenClaw \\u4e2d\\u5207\\u6362\\u5230\\u53ef\\u7528\\u7684 API Key\\u3002\";",
    "}"
  ].join("\n") + "\n";

  return {
    text: `${text.slice(0, start)}${replacement}${text.slice(end)}`,
    changed: true
  };
}

function patchBillingPatterns(text) {
  if (text.includes("overdue\\s+balance") || text.includes("overdue balance")) {
    return { text, changed: false };
  }
  const target = '"insufficient usd or diem balance",';
  if (!text.includes(target)) return { text, changed: false };
  return {
    text: text.replace(target, `${target}\n\t\t/overdue\\s+balance/i,\n\t\t/account\\s+has\\s+an\\s+overdue\\s+balance/i,`),
    changed: true
  };
}

function writePatchedFile(file, nextText, dryRun) {
  const current = readFileSync(file, "utf8");
  if (current === nextText) return null;

  const backup = backupPath(file);
  if (!dryRun) {
    writeFileSync(backup, current);
    writeFileSync(file, nextText);
  }
  return backup;
}

function nodeCheck(file) {
  const result = spawnSync(process.execPath, ["--check", file], {
    encoding: "utf8"
  });
  if (result.status !== 0) {
    throw new Error(`node --check failed for ${file}\n${result.stderr || result.stdout}`);
  }
}

function main() {
  const args = parseArgs(process.argv.slice(2));
  if (args.help) {
    console.log(usage());
    return;
  }

  const replyFile = path.join(args.dist, "reply-turn-admission-BaGuBaDP.js");
  const sanitizeFile = path.join(args.dist, "sanitize-user-facing-text-CY8fNjm7.js");

  for (const file of [replyFile, sanitizeFile]) {
    if (!existsSync(file)) throw new Error(`OpenClaw file not found: ${file}`);
  }

  const replyPatch = patchReplyFile(readFileSync(replyFile, "utf8"));
  const sanitizePatch = patchSanitizeFile(readFileSync(sanitizeFile, "utf8"));

  const backups = [
    writePatchedFile(replyFile, replyPatch.text, args.dryRun),
    writePatchedFile(sanitizeFile, sanitizePatch.text, args.dryRun)
  ].filter(Boolean);

  if (!args.dryRun) {
    nodeCheck(replyFile);
    nodeCheck(sanitizeFile);
  }

  console.log(
    JSON.stringify(
      {
        dryRun: args.dryRun,
        dist: args.dist,
        changed: replyPatch.changed || sanitizePatch.changed,
        backups
      },
      null,
      2
    )
  );
}

try {
  main();
} catch (error) {
  const softFail = process.argv.slice(2).includes("--soft-fail");
  const message = error instanceof Error ? error.message : String(error);
  if (softFail) {
    console.error(`[lhagent] OpenClaw billing patch skipped: ${message}`);
    process.exitCode = 0;
  } else {
    console.error(message);
    process.exitCode = 1;
  }
}
