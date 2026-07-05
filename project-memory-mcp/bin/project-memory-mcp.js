#!/usr/bin/env node
"use strict";

const { basename, resolve } = require("node:path");
const { spawnSync, spawn } = require("node:child_process");

const packageRoot = resolve(__dirname, "..");
const args = process.argv.slice(2);
const invokedAs = basename(process.argv[1] || "");
const isCli = invokedAs === "project-memory";

function findPython() {
  const candidates = process.platform === "win32"
    ? [["py", ["-3"]], ["python", []], ["python3", []]]
    : [["python3", []], ["python", []]];

  for (const [cmd, prefixArgs] of candidates) {
    const probe = spawnSync(cmd, [...prefixArgs, "-c", "import sys; print(sys.executable)"], {
      encoding: "utf8",
      stdio: ["ignore", "pipe", "pipe"],
    });
    if (probe.status === 0) {
      return { cmd, prefixArgs };
    }
  }
  return null;
}

function runPython(python, pyArgs, options = {}) {
  return spawnSync(python.cmd, [...python.prefixArgs, ...pyArgs], {
    cwd: packageRoot,
    encoding: "utf8",
    stdio: options.stdio || ["ignore", "pipe", "pipe"],
    env: process.env,
  });
}

function ensureInstalled(python) {
  const importProbe = runPython(python, ["-c", "import project_memory_mcp"]);
  if (importProbe.status === 0) {
    return true;
  }

  const install = runPython(
    python,
    ["-m", "pip", "install", "--quiet", packageRoot],
    { stdio: ["ignore", "pipe", "pipe"] },
  );

  if (install.stdout) {
    process.stderr.write(install.stdout);
  }
  if (install.stderr) {
    process.stderr.write(install.stderr);
  }
  return install.status === 0;
}

const python = findPython();
if (!python) {
  process.stderr.write("project-memory-mcp requires Python 3.10+ on PATH.\n");
  process.exit(1);
}

if (!ensureInstalled(python)) {
  process.stderr.write("Failed to install the Python project-memory-mcp package.\n");
  process.exit(1);
}

const code = isCli
  ? "from project_memory_mcp.cli import app; app()"
  : "from project_memory_mcp.server import main; main()";

const child = spawn(python.cmd, [...python.prefixArgs, "-c", code, ...args], {
  cwd: process.cwd(),
  stdio: "inherit",
  env: process.env,
});

child.on("exit", (codeValue, signal) => {
  if (signal) {
    process.kill(process.pid, signal);
    return;
  }
  process.exit(codeValue ?? 0);
});
