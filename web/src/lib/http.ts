// Responses of the API: the data only changes when `make push-signs` or
// `make populate` runs, so browsers and CDNs may keep them a while.

/** Data of the map: fresh for 5 minutes, then served stale while it is fetched again. */
export const MAP_DATA = "public, max-age=300, s-maxage=600, stale-while-revalidate=86400";
/** The detections of one picture: they never change between two `make populate`. */
export const PICTURE_DATA = "public, max-age=3600, s-maxage=86400, stale-while-revalidate=604800";

export function cachedJson(body: unknown, cacheControl: string = MAP_DATA): Response {
  return Response.json(body, { headers: { "Cache-Control": cacheControl } });
}

export function errorJson(message: string, status: number): Response {
  return Response.json({ error: message }, { status, headers: { "Cache-Control": "no-store" } });
}

/** A query time-limited in memory, shared by the requests of one server process. */
export class TtlCache<V> {
  private readonly entries = new Map<string, { at: number; value: V }>();

  constructor(
    private readonly ttlMs: number,
    private readonly maxEntries: number,
  ) {}

  get(key: string): V | undefined {
    const entry = this.entries.get(key);
    if (!entry) return undefined;
    if (Date.now() - entry.at > this.ttlMs) {
      this.entries.delete(key);
      return undefined;
    }
    return entry.value;
  }

  set(key: string, value: V): void {
    this.entries.delete(key); // re-inserted last: the Map's order is the age
    this.entries.set(key, { at: Date.now(), value });
    // the oldest go first
    for (const oldest of this.entries.keys()) {
      if (this.entries.size <= this.maxEntries) break;
      this.entries.delete(oldest);
    }
  }
}
