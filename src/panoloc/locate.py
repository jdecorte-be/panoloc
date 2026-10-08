"""Located signs for the web map: a small HTTP server in front of find_signs.

    python -m panoloc.locate serve [--port 8765]
    python -m panoloc.locate WEST,SOUTH,EAST,NORTH   # fill the cache of an area

find_signs slows down much faster than the area grows (26 s for 1 x 0.6 km of
Strasbourg): the map asks for fixed tiles, located in a pool of processes and kept
in the `located_tiles` collection. A tile is located again when the algorithm's
source files change (see fingerprint).

The server answers at once with the cached tiles, and keeps locating the others,
the last asked first: the map asks again for those still pending.
"""

import argparse
import hashlib
import json
import math
import multiprocessing
import os
import signal
import sys
import threading
import time
from collections.abc import Iterable
from concurrent.futures import Future, ProcessPoolExecutor
from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from panoloc.bbox import M_PER_DEG_LAT, Item, pictures, to_item
from panoloc.deduplication import find_signs
from panoloc.frontend.map_shapes import local_to_lonlat

TRAFFIC_SIGN = "osm|traffic_sign"
# the Streamlit app's defaults
CELL_M = 0.5
MAX_DIST_M = 45
TILE_DEG = 0.0025  # ~280 x 185 m in Strasbourg: ~3 s for its busiest streets
CACHE = "located_tiles"
# the code find_signs runs: a change in one of them locates the tiles again
ALGORITHM = ("annotations.py", "deduplication.py", "geo.py", "triangulation.py")
PORT = 8765
# tiles waiting to be located: a long pan over the city drops the oldest ones
MAX_WAITING = 2000

Tile = tuple[int, int]
# a tile and the parameters it is located with
Key = tuple[Tile, float, float]


def fingerprint() -> str:
    """Hash of the algorithm's source files. Not cached: the server sees an edit."""
    src = Path(__file__).parent
    h = hashlib.sha1()
    for name in ALGORITHM:
        h.update((src / name).read_bytes())
    return h.hexdigest()[:12]


def area_items(
    west: float, south: float, east: float, north: float, margin_m: float
) -> list[Item]:
    """The pictures with a traffic sign in the bbox, grown by margin_m: a sign near
    the edge is also seen from the cameras just outside."""
    dlat = margin_m / M_PER_DEG_LAT
    dlon = dlat / math.cos(math.radians((south + north) / 2))
    x0, y0, x1, y1 = west - dlon, south - dlat, east + dlon, north + dlat
    ring = [[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]]
    query = {
        "geometry": {
            "$geoWithin": {"$geometry": {"type": "Polygon", "coordinates": [ring]}}
        },
        "semantics.key": TRAFFIC_SIGN,
    }
    return [to_item(doc) for doc in pictures().find(query)]


def _lonlat(lon: float, lat: float, radius_m: float, x: float, y: float):
    # ~1 cm: keeps the answers small
    return [round(v, 7) for v in local_to_lonlat(lon, lat, radius_m, x, y)]


def located_signs(
    west: float,
    south: float,
    east: float,
    north: float,
    cell_m: float = CELL_M,
    max_m: float = MAX_DIST_M,
) -> list[Item]:
    """The signs located in the bbox, with the rays that see them."""
    items = area_items(west, south, east, north, max_m)
    if not items:
        return []
    lon, lat = (west + east) / 2, (south + north) / 2
    # the grid of find_signs: a square around the center, covering the margin
    half_w = (east - west) / 2 * M_PER_DEG_LAT * math.cos(math.radians(lat))
    half_h = (north - south) / 2 * M_PER_DEG_LAT
    radius_m = max(half_w, half_h) + max_m
    signs = find_signs(items, lon, lat, radius_m, cell_m, max_m)

    found = []
    for s in signs:
        pos = _lonlat(lon, lat, radius_m, s.x, s.y)
        if not (west <= pos[0] < east and south <= pos[1] < north):
            continue  # found from the margin: the tile it is in keeps it
        found.append(
            {
                "sign": s.sign_type,
                "position": pos,
                "rays": [
                    {
                        "pictureId": r.photo_id,
                        "annotationId": r.annotation_id,
                        "camera": _lonlat(lon, lat, radius_m, r.x, r.y),
                        "bearing": round(r.bearing, 1),
                        "distance": round(math.hypot(s.x - r.x, s.y - r.y), 1),
                    }
                    for r in s.rays
                ],
            }
        )
    return found


def tiles_of(west: float, south: float, east: float, north: float) -> list[Tile]:
    return [
        (i, j)
        for i in range(math.floor(west / TILE_DEG), math.ceil(east / TILE_DEG))
        for j in range(math.floor(south / TILE_DEG), math.ceil(north / TILE_DEG))
    ]


def tile_name(tile: Tile) -> str:
    """ "i:j", how the map names a tile."""
    return f"{tile[0]}:{tile[1]}"


def parse_tile(name: str) -> Tile:
    i, j = name.split(":")
    return int(i), int(j)


def tile_id(tile: Tile, cell_m: float, max_m: float) -> str:
    # :g: 45 and 45.0 are the same tile
    return f"{tile_name(tile)}:{cell_m:g}:{max_m:g}"


def locate_tile(key: Key) -> tuple[str, list[Item]]:
    """Run in a worker: the fingerprint of the code it ran, and the tile's signs."""
    (i, j), cell_m, max_m = key
    signs = located_signs(
        i * TILE_DEG,
        j * TILE_DEG,
        (i + 1) * TILE_DEG,
        (j + 1) * TILE_DEG,
        cell_m,
        max_m,
    )
    return fingerprint(), signs


def _exit_with(parent: int) -> None:
    """Worker initializer: exit when the server is gone, even killed (-9)."""

    def watch() -> None:
        while os.getppid() == parent:
            time.sleep(1)
        os._exit(0)

    threading.Thread(target=watch, daemon=True).start()


class Locator:
    """Locates tiles in a pool of processes, the last asked first, into the cache."""

    def __init__(
        self, workers: int | None = None, max_waiting: float = MAX_WAITING
    ) -> None:
        self.workers = workers or os.cpu_count() or 1
        self.max_waiting = max_waiting
        self.cache = pictures().database[CACHE]
        self.changed = threading.Condition()  # guards the fields below
        self.waiting: list[Key] = []  # the last asked at the end
        self.running: set[Key] = set()
        self.pool: ProcessPoolExecutor | None = None
        self.pool_fingerprint: str | None = None

    def cached(self, keys: Iterable[Key]) -> dict[Key, list[Item]]:
        by_id = {tile_id(*k): k for k in keys}
        docs = self.cache.find(
            {
                "_id": {"$in": list(by_id)},
                "fingerprint": fingerprint(),
                "signs": {"$exists": True},  # not the first format of the cache
            }
        )
        return {by_id[doc["_id"]]: doc["signs"] for doc in docs}

    def _fill(self) -> None:
        """Start the waiting tiles while there are idle workers. Lock held."""
        current = fingerprint()
        if current != self.pool_fingerprint:
            # spawned, not forked: the new workers import the edited code
            if self.pool:
                self.pool.shutdown(wait=False, cancel_futures=True)
            self.pool = ProcessPoolExecutor(
                self.workers,
                mp_context=multiprocessing.get_context("spawn"),
                initializer=_exit_with,
                initargs=(os.getpid(),),
            )
            self.pool_fingerprint = current
        while self.waiting and len(self.running) < self.workers:
            key = self.waiting.pop()
            self.running.add(key)
            future = self.pool.submit(locate_tile, key)
            future.add_done_callback(partial(self._finished, key))

    def _finished(self, key: Key, future: Future) -> None:
        try:
            located_with, signs = future.result()
            self.cache.update_one(
                {"_id": tile_id(*key)},
                {"$set": {"fingerprint": located_with, "signs": signs}},
                upsert=True,
            )
        except Exception as e:  # noqa: BLE001 - one tile, the others go on
            print(f"tile {tile_id(*key)} failed: {e!r}", file=sys.stderr)
        with self.changed:
            self.running.discard(key)
            self._fill()
            self.changed.notify_all()

    def close(self) -> None:
        with self.changed:
            self.waiting.clear()
            if self.pool:
                self.pool.shutdown(wait=False, cancel_futures=True)

    def locate(self, keys: list[Key], wait_s: float) -> dict[Key, list[Item]]:
        """The tiles cached now, or within wait_s; the others keep being located."""
        found = self.cached(keys)
        missing = [k for k in keys if k not in found]
        if not missing:
            return found
        with self.changed:
            for k in missing:
                if k in self.running:
                    continue
                if k in self.waiting:
                    self.waiting.remove(k)
                self.waiting.append(k)  # on top: asked last, located first
            if len(self.waiting) > self.max_waiting:
                del self.waiting[: len(self.waiting) - int(self.max_waiting)]
            self._fill()
            deadline = time.monotonic() + wait_s
            while (left := deadline - time.monotonic()) > 0 and any(
                k in self.running or k in self.waiting for k in missing
            ):
                self.changed.wait(left)
        return found | self.cached(missing)


def serve(port: int) -> None:
    locator = Locator()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            url = urlparse(self.path)
            if url.path == "/health":
                self.send_response(204)
                self.end_headers()
                return
            if url.path != "/tiles":
                self.send_error(404)
                return
            q = parse_qs(url.query)
            try:
                tiles = [parse_tile(t) for t in q["tiles"][0].split(",") if t]
                cell_m = float(q.get("cell", [CELL_M])[0])
                max_m = float(q.get("max", [MAX_DIST_M])[0])
                wait_s = float(q.get("wait", [0])[0]) / 1000
            except KeyError, ValueError:
                self.send_error(400, "expected tiles=i:j,i:j[&cell=&max=&wait=ms]")
                return
            keys = [(t, cell_m, max_m) for t in tiles]
            found = locator.locate(keys, wait_s)
            body = json.dumps(
                {
                    "tiles": {tile_name(k[0]): found[k] for k in keys if k in found},
                    "pending": [tile_name(k[0]) for k in keys if k not in found],
                }
            ).encode()
            try:
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except BrokenPipeError, ConnectionResetError:
                pass  # the map moved on: its tiles are cached for the next ask

        def log_message(self, format, *args) -> None:
            pass  # one line per map move is noise

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.daemon_threads = True  # a request waiting on tiles never blocks the exit

    def stop(signum, frame) -> None:
        locator.close()
        os._exit(0)

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    print(f"panoloc.locate: http://127.0.0.1:{port}/tiles", file=sys.stderr)
    server.serve_forever()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("target", help='"serve", or west,south,east,north to fill')
    parser.add_argument("--port", type=int, default=PORT)
    parser.add_argument("--cell", type=float, default=CELL_M)
    parser.add_argument("--max-dist", type=float, default=MAX_DIST_M)
    args = parser.parse_args()
    if args.target == "serve":
        serve(args.port)
        return
    west, south, east, north = (float(v) for v in args.target.split(","))
    keys = [(t, args.cell, args.max_dist) for t in tiles_of(west, south, east, north)]
    found = Locator(max_waiting=math.inf).locate(keys, wait_s=math.inf)
    print(
        f"{sum(map(len, found.values()))} signs in {len(found)}/{len(keys)} tiles",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
