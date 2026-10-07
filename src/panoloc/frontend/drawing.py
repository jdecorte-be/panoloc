"""Annotation drawing and display helpers: outlines on pictures, labels, tag tables."""

from PIL import Image, ImageDraw, ImageFont

from panoloc.annotations import shape_to_xy
from panoloc.bbox import Item

MAX_DISPLAY_WIDTH = 2000  # px; HD pictures are downscaled before drawing
BOX_COLOR = (255, 40, 40)
PANO_FILL_ALPHA = 80  # 0 (clear) .. 255 (opaque)
PANO_LABEL_PX = 16


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


def tags_table(semantics: list[Item] | None) -> list[dict[str, str]]:
    """Semantics list -> rows for a table."""
    return [
        {"key": s["key"], "value": str(s["value"])} for s in semantics or []
    ]
