import { connection } from "next/server";

import { cachedJson, errorJson } from "@/lib/http";
import { totalSigns } from "@/lib/signs";
import type { TotalResponse } from "@/lib/types";

/** GET /api/total -> the located signs of the whole world. */
export async function GET() {
  await connection(); // at request time: never a count frozen at build time
  try {
    return cachedJson({ total: await totalSigns() } satisfies TotalResponse);
  } catch (error) {
    console.error("GET /api/total failed:", error);
    return errorJson("Could not count the signs: is SIGNS_URI (or MONGODB_URI) reachable?", 503);
  }
}
