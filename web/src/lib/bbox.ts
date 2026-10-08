import { z } from "zod";

export type Bbox = [west: number, south: number, east: number, north: number];

/** "west,south,east,north" -> numbers, or the reason it is refused. */
export function parseBbox(
  value: string | null,
  maxSpanDeg: number,
): { bbox: Bbox } | { error: string } {
  const parsed = z
    .string()
    .transform((s) => s.split(",").map(Number))
    .pipe(
      z.tuple([
        z.number().min(-180).max(180),
        z.number().min(-90).max(90),
        z.number().min(-180).max(180),
        z.number().min(-90).max(90),
      ]),
    )
    .refine(([w, s, e, n]) => w < e && s < n, "expected west,south,east,north")
    .refine(
      ([w, s, e, n]) => e - w <= maxSpanDeg && n - s <= maxSpanDeg,
      `bbox wider than ${maxSpanDeg}°: zoom in`,
    )
    .safeParse(value ?? "");
  return parsed.success
    ? { bbox: parsed.data }
    : { error: parsed.error.issues.map((i) => i.message).join("; ") };
}
