import type { NextRequest } from "next/server";

import { ensureLocator, forgetLocator, LOCATOR } from "@/lib/locator";
import { manifest } from "@/lib/manifest";
import { iconKey } from "@/lib/sign-codes";
import { MAX_TILES } from "@/lib/tiles";
import type { LocatedResponse, TileSign } from "@/lib/types";

// how long the locator holds a request for the tiles it is locating
const WAIT_MS = 1200;
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

/** GET /api/located?tiles=i:j,i:j -> the signs of these tiles, and those still pending. */
export async function GET(request: NextRequest) {
  const tiles = (request.nextUrl.searchParams.get("tiles") ?? "").split(",").filter(Boolean);
  if (!tiles.length || tiles.length > MAX_TILES || !tiles.every((t) => TILE.test(t))) {
    return Response.json(
      { error: `expected tiles=i:j,i:j (at most ${MAX_TILES})` },
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
    forgetLocator(); // look for it again next time
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
