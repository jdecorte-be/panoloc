import json
import math
import os
from functools import cache
from pathlib import Path
from typing import Any

import requests
from pymongo import MongoClient
from pymongo.collection import Collection

DATA_DIR = Path("data/raw")
CHUNK_SIZE = 1 << 16  # 64 KiB per read when streaming an image
COLLECTION = "pictures"  # filled by `make populate`
M_PER_DEG_LAT = 111_320  # meters per degree of latitude (approx.)
TIMEOUT_S = 10

# A STAC item is untyped JSON: all we know is "an object with string keys".
Item = dict[str, Any]

SESSION = requests.Session()


class PictureNotFound(Exception):
    pass


@cache
def pictures() -> Collection:
    """The MongoDB collection, connected with the same settings as docker-compose.yml."""
    uri = os.environ.get("MONGO_URI") or (
        "mongodb://{user}:{password}@{host}:{port}/?authSource=admin".format(
            user=os.environ.get("MONGO_ROOT_USERNAME", "panoloc"),
            password=os.environ.get("MONGO_ROOT_PASSWORD", "panoloc"),
            host=os.environ.get("MONGO_HOST", "localhost"),
            port=os.environ.get("MONGO_PORT", "27017"),
        )
    )
    client = MongoClient(uri, serverSelectionTimeoutMS=TIMEOUT_S * 1000)
    return client[os.environ.get("MONGO_DATABASE", "panoloc")][COLLECTION]


def to_item(doc: Item) -> Item:
    """A database document as the STAC item the Panoramax API returns."""
    annotations: dict[str, Item] = {}  # by id, in their order of appearance
    picture_semantics = []
    for s in doc.get("semantics") or []:
        tag = {"key": s["key"], "value": s["value"]}
        on = s.get("on") or {}
        if on.get("field") == "annotation":
            annot = annotations.setdefault(
                on["id"],
                {"id": on["id"], "shape": on["geometry"], "semantics": []},
            )
            annot["semantics"].append(tag)
        elif (
            on.get("field") != "collection"
        ):  # the sequence's tags are not the picture's
            picture_semantics.append(tag)
    return {
        "id": doc["id"],
        "collection": doc["collection"],
        "geometry": doc["geometry"],
        "properties": {
            "datetime": doc.get("datetime"),
            "view:azimuth": doc.get("azimuth"),
            "quality:horizontal_accuracy": doc.get("horizontal_accuracy"),
            "pers:interior_orientation": doc.get("interior_orientation"),
            "semantics": picture_semantics,
            "annotations": list(annotations.values()),
        },
        "assets": {
            name: {"href": href}
            for name, href in (doc.get("assets") or {}).items()
            if href
        },
    }


def get_picture(pic_id: str) -> Item:
    doc = pictures().find_one({"_id": pic_id})
    if doc is None:
        raise PictureNotFound(pic_id)
    return to_item(doc)


def bbox_around(lon: float, lat: float, radius_m: float) -> str:
    dlat = radius_m / M_PER_DEG_LAT
    dlon = dlat / math.cos(math.radians(lat))
    return f"{lon - dlon},{lat - dlat},{lon + dlon},{lat + dlat}"


def fetch_sequence_items(seq_id: str, bbox: str) -> list[Item]:
    x0, y0, x1, y1 = (float(v) for v in bbox.split(","))
    ring = [[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]]
    query = {
        "collection": seq_id,
        "geometry": {
            "$geoWithin": {
                "$geometry": {"type": "Polygon", "coordinates": [ring]}
            }
        },
    }
    return [to_item(doc) for doc in pictures().find(query)]


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
            "thumb": f["assets"].get("thumb", {}).get("href"),
            "hd": f["assets"].get("hd", {}).get("href"),
            "item": f,  # full STAC item: annotations, azimuth, tags...
        }
        for f in items
    ]
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
