import { TtlCache } from "@/lib/http";
import { manifest } from "@/lib/manifest";
import { signs } from "@/lib/mongodb";
import { iconKey } from "@/lib/sign-codes";
import { bboxPolygon, paddedBboxOf, TILE_DEG, tileOf } from "@/lib/tiles";
import type { TileSign } from "@/lib/types";

// what is held in memory is read again after that: a `make push-signs` run
// replaces the whole collection at once
const COUNTS_TTL_MS = 10 * 60_000;
// ~1 KB per tile with signs: tens of MB at most
const TILE_CACHE_SIZE = 50_000;

const globalForTiles = globalThis as typeof globalThis & {
  _signTiles?: TtlCache<TileSign[]>;
};
// kept on globalThis: dev hot reloads re-run this module
const tileCache = (globalForTiles._signTiles ??= new TtlCache(COUNTS_TTL_MS, TILE_CACHE_SIZE));

/**
 * "i:j" -> its signs, named and with their pictogram, for each of these tiles (all
 * of them, even empty). The tiles read recently come from memory, the others from
 * one MongoDB query.
 */
export async function signsOfTiles(tiles: [number, number][]): Promise<Map<string, TileSign[]>> {
  const found = new Map<string, TileSign[]>();
  const missing: [number, number][] = [];
  for (const tile of tiles) {
    const name = tile.join(":");
    const cached = tileCache.get(name);
    if (cached) found.set(name, cached);
    else missing.push(tile);
  }
  if (!missing.length) return found;

  const read = new Map(missing.map((t) => [t.join(":"), [] as TileSign[]]));
  const [collection, icons] = await Promise.all([signs(), manifest()]);
  const docs = collection.find(
    { location: { $geoWithin: { $geometry: bboxPolygon(paddedBboxOf(missing)) } } },
    { projection: { _id: 0, type: 1, "location.coordinates": 1, rays: 1 } },
  );
  for await (const { type, location, rays } of docs) {
    const position = location.coordinates;
    const tile = read.get(tileOf(position).join(":"));
    if (!tile) continue; // out of the asked tiles
    const icon = iconKey(type, icons);
    tile.push({ sign: type, ...(icon && { icon }), name: (icon && icons[icon]) || type, position, rays: rays ?? [] });
  }
  for (const [name, tileSigns] of read) {
    tileCache.set(name, tileSigns);
    found.set(name, tileSigns);
  }
  return found;
}

/** [i, j, signs, sum of their lon, sum of their lat] of each tile with signs. */
type TileCounts = { tiles: Float64Array; total: number };
const FIELDS = 5;

const globalForCounts = globalThis as typeof globalThis & {
  _tileCounts?: { at: number; counts: Promise<TileCounts> };
};

async function loadTileCounts(): Promise<TileCounts> {
  const tile = (axis: 0 | 1) => ({
    $floor: { $divide: [{ $arrayElemAt: ["$location.coordinates", axis] }, TILE_DEG] },
  });
  const docs = await (await signs())
    .aggregate<{ _id: { i: number; j: number }; n: number; lon: number; lat: number }>([
      {
        $group: {
          _id: { i: tile(0), j: tile(1) },
          n: { $sum: 1 },
          lon: { $sum: { $arrayElemAt: ["$location.coordinates", 0] } },
          lat: { $sum: { $arrayElemAt: ["$location.coordinates", 1] } },
        },
      },
    ])
    .toArray();
  // one flat typed array: no string to split, no object per tile on each request
  const tiles = new Float64Array(docs.length * FIELDS);
  let total = 0;
  docs.forEach((d, k) => {
    tiles.set([d._id.i, d._id.j, d.n, d.lon, d.lat], k * FIELDS);
    total += d.n;
  });
  return { tiles, total };
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

/** The signs of the whole collection, from the counts held in memory. */
export async function totalSigns(): Promise<number> {
  return (await tileCounts()).total;
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
  const { tiles } = await tileCounts();
  const squares = new Map<number, [number, number, number]>();
  // squares per row of the bbox: a numeric key
  const row = Math.ceil((i1 - i0) / size) + 1;
  for (let k = 0; k < tiles.length; k += FIELDS) {
    const i = tiles[k];
    const j = tiles[k + 1];
    if (i < i0 || i >= i1 || j < j0 || j >= j1) continue;
    const key = Math.floor((j - j0) / size) * row + Math.floor((i - i0) / size);
    const square = squares.get(key);
    if (square) {
      square[0] += tiles[k + 2];
      square[1] += tiles[k + 3];
      square[2] += tiles[k + 4];
    } else {
      squares.set(key, [tiles[k + 2], tiles[k + 3], tiles[k + 4]]);
    }
  }
  const round = (v: number) => Math.round(v * 1e6) / 1e6;
  return [...squares.values()].map(([n, lon, lat]) => [round(lon / n), round(lat / n), n]);
}
