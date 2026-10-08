// The tiles of src/panoloc/locate.py: keep TILE_DEG in sync.
export const TILE_DEG = 0.0025;

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
