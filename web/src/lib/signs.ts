import { signs } from "@/lib/mongodb";
import { TILE_DEG } from "@/lib/tiles";

// the counts held in memory are read again after that: a `make push-signs` run
// replaces the whole collection at once
const COUNTS_TTL_MS = 10 * 60_000;

/** [i, j] of the tile a position is in, as locate.tiles_of cuts them. */
export function tileOf([lon, lat]: [number, number]): [number, number] {
  return [Math.floor(lon / TILE_DEG), Math.floor(lat / TILE_DEG)];
}

/** "i:j" -> the [type, lon, lat] of its signs, for each of these tiles (all of them, even empty). */
export async function signsOfTiles(
  tiles: [number, number][],
): Promise<Map<string, [string, number, number][]>> {
  const found = new Map(tiles.map(([i, j]) => [`${i}:${j}`, [] as [string, number, number][]]));
  const is = tiles.map(([i]) => i);
  const js = tiles.map(([, j]) => j);
  // one tile around: the geodesic edges of the polygon bulge a little from the
  // parallels, the signs out of the asked tiles are dropped below
  const w = (Math.min(...is) - 1) * TILE_DEG;
  const s = (Math.min(...js) - 1) * TILE_DEG;
  const e = (Math.max(...is) + 2) * TILE_DEG;
  const n = (Math.max(...js) + 2) * TILE_DEG;
  const docs = (await signs()).find(
    {
      location: {
        $geoWithin: {
          $geometry: {
            type: "Polygon",
            coordinates: [[[w, s], [e, s], [e, n], [w, n], [w, s]]],
          },
        },
      },
    },
    { projection: { _id: 0, type: 1, "location.coordinates": 1 } },
  );
  for await (const { type, location } of docs) {
    const [lon, lat] = location.coordinates;
    found.get(tileOf([lon, lat]).join(":"))?.push([type, lon, lat]);
  }
  return found;
}

/** Tile "i:j" -> [signs, sum of their lon, sum of their lat]. */
type TileCounts = Map<string, [number, number, number]>;

const globalForCounts = globalThis as typeof globalThis & {
  _tileCounts?: { at: number; counts: Promise<TileCounts> };
};

async function loadTileCounts(): Promise<TileCounts> {
  const tile = (axis: 0 | 1) => ({
    $floor: { $divide: [{ $arrayElemAt: ["$location.coordinates", axis] }, TILE_DEG] },
  });
  const docs = (await signs()).aggregate<{
    _id: { i: number; j: number };
    n: number;
    lon: number;
    lat: number;
  }>([
    {
      $group: {
        _id: { i: tile(0), j: tile(1) },
        n: { $sum: 1 },
        lon: { $sum: { $arrayElemAt: ["$location.coordinates", 0] } },
        lat: { $sum: { $arrayElemAt: ["$location.coordinates", 1] } },
      },
    },
  ]);
  const counts: TileCounts = new Map();
  for await (const d of docs) counts.set(`${d._id.i}:${d._id.j}`, [d.n, d.lon, d.lat]);
  return counts;
}

/** The counts of signs per tile, of the whole collection: read again every COUNTS_TTL_MS. */
function tileCounts(): Promise<TileCounts> {
  const cached = globalForCounts._tileCounts;
  if (cached && Date.now() - cached.at < COUNTS_TTL_MS) return cached.counts;
  const counts = loadTileCounts();
  globalForCounts._tileCounts = { at: Date.now(), counts };
  counts.catch(() => {
    // asked again on the next request
    if (globalForCounts._tileCounts?.counts === counts) globalForCounts._tileCounts = undefined;
  });
  return counts;
}

/**
 * The signs of the bbox in squares of size x size tiles, aligned on multiples of
 * size: [lon, lat, count], at the mean position of their signs (locate.Locator.counts).
 */
export async function countsOf(
  [west, south, east, north]: [number, number, number, number],
  size: number,
): Promise<[number, number, number][]> {
  const i0 = Math.floor(Math.floor(west / TILE_DEG) / size) * size;
  const j0 = Math.floor(Math.floor(south / TILE_DEG) / size) * size;
  const i1 = Math.ceil(east / TILE_DEG);
  const j1 = Math.ceil(north / TILE_DEG);
  const squares = new Map<string, [number, number, number]>();
  for (const [name, [n, lon, lat]] of await tileCounts()) {
    const [i, j] = name.split(":").map(Number);
    if (i < i0 || i >= i1 || j < j0 || j >= j1) continue;
    const key = `${Math.floor(i / size)}:${Math.floor(j / size)}`;
    const square = squares.get(key) ?? [0, 0, 0];
    square[0] += n;
    square[1] += lon;
    square[2] += lat;
    squares.set(key, square);
  }
  const round = (v: number) => Math.round(v * 1e6) / 1e6;
  return [...squares.values()].map(([n, lon, lat]) => [round(lon / n), round(lat / n), n]);
}
