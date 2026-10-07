"""Annotation geometry and drawing: pixel shapes, labels, directions from the camera.

Pure helpers (no Streamlit inside, easy to test).
"""

import math
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from panoloc.bbox import Item
from panoloc.geo import signed_angle

MAX_DISPLAY_WIDTH = 2000  # px; HD pictures are downscaled before drawing
BOX_COLOR = (255, 40, 40)
PANO_FILL_ALPHA = 80  # 0 (clear) .. 255 (opaque)
PANO_LABEL_PX = 16


def shape_to_xy(shape: Any) -> list[tuple[float, float]]:
    """Annotation shape -> polygon vertices in pixels (origin = top-left corner)."""
    if isinstance(shape, list):  # bbox form: [minx, miny, maxx, maxy]
        x0, y0, x1, y1 = shape
        return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    ring = shape["coordinates"][
        0
    ]  # GeoJSON-like Polygon: first ring = outline
    return [(float(x), float(y)) for x, y in ring]


def draw_annotations(
    image: Image.Image,
    annotations: list[Item],
    max_width: int = MAX_DISPLAY_WIDTH,
    color: tuple[int, int, int] = BOX_COLOR,
    compact: bool = False,
) -> Image.Image:
    """Downscale the picture, then draw each annotation outline with its number.

    compact: translucent filled boxes, thin outlines and small numbers (for the
    360° view, where the boxes are small and seen up close).
    """
    scale = min(1.0, max_width / image.width)
    out = image.convert("RGBA").resize(
        (round(image.width * scale), round(image.height * scale))
    )
    overlay = Image.new("RGBA", out.size)  # drawn separately so alpha blends
    draw = ImageDraw.Draw(overlay)
    if compact:
        width, fill, outline = 2, (*color, PANO_FILL_ALPHA), (*color, 230)
        font_px = PANO_LABEL_PX
    else:  # line thickness and numbers grow with picture size
        width, fill, outline = max(2, out.width // 500), None, (*color, 255)
        font_px = max(14, out.width // 60)
    font = ImageFont.load_default(size=font_px)
    for n, annot in enumerate(annotations):
        pts = [(x * scale, y * scale) for x, y in shape_to_xy(annot["shape"])]
        draw.polygon(pts, fill=fill, outline=outline, width=width)
        x_min = min(x for x, _ in pts)
        y_min = min(y for _, y in pts)
        draw.text(
            (x_min, y_min - font_px - 4),
            annotation_label(n),
            fill=outline,
            font=font,
            stroke_width=1 if compact else 0,  # dark edge: readable on the sky
            stroke_fill=(0, 0, 0, 200),
        )
    return Image.alpha_composite(out, overlay).convert("RGB")


def annotation_label(i: int) -> str:
    """Number for the i-th annotation (0-based): 1, 2, ..."""
    return str(i + 1)


def annotation_heading(shape: Any, props: Item) -> float | None:
    """Compass bearing (0 = north, clockwise, -180 .. +180) from the camera to the annotation center.

    Assumes view:azimuth is the heading of the image's horizontal center.
    None if the picture lacks the azimuth, field of view or image width.
    """
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


def annotation_elevation(shape: Any, props: Item) -> float | None:
    """Angle above (+) or below (-) the horizon of the annotation center, in degrees.

    Assumes a level camera (no pitch/roll correction) and square pixels.
    None if the picture lacks the field of view or image size.
    """
    orientation: Item = props.get("pers:interior_orientation") or {}
    fov = orientation.get("field_of_view")
    dims = orientation.get("sensor_array_dimensions")
    if not fov or not dims:
        return None
    width, height = dims
    ys = [y for _, y in shape_to_xy(shape)]
    dy = height / 2 - (min(ys) + max(ys)) / 2  # pixels above the image center
    if fov >= 360:  # equirectangular: same degrees per pixel on both axes
        return dy * 360 / width
    focal_px = (width / 2) / math.tan(math.radians(fov / 2))
    return math.degrees(math.atan(dy / focal_px))


def tags_table(semantics: list[Item] | None) -> list[dict[str, str]]:
    """Semantics list -> rows for a table."""
    return [
        {"key": s["key"], "value": str(s["value"])} for s in semantics or []
    ]
