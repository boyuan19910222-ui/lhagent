import { existsSync } from "node:fs";
import { join } from "node:path";
import { spawnSync } from "node:child_process";

const testArgs = [
  "-m",
  "unittest",
  "discover",
  "-s",
  "services/review-room-service/tests",
  "-v",
];

const candidates =
  process.platform === "win32"
    ? [
        { command: join(".venv", "Scripts", "python.exe"), args: [] },
        { command: "python", args: [] },
        { command: "py", args: ["-3"] },
      ]
    : [
        { command: join(".venv", "bin", "python"), args: [] },
        { command: "python3", args: [] },
        { command: "python", args: [] },
      ];

for (const candidate of candidates) {
  if (candidate.command.includes(".venv") && !existsSync(candidate.command)) {
    continue;
  }
  const result = spawnSync(candidate.command, [...candidate.args, ...testArgs], {
    stdio: "inherit",
    shell: false,
  });
  if (result.error?.code === "ENOENT") {
    continue;
  }
  if (result.error) {
    console.error(result.error.message);
    process.exit(1);
  }
  process.exit(result.status ?? 1);
}

console.error("No Python executable found for review-room tests.");
process.exit(127);
