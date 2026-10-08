"""Push every sign the algorithm locates to another MongoDB: their type and position only.

    SIGNS_URI=mongodb://... python -m panoloc.push_signs

The signs are located in every tile a picture with a traffic sign sees, like the web
map's (panoloc.locate), reusing and filling its cache in the local database: a run
stopped goes on from there. They are written to a staging collection that replaces
the target at the end, so the target never shows a partial run, and a run after an
algorithm change leaves no stale sign behind.
"""

import argparse
import math
import os
import sys

from pymongo import MongoClient

from panoloc.locate import CELL_M, MAX_DIST_M, Locator, locate_chunks, seen_tiles

DATABASE = "panoloc"
COLLECTION = "signs"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--uri", default=os.environ.get("SIGNS_URI"))
    parser.add_argument("--db", default=DATABASE)
    parser.add_argument("--collection", default=COLLECTION)
    args = parser.parse_args()
    if not args.uri:
        parser.error("the target MongoDB: --uri or SIGNS_URI")

    target = MongoClient(args.uri)[args.db]
    staging = target[f"{args.collection}_staging"]
    staging.drop()  # left by a stopped run

    print("listing the tiles of the pictures", file=sys.stderr, flush=True)
    tiles = seen_tiles(MAX_DIST_M)
    print(f"locating {len(tiles)} tiles", file=sys.stderr, flush=True)
    locator = Locator(max_waiting=math.inf)
    pushed = located = 0
    try:
        for found in locate_chunks(locator, tiles, CELL_M, MAX_DIST_M):
            located += len(found)
            signs = [
                {
                    "type": s["sign"],
                    "location": {"type": "Point", "coordinates": s["position"]},
                }
                for tile_signs in found.values()
                for s in tile_signs
            ]
            if signs:
                staging.insert_many(signs)
                pushed += len(signs)
    finally:
        locator.close()

    staging.create_index({"location": "2dsphere"})
    # the tiles that failed are left out: a run again tries them
    staging.rename(args.collection, dropTarget=True)
    print(
        f"{pushed} signs pushed to {args.db}.{args.collection} "
        f"({located}/{len(tiles)} tiles located)",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
