import math
from collections import Counter, defaultdict
from dataclasses import dataclass

from panoloc.annotations import annotation_heading, annotation_width
from panoloc.bbox import M_PER_DEG_LAT
from panoloc.geo import bearing_distance, signed_angle
from panoloc.signs import sign_name
from panoloc.triangulation import triangulate_many
from panoloc.utils import Node, Point

Cell = tuple[int, int]
Group = tuple[str, int]  # (sign type, sector of the travel direction)
MIN_MOVE_M = 0.5  # below that the GPS noise is bigger than the move
SECTORS = "NESW"
SIGN_MIN_RAYS = 3  # with 2, a far sign seen from 2 close pictures splits into several signs
SIGN_RADIUS_M = 1.0  # a ray passing that close to a sign is a picture of it
# pictures seeing a sign from closer directions can't place it: their rays are
# nearly parallel (a sign seen at 2.5° could be anywhere within ±70 m)
SIGN_MIN_SPAN_DEG = 5
# signs are about that wide, so the width of a box tells how far its sign is; signs
# are 0.26 to 1.6 m wide (sub-panels to big arrows), so that distance is within x/÷2.5
SIGN_WIDTH_M = 0.65
SIGN_WIDTH_FACTOR = 2.5


@dataclass
class Ray:
    x: float
    y: float
    size: float
    bearing: float
    azimuth: (
        float | None
    )  # travel direction of the car, None when it is not moving
    photo_id: str
    annotation_id: str | None
    width: float | None = None  # how wide the box looks, in degrees


def sign_type_of(annot):
    # "yes" = a sign without its type, it would only duplicate the typed ones
    values = [
        s["value"]
        for s in annot.get("semantics") or []
        if s.get("key") == "osm|traffic_sign" and s.get("value") != "yes"
    ]
    return values[0] if values else None


# to fix watching the north
def travel_azimuths(items):
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
            width = annotation_width(annot["shape"], props)
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
                        width,
                    ),
                )
            )
    return rays


def group_rays(rays_with_type):
    groups = defaultdict(list)

    for sign_type, r in rays_with_type:
        if (
            r.azimuth is None
        ):  # car not moving, no way to know which side the sign faces
            continue
        sector = int(((r.azimuth + 45) % 360) // 90)  # 0=N, 1=E, 2=S, 3=W
        groups[(sign_type, sector)].append(r)
    return groups


def ray_groups(items, lon, lat, radius_m):
    return group_rays(make_rays(items, lon, lat, radius_m))


def group_label(key):
    sign_type, sector = key
    return f"{sign_name(sign_type)}, driving {SECTORS[sector]}"


def crossed_cells(r, side, cell_m, max_m, min_m=0.0):
    n = math.ceil(round(side / cell_m, 9))
    step = cell_m / 4  # should be small enough to hit every cells
    dx = math.sin(math.radians(r.bearing))  # east
    dy = math.cos(math.radians(r.bearing))  # north
    crossed: set[Cell] = set()
    d = min_m
    while (
        d <= max_m
        and 0 <= (x := r.x + d * dx) <= side
        and 0 <= (y := r.y + d * dy) <= side
    ):
        crossed.add(
            (min(int(x // cell_m), n - 1), min(int(y // cell_m), n - 1))
        )
        d += step
    return crossed


def vote(rays, side, cell_m, max_m):
    heat: Counter[Cell] = Counter()
    for r in rays:
        heat.update(crossed_cells(r, side, cell_m, min(r.size, max_m)))
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


def the_ray_voting_algorithm(items, lon, lat, radius_m, cell_m, max_m):
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
        key: blur(vote(group, side, cell_m, max_m))
        for key, group in groups.items()
    }


@dataclass
class Sign:
    number: int  # the same in every picture, 1 = the most seen sign
    sign_type: str
    x: float
    y: float
    rays: list[Ray]


def offset(r, x, y):
    """(how far the ray passes from (x, y), how far along the ray that is)."""
    dx = math.sin(math.radians(r.bearing))
    dy = math.cos(math.radians(r.bearing))
    return abs((x - r.x) * dy - (y - r.y) * dx), (x - r.x) * dx + (
        y - r.y
    ) * dy


def sees(r, x, y, max_m, min_m=0.0):
    """Does the ray pass within SIGN_RADIUS_M of (x, y), between min_m and max_m?"""
    miss, along = offset(r, x, y)
    return miss <= SIGN_RADIUS_M and min_m < along <= max_m


def distance_window(r, max_m):
    """(min, max) distance of the ray's sign, from the size of its box.

    Better than 0 to max_m: a picture far from its sign reaches it, instead of
    stopping in front of it where the cut rays of several far signs crossed each
    other and made ghost signs.
    """
    if not r.width:  # no box size: the whole ray
        return 0.0, max_m
    dist = SIGN_WIDTH_M / math.radians(r.width)
    return dist / SIGN_WIDTH_FACTOR, dist * SIGN_WIDTH_FACTOR


def weighted_median(values):
    """[(value, weight)] -> the value in the middle of the total weight."""
    ordered = sorted(values)
    half = sum(w for _, w in ordered) / 2
    total = 0.0
    for v, w in ordered:
        total += w
        if total >= half:
            return v


def sign_position(rays, x, y):
    """Where the sign's rays cross (triangulate_many), more precise than the cell (x, y)."""
    scores = triangulate_many([Node(Point(r.x, r.y), r.bearing) for r in rays])
    if not scores:  # the rays never cross in front of both cameras
        return x, y
    # the median, not the best score: noisy rays never cross twice at the exact same
    # point so every crossing ties, and two nearly parallel rays cross far away
    return (
        weighted_median([(pt.x, score) for pt, score in scores.items()]),
        weighted_median([(pt.y, score) for pt, score in scores.items()]),
    )


def view_span(rays, x, y):
    """Widest angle between two of the pictures, seen from (x, y)."""
    angles = [math.degrees(math.atan2(r.x - x, r.y - y)) for r in rays]
    return max(
        (abs(signed_angle(a - b)) for a in angles for b in angles), default=0.0
    )


def nearest_per_picture(rays, candidates, x, y):
    """Of the candidate rays, the one passing closest to (x, y) in each picture:
    two boxes of a picture are two signs side by side."""
    closest = {}
    for i in sorted(candidates, key=lambda i: offset(rays[i], x, y)[0]):
        closest.setdefault(rays[i].photo_id, i)
    return sorted(closest.values())


def locate_signs(rays, windows, side, cell_m):
    """Rays of one sign type -> [(x, y, its rays)], one per physical sign.

    windows: (min, max) distance of each ray's sign, see distance_window.

    Greedy: the cell crossed by the most rays is a sign and the rays passing near
    it are its pictures. They leave the heatmap, so a ray counts for one sign only
    and a sign can't come back as a second peak next to the first one.
    """
    crossed = [
        crossed_cells(r, side, cell_m, hi, lo)
        for r, (lo, hi) in zip(rays, windows)
    ]
    heat: Counter[Cell] = Counter()
    for cells in crossed:
        heat.update(cells)
    left = list(range(len(rays)))
    found = []
    while heat:
        cell, n = max(heat.items(), key=lambda kv: (kv[1], kv[0]))
        if n < SIGN_MIN_RAYS:
            break
        x, y = (cell[0] + 0.5) * cell_m, (cell[1] + 0.5) * cell_m
        # 2nd pass from where the rays cross: more precise than the cell, so it
        # also gets the rays passing a bit too far from the cell center
        for _ in range(2):
            # the rays crossing the cell always join: the loop moves on even with big cells
            near = [
                i
                for i in left
                if cell in crossed[i]
                or sees(rays[i], x, y, windows[i][1], windows[i][0])
            ]
            members = nearest_per_picture(rays, near, x, y)
            if len(members) < 2:  # one picture can't triangulate
                break
            x, y = sign_position([rays[i] for i in members], x, y)
        # one picture, or pictures from nearly the same direction, can't triangulate
        if (
            len(members) < 2
            or view_span([rays[i] for i in members], x, y) < SIGN_MIN_SPAN_DEG
        ):
            del heat[cell]
            continue
        for i in members:
            heat.subtract(crossed[i])
        heat = +heat  # drop the cells no ray crosses anymore
        left = [i for i in left if i not in members]
        found.append((x, y, [rays[i] for i in members]))
    return found


def find_signs(items, lon, lat, radius_m, cell_m, max_m):
    """Every sign of the pictures, numbered from the most seen one.

    A car standing still takes the same ray again and again, so those pictures
    don't locate signs: they are only matched to the signs the others found.
    max_m only limits the rays whose box size is unknown, see distance_window.
    """
    side = 2 * radius_m
    by_type = defaultdict(list)
    for sign_type, r in make_rays(items, lon, lat, radius_m):
        by_type[sign_type].append(r)

    signs = []
    for sign_type, rays in sorted(by_type.items()):
        windows = {id(r): distance_window(r, max_m) for r in rays}
        moving = [r for r in rays if r.azimuth is not None]
        found = [
            Sign(0, sign_type, x, y, seen)
            for x, y, seen in locate_signs(
                moving, [windows[id(r)] for r in moving], side, cell_m
            )
        ]
        taken = {id(r) for s in found for r in s.rays}
        for r in rays:
            if id(r) in taken:
                continue
            near = [
                s
                for s in found
                if sees(r, s.x, s.y, windows[id(r)][1], windows[id(r)][0])
                and all(o.photo_id != r.photo_id for o in s.rays)
            ]
            # pointing at 2 signs of its type (lined up, seen from far), it could be either
            if len(near) == 1:
                near[0].rays.append(r)
        signs += found

    signs.sort(key=lambda s: (-len(s.rays), s.sign_type, s.x, s.y))
    for number, s in enumerate(signs, 1):
        s.number = number
    return signs


def sign_numbers(signs):
    """annotation id -> number of the sign it shows."""
    return {
        r.annotation_id: s.number
        for s in signs
        for r in s.rays
        if r.annotation_id
    }


def sign_distances(signs):
    """annotation id -> meters from the camera to the sign it shows."""
    return {
        r.annotation_id: math.hypot(s.x - r.x, s.y - r.y)
        for s in signs
        for r in s.rays
        if r.annotation_id
    }
