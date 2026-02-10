/**
 * Node.js bridge to the Python rules engine.
 * Calls the CLI via subprocess and returns parsed JSON.
 */

const { spawn } = require("child_process");
const path = require("path");

const ENGINE_PATH = path.join(__dirname, "unified_comics_rules_engine_studio.py");

function runEngine(args) {
  return new Promise((resolve, reject) => {
    const proc = spawn("python3", [ENGINE_PATH, ...args], {
      cwd: __dirname,
      stdio: ["pipe", "pipe", "pipe"],
    });

    let stdout = "";
    let stderr = "";

    proc.stdout.on("data", (chunk) => (stdout += chunk));
    proc.stderr.on("data", (chunk) => (stderr += chunk));

    proc.on("close", (code) => {
      try {
        const result = JSON.parse(stdout);
        resolve(result);
      } catch {
        reject(new Error(`Engine failed (code ${code}): ${stderr || stdout}`));
      }
    });

    proc.on("error", (err) => reject(err));
  });
}

function runEngineWithStdin(args, inputJson) {
  return new Promise((resolve, reject) => {
    const proc = spawn("python3", [ENGINE_PATH, ...args], {
      cwd: __dirname,
      stdio: ["pipe", "pipe", "pipe"],
    });

    let stdout = "";
    let stderr = "";

    proc.stdout.on("data", (chunk) => (stdout += chunk));
    proc.stderr.on("data", (chunk) => (stderr += chunk));

    proc.on("close", (code) => {
      try {
        const result = JSON.parse(stdout);
        resolve(result);
      } catch {
        reject(new Error(`Engine failed (code ${code}): ${stderr || stdout}`));
      }
    });

    proc.on("error", (err) => reject(err));

    proc.stdin.write(JSON.stringify(inputJson));
    proc.stdin.end();
  });
}

/**
 * Studio Mode: generate N comic specs from a seed.
 * Returns { mode, seed, gate, generated_specs[] }
 */
async function generateSpecs({
  seed = {},
  n = 3,
  applyFixes = "suggest",
  gate = "P1",
  includeResults = true,
  maxAttempts = 6,
} = {}) {
  const args = [
    "--generate",
    "--n", String(n),
    "--apply-fixes", applyFixes,
    "--gate", gate,
    "--max-attempts", String(maxAttempts),
    "--seed", JSON.stringify(seed),
  ];
  if (includeResults) args.push("--include-results");
  return runEngine(args);
}

/**
 * Critic Mode: evaluate a spec JSON.
 * Returns { mode, summary, results[], gate, suggestions, fix_registry }
 */
async function evaluateSpec({
  spec,
  applyFixes = "suggest",
  gate = "P1",
  fullReport = false,
} = {}) {
  const args = [
    "--in", "-",
    "--apply-fixes", applyFixes,
    "--gate", gate,
  ];
  if (fullReport) args.push("--full-report");
  return runEngineWithStdin(args, spec);
}

module.exports = { generateSpecs, evaluateSpec };
