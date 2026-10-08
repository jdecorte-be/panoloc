import type { NextRequest } from "next/server";

import { manifest } from "@/lib/manifest";
import { iconKey } from "@/lib/sign-codes";
import { signsOfTiles } from "@/lib/signs";
import { MAX_TILES } from "@/lib/tiles";
import type { LocatedResponse } from "@/lib/types";

const TILE = /^-?\d+:-?\d+$/;

/** GET /api/located?tiles=i:j,i:j -> the signs of these tiles, from `make push-signs`. */
export async function GET(request: NextRequest) {
  const names = (request.nextUrl.searchParams.get("tiles") ?? "").split(",").filter(Boolean);
  const tiles = names.map((t) => t.split(":").map(Number) as [number, number]);
  const span = (axis: 0 | 1) =>
    Math.max(...tiles.map((t) => t[axis])) - Math.min(...tiles.map((t) => t[axis]));
  if (
    !names.length ||
    names.length > MAX_TILES ||
    !names.every((t) => TILE.test(t)) ||
    // the tiles of one view: no scan of the whole collection
    span(0) >= MAX_TILES ||
    span(1) >= MAX_TILES
  ) {
    return Response.json(
      { error: `expected tiles=i:j,i:j (at most ${MAX_TILES}, of one view)` },
      { status: 400 },
    );
  }

  try {
    const [found, icons] = await Promise.all([signsOfTiles(tiles), manifest()]);
    const body: LocatedResponse = {
      tiles: Object.fromEntries(
        [...found].map(([tile, signs]) => [
          tile,
          signs.map(([sign, lon, lat]) => {
            const icon = iconKey(sign, icons);
            // push-signs keeps no rays: the pictures that see a sign are not known
            return { sign, ...(icon && { icon }), name: (icon && icons[icon]) || sign, position: [lon, lat], rays: [] };
          }),
        ]),
      ),
    };
    return Response.json(body);
  } catch (error) {
    console.error("GET /api/located failed:", error);
    return Response.json(
      { error: "Could not query the signs: is SIGNS_URI (or MONGODB_URI) reachable?" },
      { status: 503 },
    );
  }
}
