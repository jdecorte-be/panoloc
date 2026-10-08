import type { NextRequest } from "next/server";

import { parseBbox } from "@/lib/bbox";
import { countsOf } from "@/lib/signs";
import type { CountsResponse } from "@/lib/types";

// any bbox: the counts per tile are held in memory
const MAX_SPAN_DEG = 360;
// tiles per side of a square: 2^12 tiles is about 10° wide
const MAX_SIZE = 4096;

/** GET /api/counts?bbox=west,south,east,north&size=n -> the located signs, by squares of n x n tiles. */
export async function GET(request: NextRequest) {
  const params = request.nextUrl.searchParams;
  const parsed = parseBbox(params.get("bbox"), MAX_SPAN_DEG);
  if ("error" in parsed) return Response.json(parsed, { status: 400 });
  const size = Number(params.get("size"));
  if (!Number.isInteger(size) || size < 1 || size > MAX_SIZE) {
    return Response.json({ error: `expected size=1..${MAX_SIZE}` }, { status: 400 });
  }

  try {
    const body: CountsResponse = { counts: await countsOf(parsed.bbox, size) };
    return Response.json(body);
  } catch (error) {
    console.error("GET /api/counts failed:", error);
    return Response.json(
      { error: "Could not count the signs: is SIGNS_URI (or MONGODB_URI) reachable?" },
      { status: 503 },
    );
  }
}
