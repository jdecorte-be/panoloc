import math

import requests

API = "https://api.panoramax.xyz/api"
TIMEOUT = 10

_session = requests.Session()


class PictureNotFound(Exception):
    pass


def get_picture(pic_id: str) -> dict:
    r = _session.get(f"{API}/search", params={"ids": pic_id}, timeout=TIMEOUT)
    r.raise_for_status()
    features = r.json()["features"]
    if not features:
        raise PictureNotFound(pic_id)
    return features[0]


def bbox_around(lon: float, lat: float, radius_m: float) -> str:
    dlat = radius_m / 111_320
    dlon = dlat / math.cos(math.radians(lat))
    return f"{lon - dlon},{lat - dlat},{lon + dlon},{lat + dlat}"


def fetch_sequence_items(seq_id: str, bbox: str, limit: int = 10_000) -> list[dict]:
    # /collections/{id}/items ignores bbox (it returns the whole sequence), so use
    # /search. It does not paginate: anything past `limit` is silently dropped.
    params = {"bbox": bbox, "collections": seq_id, "limit": limit}
    r = _session.get(f"{API}/search", params=params, timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()["features"]


def nearby_pictures(pic_id: str, radius_m: float = 10) -> list[dict]:
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
            "thumb": f"{API}/pictures/{f['id']}/thumb.jpg",
            "hd": f"{API}/pictures/{f['id']}/hd.jpg",
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
    return sorted(pics, key=lambda p: p["datetime"] or "")
