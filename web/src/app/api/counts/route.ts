import type { NextRequest } from "next/server";

import { parseBbox } from "@/lib/bbox";
import { cachedJson, errorJson } from "@/lib/http";
import { countsOf } from "@/lib/signs";
import { MAX_COUNT_SIZE } from "@/lib/tiles";
import type { CountsResponse } from "@/lib/types";

// any bbox: the counts per tile are held in memory
const MAX_SPAN_DEG = 360;
const MAX_SIZE = MAX_COUNT_SIZE;

/** GET /api/counts?bbox=west,south,east,north&size=n -> the located signs, by squares of n x n tiles. */
export async function GET(request: NextRequest) {
  const params = request.nextUrl.searchParams;
  const parsed = parseBbox(params.get("bbox"), MAX_SPAN_DEG);
  if ("error" in parsed) return errorJson(parsed.error, 400);
  const size = Number(params.get("size"));
  if (!Number.isInteger(size) || size < 1 || size > MAX_SIZE) {
    return errorJson(`expected size=1..${MAX_SIZE}`, 400);
  }

  try {
    const body: CountsResponse = { counts: await countsOf(parsed.bbox, size) };
    return cachedJson(body);
  } catch (error) {
    console.error("GET /api/counts failed:", error);
    return errorJson("Could not count the signs: is SIGNS_URI (or MONGODB_URI) reachable?", 503);
  }
}
