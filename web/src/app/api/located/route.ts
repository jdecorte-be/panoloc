import { spawn } from "node:child_process";
import { join } from "node:path";

import type { NextRequest } from "next/server";

import { manifest } from "@/lib/manifest";
import { iconKey } from "@/lib/sign-codes";
import type { LocatedResponse, TileSign } from "@/lib/types";

// tiles per request: a zoom-16 view of a big screen
const MAX_TILES = 200;
// how long the locator holds a request for the tiles it is locating
const WAIT_MS = 1200;
// `python -m panoloc.locate serve`, started here when nothing answers
const PORT = 8765;
const LOCATOR = process.env.PANOLOC_LOCATOR ?? `http://127.0.0.1:${PORT}`;
// the Python project at the repository root (`make install`)
const ROOT = join(process.cwd(), "..");
const PYTHON = process.env.PANOLOC_PYTHON ?? join(ROOT, ".venv", "bin", "python");
const TILE = /^-?\d+:-?\d+$/;

interface PythonSign {
  sign: string;
  position: [number, number];
  rays: {
    pictureId: string;
    annotationId: string | null;
    camera: [number, number];
    bearing: number;
    distance: number;
  }[];
}

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
function ensureLocator(): Promise<void> {
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

/** GET /api/located?tiles=i:j,i:j -> the signs of these tiles, and those still pending. */
export async function GET(request: NextRequest) {
  const tiles = (request.nextUrl.searchParams.get("tiles") ?? "").split(",").filter(Boolean);
  if (!tiles.length || tiles.length > MAX_TILES || !tiles.every((t) => TILE.test(t))) {
    return Response.json(
      { error: `expected tiles=i:j,i:j (at most ${MAX_TILES}): zoom in` },
      { status: 400 },
    );
  }

  let located: { tiles: Record<string, PythonSign[]>; pending: string[] };
  try {
    await ensureLocator();
    const res = await fetch(`${LOCATOR}/tiles?tiles=${tiles.join(",")}&wait=${WAIT_MS}`, {
      signal: request.signal,
    });
    if (!res.ok) throw new Error(`the locator answered ${res.status}`);
    located = await res.json();
  } catch (error) {
    if (request.signal.aborted) return new Response(null, { status: 499 });
    globalForLocator._locator = undefined; // look for it again next time
    console.error("GET /api/located failed:", error);
    return Response.json(
      { error: `Could not locate the signs: ${error instanceof Error ? error.message : error}` },
      { status: 503 },
    );
  }

  const icons = await manifest();
  const body: LocatedResponse = {
    tiles: Object.fromEntries(
      Object.entries(located.tiles).map(([tile, signs]) => [
        tile,
        signs.map(({ sign, position, rays }): TileSign => {
          const icon = iconKey(sign, icons);
          return {
            sign,
            ...(icon && { icon }),
            name: (icon && icons[icon]) || sign,
            position,
            rays: rays
              .toSorted((a, b) => a.distance - b.distance)
              .map((r) => [r.pictureId, r.annotationId, ...r.camera, r.bearing, r.distance]),
          };
        }),
      ]),
    ),
    pending: located.pending,
  };
  return Response.json(body);
}
