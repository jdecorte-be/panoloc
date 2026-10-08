import type { NextRequest } from "next/server";

import { parseBbox } from "@/lib/bbox";
import { TRAFFIC_SIGN } from "@/lib/detections";
import { pictures } from "@/lib/mongodb";
import type { CamerasResponse } from "@/lib/types";

// widest bbox side, in degrees: the same as /api/located
const MAX_SPAN_DEG = 0.03;
const MAX_CAMERAS = 10_000;

/** GET /api/cameras?bbox=west,south,east,north -> the pictures with a traffic sign. */
export async function GET(request: NextRequest) {
  const parsed = parseBbox(request.nextUrl.searchParams.get("bbox"), MAX_SPAN_DEG);
  if ("error" in parsed) return Response.json(parsed, { status: 400 });
  const [w, s, e, n] = parsed.bbox;
  try {
    const docs = await (await pictures<{ _id: string; geometry: { coordinates: number[] } }>())
      .find(
        {
          geometry: {
            $geoWithin: {
              $geometry: {
                type: "Polygon",
                coordinates: [[[w, s], [e, s], [e, n], [w, n], [w, s]]],
              },
            },
          },
          "semantics.key": TRAFFIC_SIGN,
        },
        { projection: { _id: 1, "geometry.coordinates": 1 } },
      )
      .limit(MAX_CAMERAS + 1)
      .toArray();
    const body: CamerasResponse = {
      // [id, lon, lat]: a few bytes per camera
      cameras: docs
        .slice(0, MAX_CAMERAS)
        .map((d) => [d._id, d.geometry.coordinates[0], d.geometry.coordinates[1]]),
      truncated: docs.length > MAX_CAMERAS,
    };
    return Response.json(body);
  } catch (error) {
    console.error("GET /api/cameras failed:", error);
    return Response.json(
      { error: "Could not query MongoDB: is it running (make db-up)?" },
      { status: 503 },
    );
  }
}
