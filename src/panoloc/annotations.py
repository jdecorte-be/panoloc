import math
from typing import Any

from panoloc.bbox import Item
from panoloc.geo import signed_angle


def shape_to_xy(shape: Any) -> list[tuple[float, float]]:
    if isinstance(shape, list):  # bbox form: [minx, miny, maxx, maxy]
        x0, y0, x1, y1 = shape
        return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]

    ring = shape["coordinates"][
        0
    ]  # GeoJSON-like Polygon: first ring = outline
    return [(float(x), float(y)) for x, y in ring]


def annotation_heading(shape: Any, props: Item) -> float | None:
    orientation: Item = props.get("pers:interior_orientation") or {}
    azimuth = props.get("view:azimuth")
    fov = orientation.get("field_of_view")
    dims = orientation.get("sensor_array_dimensions")

    if azimuth is None or not fov or not dims:
        return None

    xs = [x for x, _ in shape_to_xy(shape)]
    u = (min(xs) + max(xs)) / 2 / dims[
        0
    ] - 0.5  # -0.5 (left edge) .. 0.5 (right edge)
    if fov >= 360:  # equirectangular: angle is linear in x
        delta = u * 360
    else:  # pinhole camera: angle grows as atan of the distance from the center
        delta = math.degrees(
            math.atan(2 * u * math.tan(math.radians(fov / 2)))
        )

    return signed_angle(azimuth + delta)


def annotation_width(shape: Any, props: Item) -> float | None:
    """How wide the annotation looks from the camera, in degrees."""
    orientation: Item = props.get("pers:interior_orientation") or {}
    fov = orientation.get("field_of_view")
    dims = orientation.get("sensor_array_dimensions")

    if not fov or not dims:
        return None

    xs = [x for x, _ in shape_to_xy(shape)]
    if fov >= 360:  # equirectangular: angle is linear in x
        return (max(xs) - min(xs)) / dims[0] * 360

    def angle(x: float) -> float:  # pinhole camera, as in annotation_heading
        u = x / dims[0] - 0.5
        return math.degrees(math.atan(2 * u * math.tan(math.radians(fov / 2))))

    return angle(max(xs)) - angle(min(xs))
