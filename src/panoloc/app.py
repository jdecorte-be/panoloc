"""
Local viewer: browse downloaded pictures, their tags, and camera headings on a map.

Run from the repo root:  uv run streamlit run src/app.py
"""

import json
import math
from pathlib import Path
from typing import Any

import pydeck as pdk
import streamlit as st
from PIL import Image, ImageDraw, ImageFont

from panoloc.fetch import DATA_DIR, M_PER_DEG_LAT, VIEWER, Item

MAX_DISPLAY_WIDTH = 2000  # px; HD pictures are downscaled before drawing
HEADING_LENGTH_M = 30  # length of the camera heading line on the map
BOX_COLOR = (255, 40, 40)


# ---------- pure helpers (no Streamlit inside, easy to test) ----------


def shape_to_xy(shape: Any) -> list[tuple[float, float]]:
    """Annotation shape -> polygon vertices in pixels (origin = top-left corner)."""
    if isinstance(shape, list):  # bbox form: [minx, miny, maxx, maxy]
        x0, y0, x1, y1 = shape
        return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    ring = shape["coordinates"][0]  # GeoJSON-like Polygon: first ring = outline
    return [(float(x), float(y)) for x, y in ring]


def draw_annotations(image: Image.Image, annotations: list[Item]) -> Image.Image:
    """Downscale the picture, then draw each annotation outline with its number."""
    scale = min(1.0, MAX_DISPLAY_WIDTH / image.width)
    out = image.convert("RGB").resize(
        (round(image.width * scale), round(image.height * scale))
    )
    draw = ImageDraw.Draw(out)
    width = max(2, out.width // 500)  # line thickness grows with picture size
    font = ImageFont.load_default(size=max(14, out.width // 60))
    for n, annot in enumerate(annotations, start=1):
        pts = [(x * scale, y * scale) for x, y in shape_to_xy(annot["shape"])]
        draw.polygon(pts, outline=BOX_COLOR, width=width)
        x_min = min(x for x, _ in pts)
        y_min = min(y for _, y in pts)
        draw.text((x_min, y_min - font.size - 4), str(n), fill=BOX_COLOR, font=font)
    return out


def offset(lon: float, lat: float, azimuth_deg: float, dist_m: float) -> list[float]:
    """Point at dist_m from (lon, lat) toward an azimuth (0 = north, clockwise)."""
    a = math.radians(azimuth_deg)
    dlat = dist_m * math.cos(a) / M_PER_DEG_LAT
    dlon = dist_m * math.sin(a) / (M_PER_DEG_LAT * math.cos(math.radians(lat)))
    return [lon + dlon, lat + dlat]


def tags_table(semantics: list[Item] | None) -> list[dict[str, str]]:
    """Semantics list -> rows for a table."""
    return [{"key": s["key"], "value": str(s["value"])} for s in semantics or []]


# ---------- data loading (cached: Streamlit reruns the script on every click) ----------


@st.cache_data
def load_sequence(seq_dir: str) -> list[tuple[str, Item]]:
    """(image path, metadata) for each picture, in capture order (rank-prefixed names)."""
    pairs: list[tuple[str, Item]] = []
    for meta in sorted(Path(seq_dir).glob("*.json")):
        pairs.append((str(meta.with_suffix(".jpg")), json.loads(meta.read_text())))
    return pairs


@st.cache_data
def annotated(image_path: str, annotations: list[Item]) -> Image.Image:
    return draw_annotations(Image.open(image_path), annotations)


# ---------- page ----------


def heading_map(items: list[Item], current: Item) -> pdk.Deck:
    """All camera positions of the sequence, plus the current camera heading."""
    cameras = [
        {
            "pos": f["geometry"]["coordinates"],
            "rank": f["properties"].get("geovisio:rank_in_collection"),
            "current": f["id"] == current["id"],
        }
        for f in items
    ]
    lon, lat = current["geometry"]["coordinates"]
    layers = [
        pdk.Layer(
            "ScatterplotLayer",
            data=cameras,
            get_position="pos",
            get_radius="current ? 3 : 1.5",
            get_fill_color="current ? [230, 80, 40] : [120, 120, 120]",
            radius_min_pixels=4,
            pickable=True,
        )
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
    view = pdk.ViewState(longitude=lon, latitude=lat, zoom=18)
    return pdk.Deck(
        layers=layers, initial_view_state=view, tooltip={"text": "rank {rank}"}
    )


def step(delta: int, n: int) -> None:
    st.session_state.idx = (st.session_state.idx + delta) % n


def main() -> None:
    st.set_page_config(page_title="panoloc", layout="wide")

    seq_dirs = sorted(p for p in DATA_DIR.glob("*") if p.is_dir())
    if not seq_dirs:
        st.info(
            f"No data in {DATA_DIR}/. Run first: uv run python -m panoloc.fetch <pic_id>"
        )
        st.stop()

    seq_dir = st.sidebar.selectbox(
        "Sequence", seq_dirs, format_func=lambda p: p.name[:8]
    )
    pairs = load_sequence(str(seq_dir))
    items = [item for _, item in pairs]
    n = len(pairs)

    # navigation state survives reruns in st.session_state
    if "idx" not in st.session_state:
        st.session_state.idx = 0
    st.session_state.idx = min(st.session_state.idx, n - 1)  # sequence may have changed
    prev_col, next_col = st.sidebar.columns(2)
    prev_col.button("< prev", on_click=step, args=(-1, n), width="stretch")
    next_col.button("next >", on_click=step, args=(1, n), width="stretch")
    if n > 1:  # a slider needs min < max
        st.sidebar.slider("Picture", 0, n - 1, key="idx")

    image_path, item = pairs[st.session_state.idx]
    props: Item = item["properties"]
    annotations: list[Item] = props.get("annotations") or []

    left, right = st.columns([3, 2])

    with left:
        if Path(image_path).exists():
            st.image(annotated(image_path, annotations), width="stretch")
        else:
            st.warning(f"Image missing: {image_path}")
        st.pydeck_chart(heading_map(items, item))
        st.caption(f"Orange line: camera heading (view:azimuth), {HEADING_LENGTH_M} m.")

    with right:
        st.subheader(f"rank {props.get('geovisio:rank_in_collection')}")
        st.link_button("Open in Panoramax", f"{VIEWER}?pic={item['id']}")

        st.markdown("**Camera**")
        st.table(
            [
                {"field": k, "value": str(props.get(k))}
                for k in (
                    "datetime",
                    "view:azimuth",
                    "pers:yaw",
                    "pers:pitch",
                    "pers:roll",
                    "quality:horizontal_accuracy",
                )
            ]
        )
        st.json(props.get("pers:interior_orientation") or {}, expanded=False)

        st.markdown("**Picture tags**")
        st.table(tags_table(props.get("semantics")) or [{"key": "-", "value": "-"}])

        st.markdown(f"**Annotations ({len(annotations)})**")
        for i, annot in enumerate(annotations, start=1):
            st.caption(f"#{i}")
            st.table(tags_table(annot.get("semantics")))

        with st.expander("Raw JSON"):
            st.json(item)


main()
