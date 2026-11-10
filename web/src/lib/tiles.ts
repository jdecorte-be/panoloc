// The tiles of src/panoloc/locate.py: keep TILE_DEG in sync.
export const TILE_DEG = 0.0025;
// tiles per /api/located or /api/cameras request: a zoom-16 view of a big screen
export const MAX_TILES = 200;
// tiles per side of a square of /api/counts at most: 2^12 tiles is about 10° wide
export const MAX_COUNT_SIZE = 4096;

/** "i:j" names of the tiles covering a bbox, as tiles_of + tile_name. */
export function tilesOf(west: number, south: number, east: number, north: number): string[] {
  const names: string[] = [];
  for (let i = Math.floor(west / TILE_DEG); i < Math.ceil(east / TILE_DEG); i++) {
    for (let j = Math.floor(south / TILE_DEG); j < Math.ceil(north / TILE_DEG); j++) {
      names.push(`${i}:${j}`);
    }
  }
  return names;
}

/** [i, j] of the tile a position is in, as locate.tiles_of cuts them. */
export function tileOf([lon, lat]: [number, number]): [number, number] {
  return [Math.floor(lon / TILE_DEG), Math.floor(lat / TILE_DEG)];
}

/** The bbox [w, s, e, n] of a list of tiles, one tile wider on each side. */
export function paddedBboxOf(tiles: [number, number][]): [number, number, number, number] {
  let [i0, j0, i1, j1] = [Infinity, Infinity, -Infinity, -Infinity];
  for (const [i, j] of tiles) {
    i0 = Math.min(i0, i);
    j0 = Math.min(j0, j);
    i1 = Math.max(i1, i);
    j1 = Math.max(j1, j);
  }
  // one tile around: the geodesic edges of a polygon bulge a little from the
  // parallels, what falls out of the asked tiles is dropped by the caller
  return [(i0 - 1) * TILE_DEG, (j0 - 1) * TILE_DEG, (i1 + 2) * TILE_DEG, (j1 + 2) * TILE_DEG];
}

/** GeoJSON polygon of a bbox, for $geoWithin. */
export function bboxPolygon([w, s, e, n]: [number, number, number, number]) {
  return { type: "Polygon" as const, coordinates: [[[w, s], [e, s], [e, n], [w, n], [w, s]]] };
}

const TILE = /^-?\d+:-?\d+$/;

/**
 * "i:j,i:j" -> the tiles, sorted (a stable cache key), or null when they are not
 * the tiles of one view: no scan of the whole collection.
 */
export function parseTiles(value: string | null): { names: string[]; tiles: [number, number][] } | null {
  const names = [...new Set((value ?? "").split(",").filter(Boolean))].sort();
  if (!names.length || names.length > MAX_TILES || !names.every((t) => TILE.test(t))) return null;
  const tiles = names.map((t) => t.split(":").map(Number) as [number, number]);
  const span = (axis: 0 | 1) =>
    Math.max(...tiles.map((t) => t[axis])) - Math.min(...tiles.map((t) => t[axis]));
  if (span(0) >= MAX_TILES || span(1) >= MAX_TILES) return null;
  return { names, tiles };
}
