"""Turn the ray voting groups into map data: cell colors, hover text and the voting rays.

Pure helpers (no Streamlit inside, easy to test).
"""

import math
from collections import defaultdict

from panoloc.deduplication import Cell, Group, Ray, group_label
from panoloc.geo import local_to_lonlat

ALL = "All groups (sum)"
WINNER = "Winning group per cell"
ONE = "One group"
VIEWS = (ALL, WINNER, ONE)
MAX_TOOLTIP_GROUPS = 8

# one color per group, cycled when there are more groups than colors
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


def ray_length(r, side):
    dx = math.sin(math.radians(r.bearing))
    dy = math.cos(math.radians(r.bearing))
    ts = []
    for p, d in ((r.x, dx), (r.y, dy)):
        if d > 1e-12:
            ts.append((side - p) / d)
        elif d < -1e-12:
            ts.append(-p / d)
    return max(0.0, min(ts, default=0.0))


def group_colors(keys: list[Group]) -> dict[Group, tuple[int, int, int]]:
    return {key: PALETTE[i % len(PALETTE)] for i, key in enumerate(keys)}


def sorted_groups(groups: dict[Group, list[Ray]]) -> list[Group]:
    """Groups with the most rays first."""
    return sorted(groups, key=lambda k: (-len(groups[k]), k))


def vote_cells(
    cells: list[dict[str, object]],
    heats: dict[Group, dict[Cell, float]],
    colors: dict[Group, tuple[int, int, int]],
    view: str,
    selected: Group | None = None,
) -> list[dict[str, object]]:
    """Fill grid_cells (no heat yet) with the value, color and hover text of the chosen view.

    cells must come from geo.grid_cells, in its (column, row) order.
    """
    n = round(len(cells) ** 0.5)
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

    out = []
    for k, cell in enumerate(cells):
        votes = per_cell.get((k // n, k % n), {})
        if view == WINNER and votes:
            winner = max(votes, key=votes.__getitem__)
            value, rgb = votes[winner], colors[winner]
        else:
            winner, value, rgb = None, sum(votes.values()), None
        ranked = sorted(votes.items(), key=lambda kv: -kv[1])
        info = "<br>".join(
            f"{group_label(g)}: {v:.1f}"
            for g, v in ranked[:MAX_TOOLTIP_GROUPS]
        )
        if len(ranked) > MAX_TOOLTIP_GROUPS:
            info += f"<br>+{len(ranked) - MAX_TOOLTIP_GROUPS} more"
        out.append(
            {**cell, "value": value, "rgb": rgb, "info": info or "no vote"}
        )
    return out


def ray_lines(
    groups: dict[Group, list[Ray]],
    colors: dict[Group, tuple[int, int, int]],
    lon: float,
    lat: float,
    radius_m: float,
    only: Group | None = None,
) -> list[dict[str, object]]:
    """One line per voting ray, from its camera to where it leaves the bbox."""
    side = 2 * radius_m
    lines = []
    for key, rays in groups.items():
        if only is not None and key != only:
            continue
        for r in rays:
            d = ray_length(r, side)
            a = math.radians(r.bearing)
            end = (r.x + d * math.sin(a), r.y + d * math.cos(a))
            lines.append(
                {
                    "from": local_to_lonlat(lon, lat, radius_m, r.x, r.y),
                    "to": local_to_lonlat(lon, lat, radius_m, *end),
                    "color": [*colors[key], 160],
                    "info": f"{group_label(key)}<br>bearing {r.bearing:.0f}°",
                }
            )
    return lines
