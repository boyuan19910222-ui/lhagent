#!/usr/bin/env node
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

const DEFAULT_DIST =
  "/home/ubuntu/.local/share/pnpm/global/5/.pnpm/openclaw@2026.5.28/node_modules/openclaw/dist";
const DEFAULT_INSTALL_DIR = path.join(os.homedir(), ".openclaw", "lhagent");
const DEFAULT_UNIT = "openclaw-gateway.service";
const DEFAULT_NODE = process.execPath;

function parseArgs(argv) {
  const args = {
    dist: process.env.OPENCLAW_DIST || DEFAULT_DIST,
    installDir: process.env.LHAGENT_INSTALL_DIR || DEFAULT_INSTALL_DIR,
    unit: process.env.OPENCLAW_SYSTEMD_UNIT || DEFAULT_UNIT,
    node: process.env.OPENCLAW_NODE || DEFAULT_NODE,
    dryRun: false,
    noSystemctl: false
  };

  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index];
    if (arg === "--dist") {
      args.dist = requireValue(argv, index, arg);
      index += 1;
      continue;
    }
    if (arg === "--install-dir") {
      args.installDir = requireValue(argv, index, arg);
      index += 1;
      continue;
    }
    if (arg === "--unit") {
      args.unit = requireValue(argv, index, arg);
      index += 1;
      continue;
    }
    if (arg === "--node") {
      args.node = requireValue(argv, index, arg);
      index += 1;
      continue;
    }
    if (arg === "--dry-run") {
      args.dryRun = true;
      continue;
    }
    if (arg === "--no-systemctl") {
      args.noSystemctl = true;
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
    "Usage: node experiments/openclaw-billing-guardian/scripts/install-openclaw-billing-guardian.mjs [options]",
    "",
    "Installs the LHAgent OpenClaw billing-message guardian as a user-systemd",
    "ExecStartPre hook for openclaw-gateway.service.",
    "",
    "Options:",
    "  --dist <path>          OpenClaw dist directory",
    "  --install-dir <path>   Install directory, default: ~/.openclaw/lhagent",
    "  --unit <name>          User systemd unit, default: openclaw-gateway.service",
    "  --node <path>          Node executable for systemd hook, default: current node",
    "  --dry-run              Print planned files without writing",
    "  --no-systemctl         Skip systemctl --user daemon-reload"
  ].join("\n");
}

function repoPath(...parts) {
  return path.join(path.dirname(fileURLToPath(import.meta.url)), "..", ...parts);
}

function resolveBundledScript(name) {
  const scriptDir = path.dirname(fileURLToPath(import.meta.url));
  const sibling = path.join(scriptDir, name);
  try {
    return readFileSync(sibling, "utf8");
  } catch {}
  return readFileSync(repoPath("scripts", name), "utf8");
}

function quoteSystemdArg(value) {
  return value.replace(/\\/g, "\\\\").replace(/"/g, '\\"');
}

function buildDropIn(args, patchScriptPath) {
  const command = [
    quoteSystemdArg(args.node),
    quoteSystemdArg(patchScriptPath),
    "--dist",
    quoteSystemdArg(args.dist),
    "--soft-fail"
  ].map((part) => `"${part}"`).join(" ");

  return [
    "[Service]",
    "# Installed by LHAgent. Keeps MiniMax billing errors beginner-readable after restarts.",
    `ExecStartPre=${command}`,
    ""
  ].join("\n");
}

function writeFilePlanned(file, content, dryRun, planned) {
  planned.push(file);
  if (dryRun) return;
  mkdirSync(path.dirname(file), { recursive: true });
  writeFileSync(file, content);
}

function runSystemctl(args) {
  if (args.noSystemctl || args.dryRun) return null;
  const result = spawnSync("systemctl", ["--user", "daemon-reload"], {
    encoding: "utf8"
  });
  return {
    command: "systemctl --user daemon-reload",
    status: result.status,
    stdout: result.stdout,
    stderr: result.stderr
  };
}

function main() {
  const args = parseArgs(process.argv.slice(2));
  if (args.help) {
    console.log(usage());
    return;
  }

  const installScriptsDir = path.join(args.installDir, "scripts");
  const patchScriptPath = path.join(installScriptsDir, "patch-openclaw-billing-message.mjs");
  const verifyScriptPath = path.join(installScriptsDir, "verify-openclaw-billing-message.mjs");
  const dropInPath = path.join(
    os.homedir(),
    ".config",
    "systemd",
    "user",
    `${args.unit}.d`,
    "lhagent-billing-guardian.conf"
  );

  const planned = [];
  writeFilePlanned(
    patchScriptPath,
    resolveBundledScript("patch-openclaw-billing-message.mjs"),
    args.dryRun,
    planned
  );
  writeFilePlanned(
    verifyScriptPath,
    resolveBundledScript("verify-openclaw-billing-message.mjs"),
    args.dryRun,
    planned
  );
  writeFilePlanned(dropInPath, buildDropIn(args, patchScriptPath), args.dryRun, planned);

  const systemctl = runSystemctl(args);
  console.log(JSON.stringify({
    ok: true,
    dryRun: args.dryRun,
    dist: args.dist,
    installDir: args.installDir,
    unit: args.unit,
    node: args.node,
    planned,
    systemctl
  }, null, 2));
}

try {
  main();
} catch (error) {
  console.error(error instanceof Error ? error.message : String(error));
  process.exitCode = 1;
}
