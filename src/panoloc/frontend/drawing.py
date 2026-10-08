"""Annotation drawing and display helpers: outlines on pictures, labels, tag tables."""

import math
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from panoloc.annotations import shape_to_xy
from panoloc.bbox import Item
from panoloc.frontend.signs import sign_name

MAX_DISPLAY_WIDTH = 2000  # px; HD pictures are downscaled before drawing
BOX_COLOR = (255, 40, 40)
PANO_FILL_ALPHA = 80  # 0 (clear) .. 255 (opaque)
PANO_LABEL_PX = 16
PANO_LABEL_COLOR = (135, 206, 250)  # light blue


def draw_annotations(
    image: Image.Image,
    annotations: list[Item],
    labels: tuple[str, ...],
    below: tuple[str, ...] = (),
    max_width: int = MAX_DISPLAY_WIDTH,
    color: tuple[int, int, int] = BOX_COLOR,
    compact: bool = False,
) -> Image.Image:
    """Downscale the picture, then draw each annotation outline with its label above
    and its below text (if any) under it.

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
        font_px, text_fill = PANO_LABEL_PX, (*PANO_LABEL_COLOR, 255)
    else:  # line thickness and numbers grow with picture size
        width, fill, outline = max(2, out.width // 500), None, (*color, 255)
        font_px, text_fill = max(14, out.width // 60), outline
    font = ImageFont.load_default(size=font_px)
    for i, (annot, label) in enumerate(zip(annotations, labels)):
        pts = [(x * scale, y * scale) for x, y in shape_to_xy(annot["shape"])]
        draw.polygon(pts, fill=fill, outline=outline, width=width)
        x_min = min(x for x, _ in pts)
        y_min = min(y for _, y in pts)
        y_max = max(y for _, y in pts)
        texts = [((x_min, y_min - font_px - 4), label)]
        if i < len(below) and below[i]:
            texts.append(((x_min, y_max + 4), below[i]))
        for xy, text in texts:
            draw.text(
                xy,
                text,
                fill=text_fill,
                font=font,
                stroke_width=1
                if compact
                else 0,  # dark edge: readable on the sky
                stroke_fill=(0, 0, 0, 200),
            )
    return Image.alpha_composite(out, overlay).convert("RGB")


def annotation_elevation(shape: Any, props: Item) -> float | None:
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


def sign_label(number: int | None, sign_type: str | None) -> str:
    """#n: the same sign in every picture. ?: not located (seen too few times, or untyped).

    Followed by the sign type when the annotation has one.
    """
    tag = "?" if number is None else f"#{number}"
    return tag if sign_type is None else f"{tag} {sign_name(sign_type)}"


def box_label(signs: list[tuple[int | None, str]]) -> str:
    """[(number, sign type)] of one box -> one sign_label per sign, "?" for an untyped box."""
    return " + ".join(sign_label(n, t) for n, t in signs) or sign_label(
        None, None
    )


def distance_label(dist_m: float | None) -> str:
    """How far the sign is from the camera, empty when it is not located."""
    return "" if dist_m is None else f"{dist_m:.0f} m"


def sign_numbers(signs):
    """(annotation id, sign type) -> number of the sign: a box can show several signs."""
    return {
        (r.annotation_id, s.sign_type): s.number
        for s in signs
        for r in s.rays
        if r.annotation_id
    }


def sign_distances(signs):
    """annotation id -> meters from the camera to the sign it shows.

    A box showing several signs gets the distance of its most seen one: they are on
    the same post.
    """
    distances = {}
    for s in signs:  # most seen first
        for r in s.rays:
            if r.annotation_id:
                distances.setdefault(
                    r.annotation_id, math.hypot(s.x - r.x, s.y - r.y)
                )
    return distances


def tags_table(semantics: list[Item] | None) -> list[dict[str, str]]:
    """Semantics list -> rows for a table."""
    return [
        {"key": s["key"], "value": str(s["value"])} for s in semantics or []
    ]
