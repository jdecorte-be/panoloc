import { totalSigns } from "@/lib/signs";
import type { TotalResponse } from "@/lib/types";

/** GET /api/total -> the located signs of the whole world. */
export async function GET() {
  try {
    const body: TotalResponse = { total: await totalSigns() };
    return Response.json(body);
  } catch (error) {
    console.error("GET /api/total failed:", error);
    return Response.json(
      { error: "Could not count the signs: is SIGNS_URI (or MONGODB_URI) reachable?" },
      { status: 503 },
    );
  }
}
