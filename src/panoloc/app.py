"""
Viewer: browse the Panoramax pictures around a target, their tags, and camera
headings on a map. Everything is read from the API; nothing is saved to disk.

Run from the repo root:  uv run streamlit run src/panoloc/app.py
"""

import base64
import math
import re
from io import BytesIO
from typing import Any

import pydeck as pdk
import streamlit as st
import streamlit.components.v2 as components_v2
from PIL import Image, ImageDraw, ImageFont

from panoloc.bbox import (
    M_PER_DEG_LAT,
    VIEWER,
    Item,
    PictureNotFound,
    bbox_around,
    nearby_pictures,
)

DEFAULT_URL = (
    "https://explore.panoramax.fr/fr/index?focus=map&map=15.12/48.589898/7.741354"
    "&pic=cfbce3b6-2904-41aa-9837-a3d2dffec6d5&seq=0fc301f5-a742-4405-8e6a-1c180a2121ff"
    "&speed=250&theme=default&users=default&xyz=66.88/-13.30/30"
)
MAX_DISPLAY_WIDTH = 2000  # px; HD pictures are downscaled before drawing
HEADING_LENGTH_M = 30  # length of the camera heading line on the map
BOX_COLOR = (255, 40, 40)
PANO_BOX_COLOR = (255, 140, 0)  # orange
PANO_FILL_ALPHA = 80  # 0 (clear) .. 255 (opaque)
PANO_LABEL_PX = 16
PANNELLUM = "https://cdnjs.cloudflare.com/ajax/libs/pannellum/2.5.6"
PANO_HEIGHT_PX = 450
PANO_MAX_WIDTH = 4096  # px; max texture width every GPU supports
INFO_COLOR = "#4fa8ff"  # light blue, readable on light and dark themes
MOVE_MAX_TARGETS = 8  # nearest pictures shown as clickable arrows in the 360° view
CAMERA_HEIGHT_M = 2.5  # used to place the arrows below the horizon
UUID_RE = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.IGNORECASE
)


# ---------- pure helpers (no Streamlit inside, easy to test) ----------


def shape_to_xy(shape: Any) -> list[tuple[float, float]]:
    """Annotation shape -> polygon vertices in pixels (origin = top-left corner)."""
    if isinstance(shape, list):  # bbox form: [minx, miny, maxx, maxy]
        x0, y0, x1, y1 = shape
        return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    ring = shape["coordinates"][0]  # GeoJSON-like Polygon: first ring = outline
    return [(float(x), float(y)) for x, y in ring]


def draw_annotations(
    image: Image.Image,
    annotations: list[Item],
    max_width: int = MAX_DISPLAY_WIDTH,
    color: tuple[int, int, int] = BOX_COLOR,
    compact: bool = False,
) -> Image.Image:
    """Downscale the picture, then draw each annotation outline with its letter.

    compact: translucent filled boxes, thin outlines and small letters (for the
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
    else:  # line thickness and letters grow with picture size
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
    """Letter for the i-th annotation (0-based): A..Z, then AA, AB, ..."""
    label = ""
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        label = chr(ord("A") + r) + label
    return label


def offset(lon: float, lat: float, azimuth_deg: float, dist_m: float) -> list[float]:
    """Point at dist_m from (lon, lat) toward an azimuth (0 = north, clockwise)."""
    a = math.radians(azimuth_deg)
    dlat = dist_m * math.cos(a) / M_PER_DEG_LAT
    dlon = dist_m * math.sin(a) / (M_PER_DEG_LAT * math.cos(math.radians(lat)))
    return [lon + dlon, lat + dlat]


def bearing_distance(
    lon: float, lat: float, lon2: float, lat2: float
) -> tuple[float, float]:
    """Compass bearing (0 = north, clockwise) and distance in m from one point to another."""
    dx = (lon2 - lon) * M_PER_DEG_LAT * math.cos(math.radians(lat))
    dy = (lat2 - lat) * M_PER_DEG_LAT
    return math.degrees(math.atan2(dx, dy)) % 360, math.hypot(dx, dy)


def move_targets(
    items: list[Item], current: Item, limit: int = MOVE_MAX_TARGETS
) -> list[Item]:
    """Nearest other pictures as Pannellum hotspots (yaw relative to the image center).

    Empty if the current picture has no azimuth: the arrows could not be oriented.
    """
    azimuth = current["properties"].get("view:azimuth")
    if azimuth is None:
        return []
    lon, lat = current["geometry"]["coordinates"]
    targets = []
    for idx, f in enumerate(items):
        if f["id"] == current["id"]:
            continue
        bearing, dist = bearing_distance(lon, lat, *f["geometry"]["coordinates"])
        if dist < 0.5:  # same spot: no meaningful direction
            continue
        targets.append(
            {
                "idx": idx,
                "yaw": (bearing - azimuth + 180) % 360 - 180,
                "pitch": -math.degrees(math.atan2(CAMERA_HEIGHT_M, dist)),
                "text": f"Move {dist:.0f} m",
                "dist": dist,
            }
        )
    return sorted(targets, key=lambda t: t["dist"])[:limit]


def bbox_ring(lon: float, lat: float, radius_m: float) -> list[list[float]]:
    """Search bbox around a point (same as bbox.bbox_around) -> closed polygon ring."""
    x0, y0, x1, y1 = (float(v) for v in bbox_around(lon, lat, radius_m).split(","))
    return [[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]]


def pic_id_from_url(text: str) -> str | None:
    """Picture id from a Panoramax URL (`pic=<uuid>`, often in the #fragment) or a bare id."""
    m = re.search(r"pic=(" + UUID_RE.pattern + ")", text, re.IGNORECASE)
    if m:
        return m.group(1)
    m = UUID_RE.search(text)
    return m.group(0) if m else None


def annotation_heading(shape: Any, props: Item) -> float | None:
    """Compass bearing (0 = north, clockwise) from the camera to the annotation center.

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
    u = (min(xs) + max(xs)) / 2 / dims[0] - 0.5  # -0.5 (left edge) .. 0.5 (right edge)
    if fov >= 360:  # equirectangular: angle is linear in x
        delta = u * 360
    else:  # pinhole camera: angle grows as atan of the distance from the center
        delta = math.degrees(math.atan(2 * u * math.tan(math.radians(fov / 2))))
    return (azimuth + delta) % 360


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
    return [{"key": s["key"], "value": str(s["value"])} for s in semantics or []]


# ---------- data loading (cached: Streamlit reruns the script on every click) ----------


@st.cache_data(max_entries=20, show_spinner=False)
def annotated(
    path: str,
    annotations: list[Item],
    max_width: int = MAX_DISPLAY_WIDTH,
    color: tuple[int, int, int] = BOX_COLOR,
    compact: bool = False,
) -> Image.Image:
    return draw_annotations(Image.open(path), annotations, max_width, color, compact)


def data_url(image: Image.Image) -> str:
    """JPEG data: URL, to hand a drawn-on picture to the browser-side viewer."""
    buf = BytesIO()
    image.save(buf, format="JPEG", quality=85)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


@st.cache_data(max_entries=20, show_spinner=False)
def pano_data_url(path: str, annotations: list[Item]) -> str:
    """The 360° texture: boxed, downscaled to PANO_MAX_WIDTH, JPEG-encoded."""
    boxed = annotated(path, annotations, PANO_MAX_WIDTH, PANO_BOX_COLOR, compact=True)
    return data_url(boxed)


# ---------- page ----------


def heading_map(items: list[Item], current: Item, bbox: list[list[float]]) -> pdk.Deck:
    """Search bbox, all camera positions of the sequence, and the current heading."""
    cameras = [
        {
            "pos": f["geometry"]["coordinates"],
            "current": f["id"] == current["id"],
        }
        for f in items
    ]
    lon, lat = current["geometry"]["coordinates"]
    layers = [
        pdk.Layer(
            "PolygonLayer",
            data=[{"polygon": bbox}],
            get_polygon="polygon",
            get_fill_color=[40, 120, 230, 25],
            get_line_color=[40, 120, 230],
            line_width_min_pixels=2,
        ),
        pdk.Layer(
            "ScatterplotLayer",
            id="cameras",
            data=cameras,
            pickable=True,  # click a camera to move there
            get_position="pos",
            get_radius="current ? 3 : 1.5",
            get_fill_color="current ? [230, 80, 40] : [120, 120, 120]",
            radius_min_pixels=4,
        ),
    ]
    azimuth = current["properties"].get("view:azimuth")
    if azimuth is not None:
        line = {
            "from": [lon, lat],
            "to": offset(lon, lat, azimuth, HEADING_LENGTH_M),
        }
        layers.append(
            pdk.Layer(
                "LineLayer",
                data=[line],
                get_source_position="from",
                get_target_position="to",
                get_color=[230, 80, 40],
                get_width=3,
            )
        )
    view = pdk.ViewState(longitude=lon, latitude=lat, zoom=17)
    return pdk.Deck(layers=layers, initial_view_state=view)


def panorama_config(image_url: str, props: Item, targets: list[Item]) -> Item:
    """Pannellum config: drag to look around, scroll to zoom, click an arrow to move.

    360° pictures wrap fully; flat pictures are shown over their field of view.
    """
    orientation: Item = props.get("pers:interior_orientation") or {}
    fov = orientation.get("field_of_view") or 360
    dims = orientation.get("sensor_array_dimensions")
    azimuth = props.get("view:azimuth")
    config: Item = {
        "type": "equirectangular",
        "panorama": image_url,
        "autoLoad": True,
        "showFullscreenCtrl": True,
        "hfov": 100,
        "hotSpots": [
            {"yaw": t["yaw"], "pitch": t["pitch"], "text": t["text"], "idx": t["idx"]}
            for t in targets
        ],
    }
    if azimuth is not None:  # compass: yaw 0 (image center) points to view:azimuth
        config |= {"northOffset": azimuth, "compass": True}
    if fov < 360 and dims:  # flat picture: map it on its own angular extent
        vaov = 2 * math.degrees(
            math.atan(dims[1] / dims[0] * math.tan(math.radians(fov / 2)))
        )
        config |= {"haov": fov, "vaov": vaov, "hfov": min(100, fov)}
    return config


PANO_CSS = f"""
.pl-pano {{ width: 100%; height: {PANO_HEIGHT_PX}px; }}
.pl-move {{
    width: 22px; height: 22px; border-radius: 50%; cursor: pointer;
    background: rgba(255, 255, 255, 0.85); border: 3px solid rgb(40, 120, 230);
}}
.pl-move:hover {{ background: rgb(40, 120, 230); }}
"""

# Pannellum runs in the app page (not an iframe) so a click can reach Python.
PANO_JS = f"""
function load(tag, attrs) {{
    if (document.querySelector(`${{tag}}[data-pannellum]`)) return window.__pannellumReady;
    const el = Object.assign(document.createElement(tag), attrs);
    el.dataset.pannellum = "";
    document.head.appendChild(el);
    return new Promise((ok) => (el.onload = ok));
}}

export default async function ({{ data, parentElement, setTriggerValue }}) {{
    load("link", {{ rel: "stylesheet", href: "{PANNELLUM}/pannellum.css" }});
    window.__pannellumReady = load("script", {{ src: "{PANNELLUM}/pannellum.js" }});
    await window.__pannellumReady;
    let box = parentElement.querySelector(".pl-pano");
    if (!box) {{
        box = Object.assign(document.createElement("div"), {{ className: "pl-pano" }});
        parentElement.appendChild(box);
    }}
    box.replaceChildren();
    for (const h of data.hotSpots) {{
        h.cssClass = "pl-move";
        h.createTooltipFunc = (div, text) => (div.title = text);
        h.createTooltipArgs = h.text;
        h.clickHandlerFunc = () => setTriggerValue("move", h.idx);
    }}
    const viewer = pannellum.viewer(box, data);
    return () => viewer.destroy();
}}
"""

panorama = components_v2.component(
    "panorama", css=PANO_CSS, js=PANO_JS, isolate_styles=False
)


def step(delta: int, n: int) -> None:
    st.session_state.idx = (st.session_state.idx + delta) % n


def move_from_map() -> None:
    """Map callback: jump to the clicked camera."""
    picked = st.session_state.map.selection["indices"].get("cameras") or []
    if picked:
        st.session_state.idx = picked[0]


def move_from_pano() -> None:
    """360° view callback: jump to the clicked arrow's picture."""
    st.session_state.idx = st.session_state.pano.move


def load_from_url() -> None:
    """Form callback: find the pictures around the pasted URL, then jump to it."""
    pic_id = pic_id_from_url(st.session_state.pano_url)
    if pic_id is None:
        st.session_state.url_error = "No picture id found in this URL."
        return
    radius = st.session_state.radius
    try:
        with st.spinner("Downloading pictures..."):
            pics = nearby_pictures(pic_id, radius)
    except PictureNotFound:
        st.session_state.url_error = f"Picture not found: {pic_id}"
        return
    except Exception as e:  # noqa: BLE001 - network error, ...
        st.session_state.url_error = f"Search failed: {e}"
        return
    ids = [pic["id"] for pic in pics]
    target = pics[ids.index(pic_id)]
    st.session_state.pics = pics
    st.session_state.idx = ids.index(pic_id)
    # the bbox is centered on the target: remember it to draw it on the map
    st.session_state.search = ([target["lon"], target["lat"]], radius)


def main() -> None:
    st.set_page_config(page_title="panoloc", layout="wide")

    with st.form("url_form", border=False):
        url_col, btn_col = st.columns([6, 1], vertical_alignment="bottom")
        url_col.text_input(
            "Panoramax URL",
            key="pano_url",
            value=DEFAULT_URL,
            placeholder="https://api.panoramax.xyz/#focus=pic&pic=...",
        )
        btn_col.form_submit_button("Load", on_click=load_from_url, width="stretch")
    if err := st.session_state.pop("url_error", None):
        st.error(err)

    # bbox parameter, used by the Load button (keyed: read in load_from_url)
    st.sidebar.markdown("**Search area**")
    st.sidebar.number_input(
        "Radius (m)", min_value=5, max_value=1000, value=10, step=5, key="radius"
    )
    st.sidebar.divider()

    pics: list[Item] = st.session_state.get("pics", [])
    if not pics:
        st.info("Paste a Panoramax picture URL above and press Load.")
        st.stop()
    items = [pic["item"] for pic in pics]
    n = len(pics)

    # navigation state survives reruns in st.session_state
    if "idx" not in st.session_state:
        st.session_state.idx = 0
    st.session_state.idx = min(st.session_state.idx, n - 1)  # sequence may have changed
    prev_col, next_col = st.sidebar.columns(2)
    prev_col.button("< prev", on_click=step, args=(-1, n), width="stretch")
    next_col.button("next >", on_click=step, args=(1, n), width="stretch")
    if n > 1:  # a slider needs min < max
        st.sidebar.slider("Picture", 0, n - 1, key="idx")

    pic = pics[st.session_state.idx]
    item: Item = pic["item"]
    props: Item = item["properties"]
    annotations: list[Item] = props.get("annotations") or []

    left, right = st.columns([3, 2])

    with left:
        try:
            with st.spinner("Loading picture..."):
                st.image(annotated(pic["jpg"], annotations), width="stretch")
        except Exception as e:  # noqa: BLE001 - shown in the page, not a crash
            st.warning(f"Could not load {pic['jpg']}: {e}")
        radius = st.session_state.search
        (lon, lat), radius = st.session_state.search
        st.pydeck_chart(
            heading_map(items, item, bbox_ring(lon, lat, radius)),
            on_select=move_from_map,
            key="map",
        )
        st.caption(
            "Click a camera dot to move there. "
            f"Orange line: camera heading (view:azimuth), {HEADING_LENGTH_M} m. "
            f"Blue box: search bbox, ±{radius} m around the target "
            f"({n} annotated pictures of its sequence inside)."
        )
        st.markdown(
            "**360° view** (drag to look around, scroll to zoom, "
            "click a blue dot to move there)"
        )
        try:
            with st.spinner("Loading 360° view..."):
                pano = pano_data_url(pic["jpg"], annotations)
            panorama(
                data=panorama_config(pano, props, move_targets(items, item)),
                key="pano",
                on_move_change=move_from_pano,
            )
        except Exception as e:  # noqa: BLE001 - shown in the page, not a crash
            st.warning(f"Could not load {pic['jpg']}: {e}")

    with right:
        st.link_button("Open in Panoramax", f"{VIEWER}?pic={item['id']}")

        st.markdown("**Camera**")
        st.table(
            [
                {"field": k, "value": str(props.get(k))}
                for k in (
                    "datetime",
                    "view:azimuth",
                    "quality:horizontal_accuracy",
                )
            ]
        )
        st.json(props.get("pers:interior_orientation") or {}, expanded=False)

        st.markdown(f"**Annotations ({len(annotations)})**")
        for i, annot in enumerate(annotations):
            heading = annotation_heading(annot["shape"], props)
            elevation = annotation_elevation(annot["shape"], props)
            info = (
                f"{annotation_label(i)} — heading from camera: "
                + ("unknown" if heading is None else f"{heading:.0f}°")
                + ", elevation: "
                + ("unknown" if elevation is None else f"{elevation:+.1f}°")
            )
            st.html(f'<span style="color: {INFO_COLOR}">{info}</span>')
            st.table(tags_table(annot.get("semantics")))

        with st.expander("Raw JSON"):
            st.json(item)


if __name__ == "__main__":
    main()
