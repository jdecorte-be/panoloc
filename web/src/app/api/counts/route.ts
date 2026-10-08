import type { NextRequest } from "next/server";

import { parseBbox } from "@/lib/bbox";
import { ensureLocator, forgetLocator, LOCATOR } from "@/lib/locator";
import type { CountsResponse } from "@/lib/types";

// any bbox: the locator answers from the counts it holds in memory
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
    await ensureLocator();
    const res = await fetch(`${LOCATOR}/counts?bbox=${parsed.bbox.join(",")}&size=${size}`, {
      signal: request.signal,
    });
    if (!res.ok) throw new Error(`the locator answered ${res.status}`);
    return Response.json((await res.json()) as CountsResponse);
  } catch (error) {
    if (request.signal.aborted) return new Response(null, { status: 499 });
    forgetLocator();
    console.error("GET /api/counts failed:", error);
    return Response.json(
      { error: `Could not count the signs: ${error instanceof Error ? error.message : error}` },
      { status: 503 },
    );
  }
}
