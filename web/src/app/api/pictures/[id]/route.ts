import type { NextRequest } from "next/server";

import { detectionsOf, TRAFFIC_SIGN, type SignTag } from "@/lib/detections";
import { pictures } from "@/lib/mongodb";

/** GET /api/pictures/<id> -> the traffic signs detected in that picture, by box. */
export async function GET(_request: NextRequest, ctx: RouteContext<"/api/pictures/[id]">) {
  const { id } = await ctx.params;
  try {
    const [doc] = await (await pictures())
      .aggregate<{ tags: SignTag[] }>([
        { $match: { _id: id } },
        {
          $project: {
            tags: {
              $map: {
                input: {
                  $filter: { input: "$semantics", cond: { $eq: ["$$this.key", TRAFFIC_SIGN] } },
                },
                in: { value: "$$this.value", annotation: "$$this.on.id" },
              },
            },
          },
        },
      ])
      .toArray();
    if (!doc) return Response.json({ error: `picture ${id} not found` }, { status: 404 });
    return Response.json({ detections: await detectionsOf(id, doc.tags ?? []) });
  } catch (error) {
    console.error(`GET /api/pictures/${id} failed:`, error);
    return Response.json({ error: "Could not query MongoDB" }, { status: 503 });
  }
}
