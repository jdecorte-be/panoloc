import { spawn } from "node:child_process";
import { join } from "node:path";

// `python -m panoloc.locate serve`, started here when nothing answers
const PORT = 8765;
export const LOCATOR = process.env.PANOLOC_LOCATOR ?? `http://127.0.0.1:${PORT}`;
// the Python project at the repository root (`make install`)
const ROOT = join(process.cwd(), "..");
const PYTHON = process.env.PANOLOC_PYTHON ?? join(ROOT, ".venv", "bin", "python");

// one locator per server process, kept across dev reloads
const globalForLocator = globalThis as typeof globalThis & { _locator?: Promise<void> };

async function locatorUp(): Promise<boolean> {
  try {
    return (await fetch(`${LOCATOR}/health`, { signal: AbortSignal.timeout(500) })).ok;
  } catch {
    return false;
  }
}

/**
 * Start the locator unless one answers. It runs in this process group: Ctrl-C on
 * `next dev` stops it too, and its worker processes exit with it.
 */
export function ensureLocator(): Promise<void> {
  globalForLocator._locator ??= (async () => {
    if (await locatorUp()) return;
    if (process.env.PANOLOC_LOCATOR) throw new Error(`No locator answers at ${LOCATOR}`);
    const child = spawn(PYTHON, ["-m", "panoloc.locate", "serve", "--port", String(PORT)], {
      cwd: ROOT,
      stdio: "inherit",
      env: {
        ...process.env,
        // the names src/panoloc/bbox.py reads
        ...(process.env.MONGODB_URI && { MONGO_URI: process.env.MONGODB_URI }),
        ...(process.env.MONGODB_DB && { MONGO_DATABASE: process.env.MONGODB_DB }),
      },
    });
    child.on("exit", () => (globalForLocator._locator = undefined));
    for (let i = 0; i < 50; i++) {
      await new Promise((r) => setTimeout(r, 200));
      if (await locatorUp()) return;
    }
    throw new Error("The locator did not start: see the server logs");
  })().catch((error) => {
    globalForLocator._locator = undefined;
    throw error;
  });
  return globalForLocator._locator;
}

/** After a failed ask: look for the locator again next time. */
export function forgetLocator() {
  globalForLocator._locator = undefined;
}
