"""Picture loading and encoding (cached: Streamlit reruns the script on every click)."""

import base64
from io import BytesIO

import streamlit as st
from PIL import Image

from panoloc.bbox import Item
from panoloc.frontend.drawing import (
    BOX_COLOR,
    MAX_DISPLAY_WIDTH,
    draw_annotations,
)

PANO_BOX_COLOR = (255, 140, 0)  # orange
PANO_MAX_WIDTH = 4096  # px; max texture width every GPU supports


@st.cache_data(max_entries=20, show_spinner=False)
def annotated(
    path: str,
    annotations: list[Item],
    max_width: int = MAX_DISPLAY_WIDTH,
    color: tuple[int, int, int] = BOX_COLOR,
    compact: bool = False,
) -> Image.Image:
    return draw_annotations(
        Image.open(path), annotations, max_width, color, compact
    )


def data_url(image: Image.Image) -> str:
    buf = BytesIO()
    image.save(buf, format="JPEG", quality=85)
    return (
        "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()
    )


@st.cache_data(max_entries=20, show_spinner=False)
def pano_data_url(path: str, annotations: list[Item]) -> str:
    boxed = annotated(
        path, annotations, PANO_MAX_WIDTH, PANO_BOX_COLOR, compact=True
    )
    return data_url(boxed)
