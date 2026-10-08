import base64
import html
import json
import re
from functools import cache
from pathlib import Path

# official pictograms (Wikimedia Commons SVGs, see SOURCES.csv there), copied from
# panoview: https://gitlab.com/mw014/panoview/-/tree/main/web/signs
ICONS_DIR = Path(__file__).parent / "assets" / "signs"
# split a traffic_sign value, but not inside brackets ("D21[A, B]")
SEGMENT_SEP = re.compile(r"[;,](?![^\[]*\])")
PREFIX = re.compile(r"^\s*[A-Z]{1,3}:")
SVG_TAG = re.compile(r"<svg\b[^>]*>", re.DOTALL)

SIGN_NAMES = {
    # danger
    "A13b": "Pedestrian crossing ahead",
    # intersection and priority
    "AB3": "Give way",
    "AB3a": "Give way",
    "AB4": "Stop",
    "AB6": "Priority road",
    # prohibition
    "B0": "Closed to all vehicles",
    "B1": "No entry",
    "B2a": "No left turn",
    "B3": "No overtaking",
    "B6a1": "No parking",
    "B6d": "No stopping or parking",
    "B14": "Speed limit",
    # obligation
    "B21a1": "Keep right",
    "B21a2": "Keep left",
    "B22a": "Mandatory cycle lane",
    "B27a": "Bus lane",
    # services
    "CE14": "Accessible to disabled people",
    # sub-panels (panonceaux)
    "M6h": "Disabled parking only",
    "M6i": "EV charging only",
    "M9v": "Except cyclists",
    "M9v1": "Except cyclists",
    "M12d": "Cyclists may turn right on red",
    "M12f": "Cyclists may go straight on red",
    "M12g": "Cyclists may turn left on red",
    "M12fd": "Cyclists may go straight or right on red",
    "M12gf": "Cyclists may go left or straight on red",
    "M12gd": "Cyclists may turn left or right on red",
    "M12gfd": "Cyclists may go any way on red",
}


@cache
def manifest() -> dict[str, str]:
    """Icon key -> French name of the sign, one key per file of ICONS_DIR."""
    return json.loads((ICONS_DIR / "manifest.json").read_text())


def icon_key(traffic_sign: str) -> str | None:
    """Pictogram of a sign: "FR:B14[50]" -> "B14[50]", else its bare code "B14".

    None when there is no pictogram for it.

    Only the first code of a composite value ("FR:B0,M9v2") is looked up.
    """
    first = SEGMENT_SEP.split(traffic_sign.upper())[0]
    exact = PREFIX.sub("", first).strip()
    for key in (exact, exact.partition("[")[0]):
        if key in manifest():
            return key
    return None


@cache
def icon_url(key: str) -> str:
    """data URL of a pictogram: Streamlit's static serving sends SVGs as text/plain."""
    svg = (ICONS_DIR / f"{key}.svg").read_bytes()
    return "data:image/svg+xml;base64," + base64.b64encode(svg).decode()


def _length(attrs: str, name: str) -> float | None:
    """Value of a width or height attribute, None when missing or relative ("100%")."""
    m = re.search(
        rf'(?<![\w:-]){name}="\s*([\d.]+)\s*(px|pt|mm|cm|in)?\s*"', attrs
    )
    return float(m.group(1)) if m else None


@cache
def icon_ratio(key: str) -> float:
    """Width / height of a pictogram: sub-panels (M...) are wide, posts (J...) narrow."""
    attrs = SVG_TAG.search((ICONS_DIR / f"{key}.svg").read_text()).group(0)
    width, height = _length(attrs, "width"), _length(attrs, "height")
    if not (width and height):
        view_box = re.search(r'viewBox="([^"]+)"', attrs)
        if view_box is None:
            return 1.0
        width, height = map(
            float, re.split(r"[\s,]+", view_box.group(1).strip())[2:4]
        )
    return width / height


def icon_img(traffic_sign: str, height_px: int) -> str:
    """<img> of the pictogram of a sign, its French name on hover, empty when there is none."""
    key = icon_key(traffic_sign)
    if key is None:
        return ""
    return (
        f'<img src="{icon_url(key)}" title="{html.escape(manifest()[key])}" alt="{key}"'
        f' style="height: {height_px}px; vertical-align: middle; margin-right: 4px">'
    )


def sign_name(traffic_sign):
    """English name when known, else the French one of the pictograms, then the codes."""
    codes = [c.removeprefix("FR:") for c in traffic_sign.split(";")]
    names = [
        SIGN_NAMES.get(c.partition("[")[0])
        or manifest().get(icon_key(c) or "")
        for c in codes
    ]
    if not any(names):
        return traffic_sign
    return f"{' + '.join(n or c for n, c in zip(names, codes))} ({';'.join(codes)})"
