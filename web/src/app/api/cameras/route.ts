import type { NextRequest } from "next/server";

import { TRAFFIC_SIGN } from "@/lib/detections";
import { cachedJson, errorJson } from "@/lib/http";
import { pictures } from "@/lib/mongodb";
import { bboxPolygon, MAX_TILES, paddedBboxOf, parseTiles, tileOf } from "@/lib/tiles";
import type { CamerasResponse } from "@/lib/types";

/** Pictures per tile at most: a dense sequence passing several times. */
const MAX_PER_TILE = 400;

/**
 * GET /api/cameras?tiles=i:j,i:j -> the pictures with a traffic sign of these tiles,
 * by tile: the browser keeps the tiles it got, as for /api/located.
 */
export async function GET(request: NextRequest) {
  const parsed = parseTiles(request.nextUrl.searchParams.get("tiles"));
  if (!parsed) return errorJson(`expected tiles=i:j,i:j (at most ${MAX_TILES}, of one view)`, 400);
  try {
    const tiles: CamerasResponse["tiles"] = Object.fromEntries(parsed.names.map((t) => [t, []]));
    const docs = (await pictures<{ _id: string; geometry: { coordinates: [number, number] } }>()).find(
      {
        geometry: { $geoWithin: { $geometry: bboxPolygon(paddedBboxOf(parsed.tiles)) } },
        "semantics.key": TRAFFIC_SIGN,
      },
      { projection: { _id: 1, "geometry.coordinates": 1 } },
    );
    for await (const { _id, geometry } of docs) {
      const [lon, lat] = geometry.coordinates;
      const tile = tiles[tileOf([lon, lat]).join(":")];
      // [id, lon, lat]: a few bytes per camera
      if (tile && tile.length < MAX_PER_TILE) tile.push([_id, lon, lat]);
    }
    return cachedJson({ tiles } satisfies CamerasResponse);
  } catch (error) {
    console.error("GET /api/cameras failed:", error);
    return errorJson("Could not query MongoDB: is it running (make db-up)?", 503);
  }
}
