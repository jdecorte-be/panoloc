import math

from panoloc.bbox import M_PER_DEG_LAT, bbox_around


def signed_angle(a: float) -> float:
    """Any angle in degrees -> -180 .. +180."""
    return (a + 180) % 360 - 180


def offset(
    lon: float, lat: float, azimuth_deg: float, dist_m: float
) -> list[float]:
    """Point at dist_m from (lon, lat) toward an azimuth (0 = north, clockwise)."""
    a = math.radians(azimuth_deg)
    dlat = dist_m * math.cos(a) / M_PER_DEG_LAT
    dlon = dist_m * math.sin(a) / (M_PER_DEG_LAT * math.cos(math.radians(lat)))
    return [lon + dlon, lat + dlat]


def bearing_distance(
    lon: float, lat: float, lon2: float, lat2: float
) -> tuple[float, float]:
    """Compass bearing (0 = north, clockwise, -180 .. +180) and distance in m from one point to another."""
    dx = (lon2 - lon) * M_PER_DEG_LAT * math.cos(math.radians(lat))
    dy = (lat2 - lat) * M_PER_DEG_LAT
    return signed_angle(math.degrees(math.atan2(dx, dy))), math.hypot(dx, dy)


def bbox_ring(lon: float, lat: float, radius_m: float) -> list[list[float]]:
    """Search bbox around a point (same as bbox.bbox_around) -> closed polygon ring."""
    x0, y0, x1, y1 = (
        float(v) for v in bbox_around(lon, lat, radius_m).split(",")
    )
    return [[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]]


def grid_lines(
    lon: float, lat: float, radius_m: float, cell_m: float
) -> list[dict[str, list[float]]]:
    x0, y0, x1, y1 = (
        float(v) for v in bbox_around(lon, lat, radius_m).split(",")
    )
    side = 2 * radius_m
    steps = [
        i * cell_m / side for i in range(math.ceil(round(side / cell_m, 9)))
    ] + [1.0]
    lines = []

    # create the grid
    for t in steps:
        x = x0 + t * (x1 - x0)
        y = y0 + t * (y1 - y0)
        lines.append({"from": [x, y0], "to": [x, y1]})  # meridian
        lines.append({"from": [x0, y], "to": [x1, y]})  # parallel
    return lines


def grid_cells(
    lon: float,
    lat: float,
    radius_m: float,
    cell_m: float,
    heat: dict[tuple[int, int], float] | None = None,
) -> list[dict[str, object]]:
    """One polygon per grid cell, with its heat value keyed by (column, row), 0 if absent."""
    x0, y0, x1, y1 = (
        float(v) for v in bbox_around(lon, lat, radius_m).split(",")
    )
    side = 2 * radius_m
    steps = [
        i * cell_m / side for i in range(math.ceil(round(side / cell_m, 9)))
    ] + [1.0]
    # ~1 cm precision keeps the map payload small (one polygon per cell)
    xs = [round(x0 + t * (x1 - x0), 7) for t in steps]
    ys = [round(y0 + t * (y1 - y0), 7) for t in steps]
    heat = heat or {}
    return [
        {
            "polygon": [[xa, ya], [xb, ya], [xb, yb], [xa, yb]],
            "value": heat.get((i, j), 0),
        }
        for i, (xa, xb) in enumerate(zip(xs, xs[1:]))
        for j, (ya, yb) in enumerate(zip(ys, ys[1:]))
    ]


def local_to_lonlat(
    lon: float, lat: float, radius_m: float, x: float, y: float
) -> list[float]:
    """(x east, y north) in m from the south-west corner of the bbox around (lon, lat) -> [lon, lat]."""
    m_per_deg_lon = M_PER_DEG_LAT * math.cos(math.radians(lat))
    return [
        lon + (x - radius_m) / m_per_deg_lon,
        lat + (y - radius_m) / M_PER_DEG_LAT,
    ]
