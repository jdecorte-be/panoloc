"""Push the located signs of an area to another MongoDB: their type and position only.

    SIGNS_URI=mongodb://... python -m panoloc.push_signs [WEST,SOUTH,EAST,NORTH]

The signs are located like the web map's (panoloc.locate), reusing and filling its
cache in the local database. In the target, the signs of the area's tiles are
replaced, so a run after an algorithm change leaves no stale sign behind.
"""

import argparse
import math
import os
import sys

from pymongo import MongoClient

from panoloc.locate import CELL_M, MAX_DIST_M, TILE_DEG, Locator, tiles_of

# Strasbourg, as `make locate`
BBOX = "7.540,48.439,7.848,48.704"
DATABASE = "panoloc"
COLLECTION = "signs"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("bbox", nargs="?", default=BBOX, help="west,south,east,north")
    parser.add_argument("--uri", default=os.environ.get("SIGNS_URI"))
    parser.add_argument("--db", default=DATABASE)
    parser.add_argument("--collection", default=COLLECTION)
    args = parser.parse_args()
    if not args.uri:
        parser.error("the target MongoDB: --uri or SIGNS_URI")

    west, south, east, north = (float(v) for v in args.bbox.split(","))
    tiles = tiles_of(west, south, east, north)
    print(f"locating {len(tiles)} tiles", file=sys.stderr)
    locator = Locator(max_waiting=math.inf)
    found = locator.locate([(t, CELL_M, MAX_DIST_M) for t in tiles], wait_s=math.inf)
    locator.close()

    signs = [
        {"type": s["sign"], "location": {"type": "Point", "coordinates": s["position"]}}
        for tile_signs in found.values()
        for s in tile_signs
    ]
    target = MongoClient(args.uri)[args.db][args.collection]
    target.create_index({"location": "2dsphere"})
    # the extent of the tiles: each sign is kept by the tile it is in
    i0, j0 = min(i for i, _ in tiles), min(j for _, j in tiles)
    i1, j1 = max(i for i, _ in tiles) + 1, max(j for _, j in tiles) + 1
    # compared on the coordinates: a GeoJSON polygon's edges are great circles,
    # not the parallels the tiles stop at
    deleted = target.delete_many(
        {
            "location.coordinates.0": {"$gte": i0 * TILE_DEG, "$lt": i1 * TILE_DEG},
            "location.coordinates.1": {"$gte": j0 * TILE_DEG, "$lt": j1 * TILE_DEG},
        }
    )
    if signs:
        target.insert_many(signs)
    print(
        f"{len(signs)} signs pushed to {args.db}.{args.collection} "
        f"({deleted.deleted_count} replaced, {len(found)}/{len(tiles)} tiles located)",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
