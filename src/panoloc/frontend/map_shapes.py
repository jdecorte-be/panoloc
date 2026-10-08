"""Map overlay shapes: search bbox outline, heatmap grid, direction segments, signs."""

import math
from collections.abc import Iterable

from panoloc.bbox import M_PER_DEG_LAT, bbox_around
from panoloc.deduplication import Cell, Sign
from panoloc.frontend.drawing import sign_label
from panoloc.frontend.signs import icon_key, icon_ratio, icon_url

SIGN_ICON_PX = 26  # the pictograms fit in a square of this side on the map
# longest side of a pictogram in deck.gl's texture: sharp on HiDPI screens
ICON_ATLAS_PX = 128


def offset(
    lon: float, lat: float, azimuth_deg: float, dist_m: float
) -> list[float]:
    """Point at dist_m from (lon, lat) toward an azimuth (0 = north, clockwise)."""
    a = math.radians(azimuth_deg)
    dlat = dist_m * math.cos(a) / M_PER_DEG_LAT
    dlon = dist_m * math.sin(a) / (M_PER_DEG_LAT * math.cos(math.radians(lat)))
    return [lon + dlon, lat + dlat]


def local_to_lonlat(
    lon: float, lat: float, radius_m: float, x: float, y: float
) -> list[float]:
    m_per_deg_lon = M_PER_DEG_LAT * math.cos(math.radians(lat))
    return [
        lon + (x - radius_m) / m_per_deg_lon,
        lat + (y - radius_m) / M_PER_DEG_LAT,
    ]


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
    keys: Iterable[Cell],
) -> dict[Cell, list[list[float]]]:
    """Polygon of the grid cells keyed by (column, row), only those asked for.

    A whole grid is millions of cells (1 km at 0.5 m: 4 M), almost all of them empty.
    """
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
    return {
        (i, j): [
            [xs[i], ys[j]],
            [xs[i + 1], ys[j]],
            [xs[i + 1], ys[j + 1]],
            [xs[i], ys[j + 1]],
        ]
        for i, j in keys
        if 0 <= i < len(xs) - 1 and 0 <= j < len(ys) - 1
    }


def sign_icon(sign_type: str) -> dict[str, object] | None:
    """deck.gl IconLayer icon of a sign type, None when there is no pictogram for it."""
    key = icon_key(sign_type)
    if key is None:
        return None
    ratio = icon_ratio(key)
    return {
        "id": key,
        "url": icon_url(key),
        "width": round(ICON_ATLAS_PX * min(ratio, 1)),
        "height": round(ICON_ATLAS_PX * min(1 / ratio, 1)),
    }


def sign_markers(
    signs: list[Sign], lon: float, lat: float, radius_m: float, current_id: str
) -> list[dict[str, object]]:
    """find_signs output -> one map point per sign, flagged when the current picture shows it."""
    markers = []
    for s in signs:
        icon = sign_icon(s.sign_type)
        markers.append(
            {
                "pos": local_to_lonlat(lon, lat, radius_m, s.x, s.y),
                "text": f"#{s.number}",
                "current": any(r.photo_id == current_id for r in s.rays),
                "icon": icon,
                # IconLayer sizes are heights: wide sub-panels (M...) get shorter
                "size": SIGN_ICON_PX * icon["height"] / ICON_ATLAS_PX
                if icon
                else 0,
                "info": f"{sign_label(s.number, s.sign_type)}\nseen in {len(s.rays)} pictures",
            }
        )
    return markers
