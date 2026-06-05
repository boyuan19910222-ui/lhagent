#!/usr/bin/env node
import { existsSync } from "node:fs";
import path from "node:path";

const DEFAULT_DIST =
  "/home/ubuntu/.local/share/pnpm/global/5/.pnpm/openclaw@2026.5.28/node_modules/openclaw/dist";

const DEFAULT_PROVIDER = "minimax";
const DEFAULT_MODEL = "abab6.5-chat";
const DEFAULT_ERROR = "MiniMax API error (402): insufficient balance";
const DEFAULT_OVERDUE_ERROR = "403 The request failed because your account has an overdue balance";
const EXPECTED_URL = "https://platform.minimaxi.com/console/recharge-records";
const EXPECTED_VOLCENGINE_URL = "https://console.volcengine.com/ark/region:ark+cn-beijing/apiKey";

function parseArgs(argv) {
  const args = {
    dist: process.env.OPENCLAW_DIST || DEFAULT_DIST,
    provider: DEFAULT_PROVIDER,
    model: DEFAULT_MODEL,
    error: DEFAULT_ERROR
  };

  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index];
    if (arg === "--dist") {
      args.dist = requireValue(argv, index, arg);
      index += 1;
      continue;
    }
    if (arg === "--provider") {
      args.provider = requireValue(argv, index, arg);
      index += 1;
      continue;
    }
    if (arg === "--model") {
      args.model = requireValue(argv, index, arg);
      index += 1;
      continue;
    }
    if (arg === "--error") {
      args.error = requireValue(argv, index, arg);
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

function requireValue(argv, index, arg) {
  const value = argv[index + 1];
  if (!value) throw new Error(`${arg} requires a value`);
  return value;
}

function usage() {
  return [
    "Usage: node scripts/verify-openclaw-billing-message.mjs [--dist <openclaw-dist>]",
    "",
    "Verifies that patched OpenClaw billing error formatting is active.",
    "",
    "Options:",
    "  --dist <path>       OpenClaw dist directory",
    "  --provider <name>   Provider name to test, default: minimax",
    "  --model <name>      Model name to display, default: abab6.5-chat",
    "  --error <text>      Raw provider error to classify"
  ].join("\n");
}

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  if (args.help) {
    console.log(usage());
    return;
  }

  const sanitizeFile = path.join(args.dist, "sanitize-user-facing-text-CY8fNjm7.js");
  assert(existsSync(sanitizeFile), `OpenClaw sanitize file not found: ${sanitizeFile}`);

  const mod = await import(pathToFileHref(sanitizeFile));
  const isBillingErrorMessage = mod.m;
  const formatBillingErrorMessage = mod.n;

  assert(
    typeof isBillingErrorMessage === "function",
    "OpenClaw export m/isBillingErrorMessage is missing"
  );
  assert(
    typeof formatBillingErrorMessage === "function",
    "OpenClaw export n/formatBillingErrorMessage is missing"
  );

  const isBilling = isBillingErrorMessage(args.error);
  const isOverdueBilling = isBillingErrorMessage(DEFAULT_OVERDUE_ERROR);
  const message = formatBillingErrorMessage(args.provider, args.model);
  const volcengineMessage = formatBillingErrorMessage("doubao", "doubao-seed-2-0-pro-260215");

  assert(isBilling === true, "sample MiniMax billing error was not classified as billing");
  assert(isOverdueBilling === true, "sample overdue-balance error was not classified as billing");
  assert(message.includes("MiniMax"), "formatted message does not mention MiniMax");
  assert(message.includes(args.model), "formatted message does not include the model name");
  assert(message.includes(EXPECTED_URL), `formatted message does not include ${EXPECTED_URL}`);
  assert(
    volcengineMessage.includes(EXPECTED_VOLCENGINE_URL),
    `Volcengine billing message does not include ${EXPECTED_VOLCENGINE_URL}`
  );

  console.log(
    JSON.stringify(
      {
        ok: true,
        dist: args.dist,
        provider: args.provider,
        model: args.model,
        isBilling,
        isOverdueBilling,
        containsRechargeUrl: message.includes(EXPECTED_URL),
        containsVolcengineApiUrl: volcengineMessage.includes(EXPECTED_VOLCENGINE_URL),
        message
      },
      null,
      2
    )
  );
}

function pathToFileHref(file) {
  return new URL(`file://${path.resolve(file).replace(/\\/g, "/")}`).href;
}

try {
  await main();
} catch (error) {
  console.error(error instanceof Error ? error.message : String(error));
  process.exitCode = 1;
}
