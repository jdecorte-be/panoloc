import base64
import colorsys
import math
from collections import defaultdict
from io import BytesIO

from PIL import Image

from panoloc.bbox import bbox_around
from panoloc.deduplication import Cell, Group, Ray
from panoloc.frontend.heading_map import heat_rgba
from panoloc.frontend.map_shapes import grid_cells, local_to_lonlat
from panoloc.frontend.signs import sign_name

ALL = "All groups (sum)"
WINNER = "Winning group per cell"
ONE = "One group"
VIEWS = (ALL, WINNER, ONE)
MAX_TOOLTIP_GROUPS = 8
# above this many cells with a vote, the map shows them as an image (see vote_image)
MAX_HOVER_CELLS = 50_000
MAX_IMAGE_PX = 4096  # longest side of that image: past it, cells share a pixel
SECTORS = "NESW"  # see group_rays

# one color per group when there are few groups, see group_colors
PALETTE = [
    (31, 119, 180),
    (255, 127, 14),
    (44, 160, 44),
    (214, 39, 40),
    (148, 103, 189),
    (140, 86, 75),
    (227, 119, 194),
    (23, 190, 207),
    (188, 189, 34),
    (127, 127, 127),
]


def group_label(key: Group) -> str:
    sign_type, sector = key
    return f"{sign_name(sign_type)}, driving {SECTORS[sector]}"


def ray_length(r, side, max_m):
    dx = math.sin(math.radians(r.bearing))
    dy = math.cos(math.radians(r.bearing))
    ts = []
    for p, d in ((r.x, dx), (r.y, dy)):
        if d > 1e-12:
            ts.append((side - max(r.size, p)) / d)
        elif d < -1e-12:
            ts.append(-min(r.size, p) / d)
    return max(0.0, min(ts + [max_m]))


def distinct_color(i: int) -> tuple[int, int, int]:
    hue = (i * 0.618033988749895) % 1
    sat = (0.85, 0.55, 0.95)[i % 3]
    val = (0.9, 0.65, 0.75, 0.5)[i % 4]
    r, g, b = colorsys.hsv_to_rgb(hue, sat, val)

    return round(r * 255), round(g * 255), round(b * 255)


def group_colors(keys: list[Group]) -> dict[Group, tuple[int, int, int]]:
    """A different color for every group."""
    if len(keys) <= len(PALETTE):
        return dict(zip(keys, PALETTE))
    return {key: distinct_color(i) for i, key in enumerate(keys)}


def sorted_groups(groups: dict[Group, list[Ray]]) -> list[Group]:
    """Groups with the most rays first."""
    return sorted(groups, key=lambda k: (-len(groups[k]), k))


def voted_cells(
    heats: dict[Group, dict[Cell, float]],
    view: str,
    selected: Group | None = None,
) -> dict[Cell, dict[Group, float]]:
    """The groups voting for each cell in the chosen view, only the cells with a vote."""
    shown = (
        {selected: heats.get(selected, {})}
        if view == ONE and selected
        else heats
    )
    per_cell: dict[Cell, dict[Group, float]] = defaultdict(dict)
    for key, heat in shown.items():
        for c, v in heat.items():
            if v > 0:
                per_cell[c][key] = v
    return per_cell


def cell_value(
    votes: dict[Group, float],
    colors: dict[Group, tuple[int, int, int]],
    view: str,
) -> tuple[float, tuple[int, int, int] | None]:
    """Value of a cell, and its group's color in the winner view (None: heat colors)."""
    if view == WINNER:
        winner = max(votes, key=votes.__getitem__)
        return votes[winner], colors[winner]
    return sum(votes.values()), None


def vote_cells(
    lon: float,
    lat: float,
    radius_m: float,
    cell_m: float,
    per_cell: dict[Cell, dict[Group, float]],
    colors: dict[Group, tuple[int, int, int]],
    view: str,
) -> list[dict[str, object]]:
    """voted_cells as map polygons, with their value, color and hover text.

    The cells without a vote are left out: they would be transparent on the map.
    """
    polygons = grid_cells(lon, lat, radius_m, cell_m, per_cell)
    out = []
    for c, polygon in polygons.items():
        votes = per_cell[c]
        value, rgb = cell_value(votes, colors, view)
        ranked = sorted(votes.items(), key=lambda kv: -kv[1])
        info = "\n".join(
            f"{group_label(g)}: {v:.1f}"
            for g, v in ranked[:MAX_TOOLTIP_GROUPS]
        )
        if len(ranked) > MAX_TOOLTIP_GROUPS:
            info += f"\n+{len(ranked) - MAX_TOOLTIP_GROUPS} more"
        out.append(
            {"polygon": polygon, "value": value, "rgb": rgb, "info": info}
        )
    return out


def vote_image(
    lon: float,
    lat: float,
    radius_m: float,
    cell_m: float,
    per_cell: dict[Cell, dict[Group, float]],
    colors: dict[Group, tuple[int, int, int]],
    view: str,
) -> dict[str, object]:
    """voted_cells drawn as one PNG, one pixel per cell, with its lon/lat bounds.

    For big searches: hundreds of thousands of polygons are too heavy for the map,
    an image of the same colors is a few MB. No hover text per cell.
    """
    side = 2 * radius_m
    n = math.ceil(round(side / cell_m, 9))  # cells per side, as in grid_cells
    scale = math.ceil(n / MAX_IMAGE_PX)  # cells per pixel side
    size = math.ceil(n / scale)
    # a pixel shared by several cells shows the strongest one
    best: dict[Cell, tuple[float, tuple[int, int, int] | None]] = {}
    for (i, j), votes in per_cell.items():
        if not (0 <= i < n and 0 <= j < n):  # blurred out of the grid
            continue
        value, rgb = cell_value(votes, colors, view)
        px = (i // scale, j // scale)
        if px not in best or value > best[px][0]:
            best[px] = (value, rgb)
    vmax = max((value for value, _ in best.values()), default=0)
    pixels = bytearray(size * size * 4)  # transparent
    for (pi, pj), (value, rgb) in best.items():
        k = ((size - 1 - pj) * size + pi) * 4  # row 0 is the north edge
        pixels[k : k + 4] = bytes(heat_rgba(value, vmax, rgb))
    png = BytesIO()
    Image.frombytes("RGBA", (size, size), bytes(pixels)).save(
        png, "PNG", compress_level=1
    )
    x0, y0, x1, y1 = (
        float(v) for v in bbox_around(lon, lat, radius_m).split(",")
    )
    # whole cells: the last ones can stick out of the bbox by less than a cell
    covered = size * scale * cell_m / side
    return {
        "image": "data:image/png;base64,"
        + base64.b64encode(png.getvalue()).decode(),
        "bounds": [
            x0,
            y0,
            x0 + covered * (x1 - x0),
            y0 + covered * (y1 - y0),
        ],
    }


def ray_lines(
    groups: dict[Group, list[Ray]],
    colors: dict[Group, tuple[int, int, int]],
    lon: float,
    lat: float,
    radius_m: float,
    max_m: float,
    only: Group | None = None,
) -> list[dict[str, object]]:
    """One line per voting ray, from its camera to max_m or where it leaves the bbox."""
    side = 2 * radius_m
    lines = []
    for key, rays in groups.items():
        if only is not None and key != only:
            continue
        for r in rays:
            d = ray_length(r, side, max_m)
            a = math.radians(r.bearing)
            end = (r.x + d * math.sin(a), r.y + d * math.cos(a))
            lines.append(
                {
                    "from": local_to_lonlat(lon, lat, radius_m, r.x, r.y),
                    "to": local_to_lonlat(lon, lat, radius_m, *end),
                    "color": [*colors[key], 160],
                    "info": f"{group_label(key)}\nbearing {r.bearing:.0f}°, travel {r.azimuth:.0f}°",
                }
            )
    return lines
