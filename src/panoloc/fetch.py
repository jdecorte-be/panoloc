"""Download the pictures around a target Panoramax picture, with their metadata.

Output: data/raw/<sequence_id>/<rank>_<picture_id>.{jpg,json}
"""

import argparse
import json
import logging
import math
import time
from pathlib import Path
from typing import Any

import requests

API = "https://api.panoramax.xyz/api"
VIEWER = "https://api.panoramax.xyz/"
DATA_DIR = Path("data/raw")
M_PER_DEG_LAT = 111_320  # meters per degree of latitude (approx.)
TIMEOUT_S = 30
CHUNK_SIZE = 1 << 16  # 64 KiB per read when streaming an image

log = logging.getLogger(__name__)

# A STAC item is untyped JSON: all we know is "an object with string keys".
Item = dict[str, Any]


def get_picture(session: requests.Session, pic_id: str) -> Item:
    """Return the STAC item of a single picture."""
    log.info("looking up picture %s", pic_id)
    r = session.get(f"{API}/search", params={"ids": pic_id}, timeout=TIMEOUT_S)
    r.raise_for_status()
    features: list[Item] = r.json()["features"]
    if not features:
        raise ValueError(f"picture not found: {pic_id}")
    return features[0]


def bbox_around(lon: float, lat: float, radius_m: float) -> str:
    """Square bbox of +/- radius_m around a point: 'minlon,minlat,maxlon,maxlat'."""
    dlat = radius_m / M_PER_DEG_LAT
    # a degree of longitude gets shorter as you move away from the equator
    dlon = dlat / math.cos(math.radians(lat))
    return f"{lon - dlon},{lat - dlat},{lon + dlon},{lat + dlat}"


def get_sequence_items(
    session: requests.Session, seq_id: str, bbox: str, page_size: int
) -> list[Item]:
    """All items of one sequence inside a bbox, following the pagination."""
    items: list[Item] = []
    url: str | None = f"{API}/collections/{seq_id}/items"
    params: dict[str, str | int] | None = {"bbox": bbox, "limit": page_size}
    page = 0
    while url:
        page += 1
        log.info("fetching sequence page %d ...", page)
        r = session.get(url, params=params, timeout=TIMEOUT_S)
        r.raise_for_status()
        data: Item = r.json()
        items += data["features"]
        log.info(
            "page %d: +%d items (total %d)", page, len(data["features"]), len(items)
        )
        links: list[Item] = data.get("links", [])
        url = next((link["href"] for link in links if link.get("rel") == "next"), None)
        params = None  # the "next" link already carries the query params
    return items


def rank_of(item: Item) -> int:
    """Position of the picture along the capture path."""
    return int(item["properties"]["geovisio:rank_in_collection"])


def neighbors(items: list[Item], target_id: str, window: int) -> list[Item]:
    """The target and up to `window` pictures before and after it, in capture order."""
    ordered = sorted(items, key=rank_of)
    i = [item["id"] for item in ordered].index(target_id)
    return ordered[max(0, i - window) : i + window + 1]


def download(session: requests.Session, url: str, dest: Path) -> None:
    """Stream a file to disk; skip it if already downloaded."""
    if dest.exists():
        log.info("  cached, skipped")
        return
    start = time.perf_counter()
    size = 0
    tmp = dest.with_name(dest.name + ".part")
    # stream=True: the body is read chunk by chunk, never fully loaded in RAM
    with session.get(url, stream=True, timeout=TIMEOUT_S) as r:
        r.raise_for_status()
        with tmp.open("wb") as fh:
            for chunk in r.iter_content(chunk_size=CHUNK_SIZE):
                size += fh.write(chunk)
    # rename is atomic: an interrupted run never leaves a half-written .jpg
    tmp.replace(dest)
    elapsed = time.perf_counter() - start
    mb = size / 1e6
    log.info("  done: %.1f MB in %.1f s (%.1f MB/s)", mb, elapsed, mb / elapsed)


def save_item(session: requests.Session, item: Item, out_dir: Path) -> None:
    """Write the full metadata as JSON, then the HD image next to it."""
    # zero-padded rank: files sort in capture order with a plain `ls`
    stem = f"{rank_of(item):05d}_{item['id']}"
    (out_dir / f"{stem}.json").write_text(
        json.dumps(item, indent=2, ensure_ascii=False)
    )
    download(session, item["assets"]["hd"]["href"], out_dir / f"{stem}.jpg")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pic_id", help="target picture id")
    parser.add_argument("--radius", type=float, default=100, help="search radius (m)")
    parser.add_argument(
        "--window", type=int, default=5, help="pictures kept on each side"
    )
    parser.add_argument("--page-size", type=int, default=100)
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="also log every HTTP request"
    )
    args = parser.parse_args()
    pic_id: str = args.pic_id

    # logs go to stderr, unbuffered: you see them as they happen
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-5s %(message)s",
        datefmt="%H:%M:%S",
    )

    # one Session = one TCP/TLS connection reused across all requests
    with requests.Session() as session:
        target = get_picture(session, pic_id)
        lon, lat = target["geometry"]["coordinates"]
        seq_id: str = target["collection"]
        log.info("target   : %s?pic=%s", VIEWER, pic_id)
        log.info("sequence : %s", seq_id)

        bbox = bbox_around(lon, lat, args.radius)
        items = get_sequence_items(session, seq_id, bbox, args.page_size)
        selected = neighbors(items, pic_id, args.window)
        log.info(
            "%d pictures selected out of %d in the bbox", len(selected), len(items)
        )

        out_dir = DATA_DIR / seq_id
        out_dir.mkdir(parents=True, exist_ok=True)
        for i, item in enumerate(selected, start=1):
            n_annot = len(item["properties"].get("annotations") or [])
            mark = " <- target" if item["id"] == pic_id else ""
            log.info(
                "[%d/%d] rank %d, %d annotations%s",
                i,
                len(selected),
                rank_of(item),
                n_annot,
                mark,
            )
            save_item(session, item, out_dir)

    log.info("%d pictures saved in %s", len(selected), out_dir)


if __name__ == "__main__":
    main()
