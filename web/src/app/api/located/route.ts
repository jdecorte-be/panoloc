import type { NextRequest } from "next/server";

import { cachedJson, errorJson } from "@/lib/http";
import { signsOfTiles } from "@/lib/signs";
import { MAX_TILES, parseTiles } from "@/lib/tiles";
import type { LocatedResponse } from "@/lib/types";

/** GET /api/located?tiles=i:j,i:j -> the signs of these tiles, from `make push-signs`. */
export async function GET(request: NextRequest) {
  const parsed = parseTiles(request.nextUrl.searchParams.get("tiles"));
  if (!parsed) return errorJson(`expected tiles=i:j,i:j (at most ${MAX_TILES}, of one view)`, 400);
  try {
    const body: LocatedResponse = { tiles: Object.fromEntries(await signsOfTiles(parsed.tiles)) };
    return cachedJson(body);
  } catch (error) {
    console.error("GET /api/located failed:", error);
    return errorJson("Could not query the signs: is SIGNS_URI (or MONGODB_URI) reachable?", 503);
  }
}
