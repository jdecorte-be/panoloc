"""Push every sign the algorithm locates to another MongoDB: their type, position and rays.

    SIGNS_URI=mongodb://... python -m panoloc.push_signs

The signs are located in every tile a picture with a traffic sign sees, like the web
map's (panoloc.locate), reusing and filling its cache in the local database: a run
stopped goes on from there. They are written to a staging collection that replaces
the target at the end, so the target never shows a partial run, and a run after an
algorithm change leaves no stale sign behind. A write that fails is tried again.
"""

import argparse
import math
import os
import sys
import time
from collections.abc import Callable
from functools import partial

from pymongo import MongoClient
from pymongo.collection import Collection
from pymongo.database import Database
from pymongo.errors import BulkWriteError, PyMongoError
from tqdm import tqdm

from panoloc.bbox import Item
from panoloc.locate import CELL_M, MAX_DIST_M, Locator, locate_chunks, seen_tiles

DATABASE = "panoloc"
COLLECTION = "signs"
# the waits before trying a failed write again, ~6 min in all: then the run stops
RETRY_WAITS_S = (5, 15, 60, 300)
DUPLICATE_KEY = 11000


def retried(write: Callable[[], object], what: str) -> None:
    for wait in (*RETRY_WAITS_S, None):
        try:
            write()
            return
        except PyMongoError as e:
            if wait is None:
                raise
            # above the progress bar
            tqdm.write(f"{what} failed, again in {wait} s: {e!r}", file=sys.stderr)
            time.sleep(wait)


def insert(staging: Collection, signs: list[Item]) -> None:
    """Can be tried again: insert_many gave the signs their _id, the ones of an
    attempt that went through are duplicates."""
    try:
        staging.insert_many(signs, ordered=False)
    except BulkWriteError as e:
        if e.details.get("writeConcernErrors") or any(
            err["code"] != DUPLICATE_KEY for err in e.details["writeErrors"]
        ):
            raise


def replace(target: Database, staging: Collection, name: str) -> None:
    """Can be tried again: a rename that went through left no staging behind."""
    if staging.name in target.list_collection_names():
        staging.rename(name, dropTarget=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--uri", default=os.environ.get("SIGNS_URI"))
    parser.add_argument("--db", default=DATABASE)
    parser.add_argument("--collection", default=COLLECTION)
    parser.add_argument(
        "--workers", type=int, help="processes locating tiles (default: one per CPU)"
    )
    args = parser.parse_args()
    if not args.uri:
        parser.error("the target MongoDB: --uri or SIGNS_URI")

    target = MongoClient(args.uri)[args.db]
    staging = target[f"{args.collection}_staging"]
    retried(staging.drop, "dropping the staging")  # left by a stopped run

    tiles = seen_tiles(MAX_DIST_M)
    locator = Locator(args.workers, max_waiting=math.inf)
    pushed = located = 0
    try:
        for found in locate_chunks(locator, tiles, CELL_M, MAX_DIST_M):
            located += len(found)
            signs = [
                {
                    "type": s["sign"],
                    "location": {"type": "Point", "coordinates": s["position"]},
                    # [picture id, annotation id, camera lon, camera lat, bearing,
                    # distance], the nearest first: the web map's RayTuple
                    "rays": sorted(
                        (
                            [r["pictureId"], r["annotationId"], *r["camera"]]
                            + [r["bearing"], r["distance"]]
                            for r in s["rays"]
                        ),
                        key=lambda r: r[5],
                    ),
                }
                for tile_signs in found.values()
                for s in tile_signs
            ]
            if signs:
                retried(partial(insert, staging, signs), "pushing signs")
                pushed += len(signs)
    finally:
        locator.close()

    retried(lambda: staging.create_index({"location": "2dsphere"}), "indexing")
    # the tiles that failed are left out: a run again tries them
    retried(lambda: replace(target, staging, args.collection), "replacing the signs")
    print(
        f"{pushed} signs pushed to {args.db}.{args.collection} "
        f"({located}/{len(tiles)} tiles located, {len(locator.failed)} failed)",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
