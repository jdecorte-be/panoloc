import math
from collections import Counter, defaultdict
from dataclasses import dataclass

from panoloc.annotations import annotation_heading
from panoloc.bbox import M_PER_DEG_LAT
from panoloc.geo import bearing_distance

Cell = tuple[int, int]
Group = tuple[str, int]  # (sign type, sector of the travel direction)
MIN_MOVE_M = 0.5  # below that the GPS noise is bigger than the move
SECTORS = "NESW"


@dataclass
class Ray:
    x: float
    y: float
    size: float
    bearing: float
    azimuth: float  # travel direction of the car
    photo_id: str
    annotation_id: str | None


def sign_type_of(annot):
    values = [
        s["value"]
        for s in annot.get("semantics") or []
        if s.get("key") == "osm|traffic_sign"
    ]
    precise = [v for v in values if v != "yes"]
    return precise[0] if precise else (values[0] if values else None)


def travel_azimuths(items):
    """Travel direction of every photo, from the previous to the next photo of its sequence.

    view:azimuth is not used: it is the camera heading, and some images are rotated to the north.
    """
    sequences = defaultdict(list)
    for item in items:
        sequences[item.get("collection")].append(item)

    azimuths = {}
    for seq in sequences.values():
        seq.sort(key=lambda it: it["properties"].get("datetime") or "")
        for i, item in enumerate(seq):
            prev = seq[max(i - 1, 0)]["geometry"]["coordinates"]
            nxt = seq[min(i + 1, len(seq) - 1)]["geometry"]["coordinates"]
            azimuth, dist = bearing_distance(*prev, *nxt)
            if dist >= MIN_MOVE_M:
                azimuths[item["id"]] = azimuth % 360
    return azimuths


def make_rays(items, lon, lat, radius_m):
    m_per_deg_lon = M_PER_DEG_LAT * math.cos(math.radians(lat))
    azimuths = travel_azimuths(items)
    rays = []
    for item in items:
        azimuth = azimuths.get(item["id"])
        if (
            azimuth is None
        ):  # car not moving, no way to know which side the sign faces
            continue
        props = item["properties"]
        cam_lon, cam_lat = item["geometry"]["coordinates"]

        # camera position in meters
        x0 = (cam_lon - lon) * m_per_deg_lon + radius_m
        y0 = (cam_lat - lat) * M_PER_DEG_LAT + radius_m
        for annot in props.get("annotations") or []:
            sign_type = sign_type_of(annot)
            heading = annotation_heading(annot["shape"], props)
            if sign_type is None or heading is None:
                continue
            rays.append(
                (
                    sign_type,
                    Ray(
                        x0,
                        y0,
                        50,
                        heading,
                        azimuth,
                        item["id"],
                        annot.get("id"),
                    ),
                )
            )
    return rays


def group_rays(rays_with_type):
    groups = defaultdict(list)

    for sign_type, r in rays_with_type:
        sector = int(((r.azimuth + 45) % 360) // 90)  # 0=N, 1=E, 2=S, 3=W
        groups[(sign_type, sector)].append(r)
    return groups


def ray_groups(items, lon, lat, radius_m):
    return group_rays(make_rays(items, lon, lat, radius_m))


def group_label(key):
    sign_type, sector = key
    return f"{sign_type} (driving {SECTORS[sector]})"


def vote(rays, side, cell_m):
    n = math.ceil(round(side / cell_m, 9))
    step = cell_m / 4  # should be small enough to hit every cells
    heat: Counter[Cell] = Counter()

    for r in rays:
        dx = math.sin(math.radians(r.bearing))  # east
        dy = math.cos(math.radians(r.bearing))  # north
        crossed: set[Cell] = set()
        d = 0.0
        # TODO: add max distance
        while (
            d <= r.size
            and 0 <= (x := r.x + d * dx) <= side
            and 0 <= (y := r.y + d * dy) <= side
        ):
            crossed.add(
                (min(int(x // cell_m), n - 1), min(int(y // cell_m), n - 1))
            )
            d += step

        heat.update(crossed)
    return heat


# TODO: ok that work but gaussian blur, can be more precise if the gps is low quality. Like poor gps increase gaussian blur
def blur(grid):
    smooth = defaultdict(float)

    for (x, y), score in grid.items():
        share = score / 9
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                smooth[(x + dx, y + dy)] += share
    return dict(smooth)


def the_ray_voting_algorithm(items, lon, lat, radius_m, cell_m):
    """
    That will be the best algorithm ever:

    1. We gonna iterate on every item
    2. Every time, we gonna follow the ray and increase the heatmap following the ray
    3. If everything work correctly, we have some high number on the heatmap which will represent the signs

    Problems:
            If there's multiple sign in the same place what happen?

    """
    side = 2 * radius_m
    groups = ray_groups(items, lon, lat, radius_m)
    return {
        key: blur(vote(group, side, cell_m)) for key, group in groups.items()
    }
