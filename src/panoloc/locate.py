"""Located signs for the web map: a small HTTP server in front of find_signs.

    python -m panoloc.locate serve [--port 8765]
    python -m panoloc.locate [WEST,SOUTH,EAST,NORTH]   # fill the cache: an area, or every picture

find_signs slows down much faster than the area grows (26 s for 1 x 0.6 km of
Strasbourg): the map asks for fixed tiles, located in a pool of processes and kept
in the `located_tiles` collection. A tile is located again when the algorithm's
source files change (see fingerprint).

The server answers at once with the cached tiles, and keeps locating the others,
the last asked first: the map asks again for those still pending.

Zoomed out, the map asks for /counts instead: the located signs, counted in
squares of tiles, from a count per tile held in memory.
"""

import argparse
import hashlib
import json
import math
import multiprocessing
import os
import re
import resource
import signal
import sys
import threading
import time
from collections.abc import Callable, Iterable, Iterator
from concurrent.futures import CancelledError, Future, ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from tqdm import tqdm

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
# tiles located at once by a fill
CHUNK_TILES = 2000
# times a tile is located before it is given up: a worker that crashes (out of
# memory...) takes the tiles of the others with it, located again in a new pool
MAX_ATTEMPTS = 3
# memory a worker may use: a tile needing more fails (MemoryError) instead of the
# whole machine running out of memory; its busiest tiles take several GB
WORKER_MEM_GB = 3.0
# memory left to the rest of the machine when choosing the number of workers
RESERVED_MEM_GB = 4.0
GB = 1 << 30

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


def seen_tiles(max_m: float = MAX_DIST_M) -> list[Tile]:
    """Every tile whose signs a picture with a traffic sign may see: the tiles its
    camera is within max_m of, as area_items grows a tile. In order, by column."""
    tiles: set[Tile] = set()
    dlat = max_m / M_PER_DEG_LAT
    docs = pictures().find(
        {"semantics.key": TRAFFIC_SIGN}, {"_id": 0, "geometry.coordinates": 1}
    )
    for doc in tqdm(docs, desc="listing the tiles", unit=" pictures", unit_scale=True):
        lon, lat = doc["geometry"]["coordinates"]
        dlon = dlat / math.cos(math.radians(lat))
        tiles.update(tiles_of(lon - dlon, lat - dlat, lon + dlon, lat + dlat))
    return sorted(tiles)


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


def available_memory() -> int | None:
    """Bytes the kernel can give without swapping, None if unknown."""
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) * 1024
    except OSError:
        pass
    return None


def default_workers(worker_mem_gb: float) -> int:
    """One per CPU, as many as fit in the memory available at worker_mem_gb each."""
    workers = os.cpu_count() or 1
    if (available := available_memory()) is not None:
        fit = (available - RESERVED_MEM_GB * GB) // (worker_mem_gb * GB)
        workers = min(workers, max(1, int(fit)))
    return workers


def _init_worker(parent: int, mem_bytes: int) -> None:
    """Worker initializer: cap its memory, and exit when the server is gone,
    even killed (-9)."""
    # RLIMIT_DATA, not RLIMIT_AS: the address space reserved (malloc arenas,
    # shared libraries) does not count, only the memory written to
    resource.setrlimit(resource.RLIMIT_DATA, (mem_bytes, mem_bytes))

    def watch() -> None:
        while os.getppid() == parent:
            time.sleep(1)
        os._exit(0)

    threading.Thread(target=watch, daemon=True).start()


class Locator:
    """Locates tiles in a pool of processes, the last asked first, into the cache."""

    def __init__(
        self,
        workers: int | None = None,
        max_waiting: float = MAX_WAITING,
        worker_mem_gb: float = WORKER_MEM_GB,
    ) -> None:
        self.workers = workers or default_workers(worker_mem_gb)
        self.worker_mem_gb = worker_mem_gb
        print(
            f"{self.workers} workers, {worker_mem_gb:g} GB of memory each at most",
            file=sys.stderr,
        )
        self.max_waiting = max_waiting
        self.cache = pictures().database[CACHE]
        self.changed = threading.Condition()  # guards the fields below
        self.waiting: list[Key] = []  # the last asked at the end
        self.running: set[Key] = set()
        self.pool: ProcessPoolExecutor | None = None
        self.pool_fingerprint: str | None = None
        self.attempts: dict[Key, int] = {}  # the tiles that failed, and how often
        self.failed: set[Key] = set()  # given up after MAX_ATTEMPTS
        self.closed = False
        # called once per tile located or given up, from a pool's thread
        self.on_done: Callable[[], None] | None = None
        self.counts_lock = threading.Lock()  # guards the fields below
        # tile -> its signs and the sums of their coordinates, for the default
        # parameters; the tiles without a sign are left out
        self.tile_counts: dict[Tile, tuple[int, float, float]] = {}
        self.counts_fingerprint: str | None = None

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

    def _load_counts(self, current: str) -> None:
        """The counts of the cached tiles located with this code. Counts lock held."""
        if self.counts_fingerprint == current:
            return
        suffix = tile_id((0, 0), CELL_M, MAX_DIST_M).removeprefix("0:0")

        def total(axis: int) -> dict:
            return {
                "$sum": {
                    "$map": {
                        "input": "$signs",
                        "in": {"$arrayElemAt": ["$$this.position", axis]},
                    }
                }
            }

        docs = self.cache.aggregate(
            [
                {
                    "$match": {
                        "_id": {"$regex": re.escape(suffix) + "$"},
                        "fingerprint": current,
                        "signs.0": {"$exists": True},
                    }
                },
                {
                    "$project": {
                        "n": {"$size": "$signs"},
                        "lon": total(0),
                        "lat": total(1),
                    }
                },
            ]
        )
        self.tile_counts = {
            parse_tile(d["_id"].removesuffix(suffix)): (d["n"], d["lon"], d["lat"])
            for d in docs
        }
        self.counts_fingerprint = current

    def _count(self, key: Key, located_with: str, signs: list[Item]) -> None:
        """Keep the counts up to date with a tile just located."""
        tile, cell_m, max_m = key
        with self.counts_lock:
            if (cell_m, max_m) != (CELL_M, MAX_DIST_M):
                return
            if located_with != self.counts_fingerprint:
                return  # loaded again from the cache on the next ask
            if signs:
                self.tile_counts[tile] = (
                    len(signs),
                    sum(s["position"][0] for s in signs),
                    sum(s["position"][1] for s in signs),
                )
            else:
                self.tile_counts.pop(tile, None)

    def counts(
        self, west: float, south: float, east: float, north: float, size: int
    ) -> list[list[float]]:
        """The located signs of the bbox in squares of size x size tiles, aligned
        on multiples of size: [lon, lat, count], at the mean position of the signs.
        Only the cached tiles: nothing is located."""
        i0 = math.floor(west / TILE_DEG) // size * size
        j0 = math.floor(south / TILE_DEG) // size * size
        i1, j1 = math.ceil(east / TILE_DEG), math.ceil(north / TILE_DEG)
        squares: dict[Tile, list[float]] = {}
        with self.counts_lock:
            self._load_counts(fingerprint())
            for (i, j), (n, lon, lat) in self.tile_counts.items():
                if i0 <= i < i1 and j0 <= j < j1:
                    square = squares.setdefault((i // size, j // size), [0, 0.0, 0.0])
                    square[0] += n
                    square[1] += lon
                    square[2] += lat
        return [
            [round(lon / n, 6), round(lat / n, 6), n]
            for n, lon, lat in squares.values()
        ]

    def _fill(self) -> None:
        """Start the waiting tiles while there are idle workers. Lock held."""
        current = fingerprint()
        while self.waiting and len(self.running) < self.workers:
            if self.pool is None or current != self.pool_fingerprint:
                old = self.pool
                # spawned, not forked: the new workers import the edited code
                self.pool = ProcessPoolExecutor(
                    self.workers,
                    mp_context=multiprocessing.get_context("spawn"),
                    initializer=_init_worker,
                    initargs=(os.getpid(), int(self.worker_mem_gb * GB)),
                )
                self.pool_fingerprint = current
                # after: the tiles it cancels come back here, for the new pool
                if old:
                    old.shutdown(wait=False, cancel_futures=True)
            key = self.waiting.pop()
            try:
                future = self.pool.submit(locate_tile, key)
            except BrokenProcessPool:  # a worker crashed: before its tiles say so
                self.waiting.append(key)
                self.pool = None
                continue
            self.running.add(key)
            future.add_done_callback(partial(self._finished, key, self.pool))

    def _finished(self, key: Key, pool: ProcessPoolExecutor, future: Future) -> None:
        retry = done = broken = False
        try:
            located_with, signs = future.result()
            self.cache.update_one(
                {"_id": tile_id(*key)},
                {"$set": {"fingerprint": located_with, "signs": signs}},
                upsert=True,
            )
            self._count(key, located_with, signs)
            done = True
        except CancelledError:
            retry = True  # by a new pool, for edited code: not the tile's fault
        except MemoryError:
            # it would need as much again: given up at once
            tqdm.write(
                f"tile {tile_id(*key)} failed: over {self.worker_mem_gb:g} GB "
                "of memory (--worker-mem)",
                file=sys.stderr,
            )
            self.failed.add(key)
            done = True
        except Exception as e:  # noqa: BLE001 - one tile, the others go on
            attempts = self.attempts.get(key, 0) + 1
            retry = attempts < MAX_ATTEMPTS
            broken = isinstance(e, BrokenProcessPool)
            # above the progress bar, if any
            tqdm.write(
                f"tile {tile_id(*key)} failed ({attempts}/{MAX_ATTEMPTS}): "
                + ("a worker crashed" if broken else repr(e)),
                file=sys.stderr,
            )
            self.attempts[key] = attempts
            if not retry:
                self.failed.add(key)
                done = True
        with self.changed:
            if broken and self.pool is pool:
                self.pool = None  # a new one on the next fill
            self.running.discard(key)
            if retry and not self.closed:
                self.waiting.append(key)
            if not self.closed:
                self._fill()
            # held: counted before locate returns
            if done and self.on_done:
                self.on_done()
            self.changed.notify_all()

    def close(self) -> None:
        with self.changed:
            self.closed = True
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
                # None: a lock's timeout cannot be infinite
                self.changed.wait(None if math.isinf(left) else left)
        return found | self.cached(missing)


def locate_chunks(
    locator: Locator, tiles: list[Tile], cell_m: float, max_m: float
) -> Iterator[dict[Key, list[Item]]]:
    """The located tiles, CHUNK_TILES at a time, under a progress bar."""
    chunks = [
        [(t, cell_m, max_m) for t in tiles[first : first + CHUNK_TILES]]
        for first in range(0, len(tiles), CHUNK_TILES)
    ]
    signs = done = 0
    with tqdm(total=len(tiles), unit="tile", smoothing=0.01) as bar:
        locator.on_done = partial(bar.update, 1)
        for n, keys in enumerate(chunks):
            if n + 1 < len(chunks):
                # queued under this chunk: located by the workers it leaves idle
                # at its end, and while the caller handles it
                locator.locate(chunks[n + 1], wait_s=0)
            found = locator.locate(keys, wait_s=math.inf)
            done += len(keys)
            # the cached ones, not seen by on_done (ahead: the next chunk's)
            bar.update(max(0, done - bar.n))
            signs += sum(map(len, found.values()))
            bar.set_postfix(signs=signs, failed=len(locator.failed))
            yield found
        locator.on_done = None


def serve(
    port: int, workers: int | None = None, worker_mem_gb: float = WORKER_MEM_GB
) -> None:
    locator = Locator(workers, worker_mem_gb=worker_mem_gb)

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            url = urlparse(self.path)
            if url.path == "/health":
                self.send_response(204)
                self.end_headers()
                return
            q = parse_qs(url.query)
            if url.path == "/counts":
                try:
                    west, south, east, north = (
                        float(v) for v in q["bbox"][0].split(",")
                    )
                    size = int(q["size"][0])
                    if size < 1:
                        raise ValueError(size)
                except KeyError, ValueError:
                    self.send_error(400, "expected bbox=w,s,e,n&size=tiles")
                    return
                counts = locator.counts(west, south, east, north, size)
                self._json({"counts": counts})
                return
            if url.path != "/tiles":
                self.send_error(404)
                return
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
            self._json(
                {
                    "tiles": {tile_name(k[0]): found[k] for k in keys if k in found},
                    "pending": [tile_name(k[0]) for k in keys if k not in found],
                }
            )

        def _json(self, value: object) -> None:
            body = json.dumps(value).encode()
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


def add_worker_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--workers",
        type=int,
        help="processes locating tiles (default: one per CPU, as many as fit in memory)",
    )
    parser.add_argument(
        "--worker-mem",
        type=float,
        default=WORKER_MEM_GB,
        help=f"GB of memory a worker may use (default: {WORKER_MEM_GB:g})",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument(
        "target",
        nargs="?",
        help='"serve", or west,south,east,north to fill (none: every picture)',
    )
    parser.add_argument("--port", type=int, default=PORT)
    parser.add_argument("--cell", type=float, default=CELL_M)
    parser.add_argument("--max-dist", type=float, default=MAX_DIST_M)
    add_worker_args(parser)
    args = parser.parse_args()
    if args.target == "serve":
        serve(args.port, args.workers, args.worker_mem)
        return
    if args.target:
        west, south, east, north = (float(v) for v in args.target.split(","))
        tiles = tiles_of(west, south, east, north)
    else:
        tiles = seen_tiles(args.max_dist)
    locator = Locator(args.workers, max_waiting=math.inf, worker_mem_gb=args.worker_mem)
    signs = located = 0
    for found in locate_chunks(locator, tiles, args.cell, args.max_dist):
        signs += sum(map(len, found.values()))
        located += len(found)
    locator.close()
    print(
        f"{signs} signs in {located}/{len(tiles)} tiles ({len(locator.failed)} failed)",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
