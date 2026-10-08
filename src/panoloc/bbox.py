import json
import math
from pathlib import Path
from typing import Any

import requests

DATA_DIR = Path("data/raw")
CHUNK_SIZE = 1 << 16  # 64 KiB per read when streaming an image
API = "https://api.panoramax.xyz/api"
M_PER_DEG_LAT = 111_320  # meters per degree of latitude (approx.)
TIMEOUT_S = 10

# A STAC item is untyped JSON: all we know is "an object with string keys".
Item = dict[str, Any]

SESSION = requests.Session()


class PictureNotFound(Exception):
    pass


def get_picture(pic_id: str) -> Item:
    r = SESSION.get(f"{API}/search", params={"ids": pic_id}, timeout=TIMEOUT_S)
    r.raise_for_status()
    features = r.json()["features"]
    if not features:
        raise PictureNotFound(pic_id)
    return features[0]


def bbox_around(lon: float, lat: float, radius_m: float) -> str:
    dlat = radius_m / M_PER_DEG_LAT
    dlon = dlat / math.cos(math.radians(lat))
    return f"{lon - dlon},{lat - dlat},{lon + dlon},{lat + dlat}"


def fetch_sequence_items(
    seq_id: str, bbox: str, limit: int = 10_000
) -> list[Item]:
    # /collections/{id}/items ignores bbox (it returns the whole sequence), so use
    # /search. It does not paginate: anything past `limit` is silently dropped.
    params = {"bbox": bbox, "collections": seq_id, "limit": limit}
    r = SESSION.get(f"{API}/search", params=params, timeout=TIMEOUT_S)
    r.raise_for_status()
    return r.json()["features"]


def save_item(item: Item) -> Path:
    """Write the item as JSON, return the path where its image belongs."""
    folder = DATA_DIR / item["collection"]
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{item['id']}.json").write_text(
        json.dumps(item, indent=2, ensure_ascii=False)
    )
    return folder / f"{item['id']}.jpg"


def ensure_image(url: str, dest: Path) -> None:
    """Download url to dest, unless it is already there."""
    if dest.exists():
        return
    tmp = dest.with_suffix(".jpg.part")
    # stream=True: read chunk by chunk, the image is never fully in RAM
    with SESSION.get(url, stream=True, timeout=TIMEOUT_S) as r:
        r.raise_for_status()
        with tmp.open("wb") as fh:
            for chunk in r.iter_content(chunk_size=CHUNK_SIZE):
                fh.write(chunk)
    tmp.replace(dest)  # atomic: a crash never leaves a half-written .jpg


def fetch_image(url: str) -> bytes:
    """Download url in memory, nothing written to disk."""
    r = SESSION.get(url, timeout=TIMEOUT_S)
    r.raise_for_status()
    return r.content


def nearby_pictures(
    pic_id: str, radius_m: float = 10, download: bool = False
) -> list[Item]:
    target = get_picture(pic_id)
    lon, lat = target["geometry"]["coordinates"]
    seq = target["collection"]
    bbox = bbox_around(lon, lat, radius_m)
    items = fetch_sequence_items(seq, bbox)
    pics = [
        {
            "id": f["id"],
            "sequence": f["collection"],
            "datetime": f["properties"].get("datetime"),
            "lon": f["geometry"]["coordinates"][0],
            "lat": f["geometry"]["coordinates"][1],
            "thumb": f["assets"]["thumb"]["href"],
            "hd": f["assets"]["hd"]["href"],
            "item": f,  # full STAC item: annotations, azimuth, tags...
        }
        for f in items
        if f["collection"] == seq
    ]
    # the API's bbox filter is loose: a few pictures just outside slip through
    x0, y0, x1, y1 = (float(v) for v in bbox.split(","))
    pics = [p for p in pics if x0 <= p["lon"] <= x1 and y0 <= p["lat"] <= y1]
    # only annotated pictures are useful; the target stays, the viewer jumps to it
    pics = [
        p
        for p in pics
        if p["id"] == pic_id or p["item"]["properties"].get("annotations")
    ]
    for p in pics:
        path = save_item(p["item"])
        if download:
            ensure_image(p["hd"], path)
        # local file if there is one (downloaded now or before), else the app reads p["hd"]
        p["jpg"] = str(path) if path.exists() else None
    return sorted(pics, key=lambda p: p["datetime"] or "")
