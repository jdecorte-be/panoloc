import math
from collections import Counter, defaultdict
from dataclasses import dataclass

from panoloc.annotations import annotation_heading, annotation_width
from panoloc.bbox import M_PER_DEG_LAT, Item
from panoloc.geo import bearing_distance, signed_angle
from panoloc.triangulation import triangulate_many
from panoloc.utils import Node, Point

Cell = tuple[int, int]

# TODO: divide in more multiple section maybe (4 for now)?
Group = tuple[
    str, int
]  # (sign type, sector of the travel direction) -> N, E, S, W

# opt5: min number of meters needed to trust the image
# the gps noise is too important to lower taht for now
MIN_MOVE_M = 0.5

# opt3: min number of picture mandatory
SIGN_MIN_RAYS = 3

# opt4: every ray around this radius is a ray of the sign,
# so that avoid that we have many intersection
# TODO: decrease if we have orienternet
SIGN_RADIUS_M = 1.0

# opt2: try to avoid nearly parallel rays
SIGN_MIN_SPAN_DEG = 1

# opt1: signs are between 0.26 to 1.6m so lets say 0.65 for the average size
SIGN_WIDTH_M = 0.65
SIGN_WIDTH_FACTOR = 2.5


@dataclass
class Ray:
    x: float
    y: float
    size: float
    bearing: float
    azimuth: float | None  # direction of the car
    photo_id: str
    annotation_id: str | None
    width: float | None

    # opt1: this is a rough distance estime
    window: tuple[float, float] = (0.0, math.inf)


# OK
def sign_types_of(annot: Item) -> list[str]:
    """
    Args:
            annot: An annotation of a picture, with its "semantics" tags.
    """
    values = [
        s["value"]
        for s in annot.get("semantics") or []
        if s.get("key") == "osm|traffic_sign"
        and s.get("value") != "yes"  # we ignore sign that we dont know
    ]

    # "stop", "no_entry"...: the same sign as the code next to them
    # the edge case there is that 2 sign can be on the same pole
    coded = [v for v in values if ":" in v] or values
    return list(
        dict.fromkeys(
            t.strip() for v in coded for t in v.split(";") if t.strip()
        )
    )


def travel_azimuths(items: list[Item]) -> dict[str, float]:
    """
    Args:
            items: The pictures, from one or several sequences.
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


# OK: trace the ray per type
def make_rays(
    items: list[Item], lon: float, lat: float, radius_m: float
) -> list[tuple[str, Ray]]:
    """
    Args:
            lon: Longitude of the center of the grid.
            lat: Latitude of the center of the grid.
            radius_m: Half the side of the grid, in meters.
    """
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
            sign_types = sign_types_of(annot)
            heading = annotation_heading(annot["shape"], props)
            if not sign_types or heading is None:
                continue
            width = annotation_width(annot["shape"], props)

            for sign_type in sign_types:  # one ray per sign of the box
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


def group_rays(
    rays_with_type: list[tuple[str, Ray]],
) -> dict[Group, list[Ray]]:
    """
    Args:
            rays_with_type: (sign type, ray) pairs, see make_rays.
    """
    groups = defaultdict(list)

    for sign_type, r in rays_with_type:
        if (
            r.azimuth is None
        ):  # car not moving, no way to know which side the sign faces
            continue
        sector = int(((r.azimuth + 45) % 360) // 90)  # 0=N, 1=E, 2=S, 3=W
        groups[(sign_type, sector)].append(r)
    return groups


def ray_groups(
    items: list[Item], lon: float, lat: float, radius_m: float
) -> dict[Group, list[Ray]]:
    return group_rays(make_rays(items, lon, lat, radius_m))


def crossed_cells(
    r: Ray, side: float, cell_m: float, window: tuple[float, float]
) -> set[Cell]:
    """
    Args:
            side: Side of the grid, in meters.
            cell_m: Side of a cell, in meters.
    """
    lo, hi = window
    n = math.ceil(round(side / cell_m, 9))
    step = cell_m / 4  # should be small enough to hit every cells
    dx = math.sin(math.radians(r.bearing))  # east
    dy = math.cos(math.radians(r.bearing))  # north
    crossed: set[Cell] = set()
    d = lo
    while (
        d <= hi
        and 0 <= (x := r.x + d * dx) <= side
        and 0 <= (y := r.y + d * dy) <= side
    ):
        crossed.add(
            (min(int(x // cell_m), n - 1), min(int(y // cell_m), n - 1))
        )
        d += step
    return crossed


def vote(
    rays: list[Ray], side: float, cell_m: float, max_m: float
) -> Counter[Cell]:
    """
    Args:
            max_m: How far a ray goes, in meters.
    """
    heat: Counter[Cell] = Counter()
    for r in rays:
        heat.update(crossed_cells(r, side, cell_m, (0.0, min(r.size, max_m))))
    return heat


# TODO: ok that work but gaussian blur, can be more precise if the gps is low quality. Like poor gps increase gaussian blur
def blur(grid: Counter[Cell]) -> dict[Cell, float]:
    """
    Args:
            grid: Cell -> score, see vote.
    """
    smooth = defaultdict(float)

    for (x, y), score in grid.items():
        share = score / 9
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                smooth[(x + dx, y + dy)] += share
    return dict(smooth)


def the_ray_voting_algorithm(
    items: list[Item],
    lon: float,
    lat: float,
    radius_m: float,
    cell_m: float,
    max_m: float,
) -> dict[Group, dict[Cell, float]]:
    side = 2 * radius_m
    groups = ray_groups(items, lon, lat, radius_m)
    return {
        key: blur(vote(group, side, cell_m, max_m))
        for key, group in groups.items()
    }


@dataclass
class Sign:
    """
    Attributes:
            number: The same in every picture, 1 = the most seen sign.
            sign_type: Its traffic sign code, e.g. "FR:B14[30]".
            x: East position of the sign.
            y: North position of the sign.
            rays: The rays of the pictures that see it, one per picture.
    """

    number: int  # the same in every picture, 1 = the most seen sign
    sign_type: str
    x: float
    y: float
    rays: list[Ray]


def offset(r: Ray, x: float, y: float) -> tuple[float, float]:
    dx = math.sin(math.radians(r.bearing))
    dy = math.cos(math.radians(r.bearing))
    return abs((x - r.x) * dy - (y - r.y) * dx), (x - r.x) * dx + (
        y - r.y
    ) * dy


def sees(r: Ray, x: float, y: float, window: tuple[float, float]) -> bool:
    lo, hi = window
    miss, along = offset(r, x, y)
    return miss <= SIGN_RADIUS_M and lo < along <= hi


# estimation of the distance, min max window
def distance_window(r: Ray, max_m: float) -> tuple[float, float]:
    """
    Args:
            max_m: Only for the rays whose box size is unknown.
    """
    if not r.width:  # no box size: the whole ray
        return 0.0, max_m
    dist = SIGN_WIDTH_M / math.radians(r.width)
    return dist / SIGN_WIDTH_FACTOR, dist * SIGN_WIDTH_FACTOR


# mediane of the points around the probable sign
def weighted_median(values: list[tuple[float, float]]) -> float:
    """
    Args:
            values: (value, weight) pairs, not empty.
    """
    ordered = sorted(values)
    half = sum(w for _, w in ordered) / 2
    total = 0.0
    for v, w in ordered:
        total += w
        if total >= half:
            return v
    return 0


def sign_position(rays: list[Ray], x: float, y: float) -> tuple[float, float]:
    """
    Args:
            rays: The rays of one sign.
            x: East position to fall back on, e.g. the center of its cell.
            y: North position to fall back on.
    """
    scores = triangulate_many([Node(Point(r.x, r.y), r.bearing) for r in rays])
    if not scores:  # the rays never cross in front of both cameras
        return x, y

    # TODO: the median, not the best score:
    # noisy rays never cross twice at the exact same
    # So I think that point so every crossing ties,
    # and two nearly parallel rays cross far away
    return (
        weighted_median([(pt.x, score) for pt, score in scores.items()]),
        weighted_median([(pt.y, score) for pt, score in scores.items()]),
    )


def view_span(rays: list[Ray], x: float, y: float) -> float:
    angles = [math.degrees(math.atan2(r.x - x, r.y - y)) for r in rays]
    return max(
        (abs(signed_angle(a - b)) for a in angles for b in angles), default=0.0
    )


# sort them by nierest from the picture
def nearest_per_picture(
    rays: list[Ray], candidates: list[int], x: float, y: float
) -> list[int]:
    closest: dict[str, int] = {}
    for i in sorted(candidates, key=lambda i: offset(rays[i], x, y)[0]):
        closest.setdefault(rays[i].photo_id, i)
    return sorted(closest.values())


def locate_signs(
    rays: list[Ray], side: float, cell_m: float
) -> list[tuple[float, float, list[Ray]]]:
    """
    Args:
            rays: The rays of one sign type, with their window set.
    """
    crossed = [crossed_cells(r, side, cell_m, r.window) for r in rays]
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
        members: list[int] = []

        # 2nd pass from where the rays cross: more precise than the cell, so it
        # also gets the rays passing a bit too far from the cell center
        for _ in range(2):
            # the rays crossing the cell always join:
            # the loop moves on even with big cells
            near = [
                i
                for i in left
                if cell in crossed[i] or sees(rays[i], x, y, rays[i].window)
            ]

            members = nearest_per_picture(rays, near, x, y)

            # the cell counts rays, a sign counts pictures:
            # two boxes of one picture are one
            if len(members) < SIGN_MIN_RAYS:
                break
            x, y = sign_position([rays[i] for i in members], x, y)

        # too few pictures, or pictures from nearly the same direction,
        # can't place a sign
        if (
            len(members) < SIGN_MIN_RAYS
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


def find_signs(
    items: list[Item],
    lon: float,
    lat: float,
    radius_m: float,
    cell_m: float,
    max_m: float,
) -> list[Sign]:
    side = 2 * radius_m
    by_type = defaultdict(list)
    for sign_type, r in make_rays(items, lon, lat, radius_m):
        r.window = distance_window(r, max_m)
        by_type[sign_type].append(r)

    signs = []
    for sign_type, rays in sorted(by_type.items()):
        moving = [r for r in rays if r.azimuth is not None]
        found = [
            Sign(0, sign_type, x, y, seen)
            for x, y, seen in locate_signs(moving, side, cell_m)
        ]
        taken = {id(r) for s in found for r in s.rays}
        for r in rays:
            if id(r) in taken:
                continue
            near = [
                s
                for s in found
                if sees(r, s.x, s.y, r.window)
                and all(o.photo_id != r.photo_id for o in s.rays)
            ]

            # pointing at 2 signs of its type (lined up, seen from far),
            # it could be either
            if len(near) == 1:
                near[0].rays.append(r)
        signs += found

    signs.sort(key=lambda s: (-len(s.rays), s.sign_type, s.x, s.y))
    for number, s in enumerate(signs, 1):
        s.number = number
    return signs
