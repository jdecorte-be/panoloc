import re

import streamlit as st

from panoloc.annotations import annotation_heading
from panoloc.bbox import Item, PictureNotFound, nearby_pictures
from panoloc.deduplication import (
    Cell,
    Group,
    Ray,
    Sign,
    find_signs,
    ray_groups,
    sign_types_of,
    the_ray_voting_algorithm,
)
from panoloc.frontend.drawing import (
    annotation_elevation,
    box_label,
    distance_label,
    sign_distances,
    sign_numbers,
    tags_table,
)
from panoloc.frontend.heading_map import heading_map
from panoloc.frontend.images import pano_data_url
from panoloc.frontend.map_shapes import (
    bbox_ring,
    grid_lines,
    sign_markers,
)
from panoloc.frontend.panorama import move_targets, panorama, panorama_config
from panoloc.frontend.settings import load as load_sidebar
from panoloc.frontend.settings import save as save_sidebar
from panoloc.frontend.signs import icon_img
from panoloc.frontend.votes import (
    MAX_HOVER_CELLS,
    ONE,
    VIEWS,
    WINNER,
    group_colors,
    group_label,
    ray_lines,
    sorted_groups,
    vote_cells,
    vote_image,
    voted_cells,
)

DEFAULT_URL = (
    "https://explore.panoramax.fr/fr/index?focus=map&map=15.12/48.589898/7.741354"
    "&pic=cfbce3b6-2904-41aa-9837-a3d2dffec6d5&seq=0fc301f5-a742-4405-8e6a-1c180a2121ff"
    "&speed=250&theme=default&users=default&xyz=66.88/-13.30/30"
)
VIEWER = "https://api.panoramax.xyz/"
INFO_COLOR = "#4fa8ff"  # light blue, readable on light and dark themes
# sidebar options (widget key -> default), saved to the cache dir on every change
SIDEBAR = {
    "radius": 50,
    "download": False,
    "cell": 0.5,
    "max_dist": 45,
    "view": WINNER,
    "show_numbers": False,
    "show_rays": False,
    "show_signs": True,
    "full_map": False,
    "show_pano": True,
}
MAP_HEIGHT_PX = 500
FULL_MAP_HEIGHT_PX = 800
# Streamlit's own fullscreen button of the map (hidden until hover, above it):
# always shown, at the bottom-left corner of the map
MAP_FULLSCREEN_CSS = """<style>
.st-key-map [data-testid="stElementToolbar"] {
    top: auto !important;
    right: auto !important;
    bottom: 8px;
    left: 8px;
    padding: 0;
    opacity: 1 !important;
    z-index: 10; /* above deck.gl's view, drawn after it */
    background: rgba(255, 255, 255, 0.85); /* readable on the dark basemap */
    border-radius: 6px;
}
</style>"""
UUID_RE = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
    re.IGNORECASE,
)


def pic_id_from_url(text: str) -> str | None:
    """Picture id from a Panoramax URL (`pic=<uuid>`, often in the #fragment) or a bare id."""
    m = re.search(r"pic=(" + UUID_RE.pattern + ")", text, re.IGNORECASE)
    if m:
        return m.group(1)
    m = UUID_RE.search(text)
    return m.group(0) if m else None


# ---------- page ----------


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
    download = st.session_state.download
    try:
        with st.spinner(
            "Downloading pictures..." if download else "Searching pictures..."
        ):
            pics = nearby_pictures(pic_id, radius, download)
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


@st.cache_data(max_entries=8, show_spinner="Locating the signs...")
def locate(
    _items: list[Item],
    ids: tuple[str, ...],
    lon: float,
    lat: float,
    radius: float,
    cell: float,
    max_dist: float,
) -> tuple[dict[Group, list[Ray]], dict[Group, dict[Cell, float]], list[Sign]]:
    """Ray groups, one vote heatmap per group, and the signs found from them.

    Seconds of work for a big search: cached, so going from one picture to the next,
    or changing a display option, does not redo it. `_items` is not hashed (thousands
    of big dicts): `ids` stands for it.
    """
    groups = ray_groups(_items, lon, lat, radius)
    heats = the_ray_voting_algorithm(_items, lon, lat, radius, cell, max_dist)
    # numbered over all the pictures: a sign keeps its number from one picture to the next
    signs = find_signs(_items, lon, lat, radius, cell, max_dist)
    return groups, heats, signs


@st.cache_data(max_entries=16, show_spinner="Drawing the votes...")
def vote_layer(
    _heats: dict[Group, dict[Cell, float]],
    _colors: dict[Group, tuple[int, int, int]],
    search: tuple,
    view: str,
    selected: Group | None,
) -> tuple[int, list[dict[str, object]], dict[str, object] | None]:
    """How many cells have a vote, and the map's cells: one polygon each with its
    hover text, or one image when there are too many (cells then empty).

    Cached like locate: `search` (the arguments of locate) stands for `_heats` and
    `_colors`, computed from it.
    """
    _, lon, lat, radius, cell, _ = search
    per_cell = voted_cells(_heats, view, selected)
    if len(per_cell) <= MAX_HOVER_CELLS:
        cells = vote_cells(lon, lat, radius, cell, per_cell, _colors, view)
        return len(per_cell), cells, None
    image = vote_image(lon, lat, radius, cell, per_cell, _colors, view)
    return len(per_cell), [], image


def show_panorama(
    pic: Item,
    items: list[Item],
    annotations: list[Item],
    labels: tuple[str, ...],
    below: tuple[str, ...],
) -> None:
    """360° view of the picture, its boxes labelled, with arrows to the nearby ones."""
    item: Item = pic["item"]
    src = pic["jpg"] or pic["hd"]  # not downloaded: fetched from Panoramax
    try:
        with st.spinner("Loading 360° view..."):
            pano = pano_data_url(src, annotations, labels, below)
        panorama(
            data=panorama_config(
                pano, item["properties"], move_targets(items, item)
            ),
            key="pano",
            on_move_change=move_from_pano,
        )
    except Exception as e:  # noqa: BLE001 - shown in the page, not a crash
        st.warning(f"Could not load {src}: {e}")


def main() -> None:
    st.set_page_config(page_title="panoloc", layout="wide")
    st.html(MAP_FULLSCREEN_CSS)

    with st.form("url_form", border=False):
        url_col, btn_col = st.columns([6, 1], vertical_alignment="bottom")
        url_col.text_input(
            "Panoramax URL",
            key="pano_url",
            value=DEFAULT_URL,
            placeholder="https://api.panoramax.xyz/#focus=pic&pic=...",
        )
        btn_col.form_submit_button(
            "Load", on_click=load_from_url, width="stretch"
        )
    if err := st.session_state.pop("url_error", None):
        st.error(err)

    # new session (a reload, a restart): start from the options saved last time.
    # The widgets take their value from session_state, so they have no `value=`.
    if "saved_sidebar" not in st.session_state:
        st.session_state.saved_sidebar = load_sidebar(SIDEBAR)
        st.session_state.update(st.session_state.saved_sidebar)

    # bbox parameter, used by the Load button (keyed: read in load_from_url)
    st.sidebar.markdown("**Search area**")
    st.sidebar.number_input(
        "Radius (m)",
        min_value=5,
        max_value=1000,
        step=5,
        key="radius",
    )
    st.sidebar.checkbox(
        "Download pictures",
        key="download",
        help="Save the HD pictures to data/raw on Load. Off: only the shown one is fetched.",
    )
    cell = st.sidebar.number_input(
        "Grid cell (m)", min_value=0.1, max_value=100.0, step=0.1, key="cell"
    )
    st.sidebar.markdown("**Heatmap**")
    max_dist = st.sidebar.number_input(
        "Max ray distance (m)",
        min_value=1,
        max_value=3000,
        step=5,
        key="max_dist",
    )
    view = st.sidebar.radio("Votes", VIEWS, key="view")
    group_box = st.sidebar.container()  # filled once the groups are known
    show_numbers = st.sidebar.checkbox("Show numbers", key="show_numbers")
    show_rays = st.sidebar.checkbox("Show voting rays", key="show_rays")
    show_signs = st.sidebar.checkbox("Show located signs", key="show_signs")
    full_map = st.sidebar.checkbox(
        "Full-screen map",
        key="full_map",
        help="The map over the whole width, without the 360° view: the picture details go under it.",
    )
    show_pano = st.sidebar.checkbox(
        "Show 360° view",
        disabled=full_map,
        key="show_pano",
        help="Off: the picture is not loaded, faster to browse from the map.",
    )
    st.sidebar.divider()

    options = {k: st.session_state[k] for k in SIDEBAR}
    if options != st.session_state.saved_sidebar:
        save_sidebar(options)
        st.session_state.saved_sidebar = options

    pics: list[Item] = st.session_state.get("pics", [])
    if not pics:
        st.info("Paste a Panoramax picture URL above and press Load.")
        st.stop()
    items = [pic["item"] for pic in pics]
    n = len(pics)

    # navigation state survives reruns in st.session_state
    if "idx" not in st.session_state:
        st.session_state.idx = 0
    st.session_state.idx = min(
        st.session_state.idx, n - 1
    )  # sequence may have changed
    prev_col, next_col = st.sidebar.columns(2)
    prev_col.button("< prev", on_click=step, args=(-1, n), width="stretch")
    next_col.button("next >", on_click=step, args=(1, n), width="stretch")
    if n > 1:  # a slider needs min < max
        st.sidebar.slider("Picture", 0, n - 1, key="idx")

    pic = pics[st.session_state.idx]
    item: Item = pic["item"]
    props: Item = item["properties"]
    annotations: list[Item] = props.get("annotations") or []

    # ray voting: one heatmap per (sign type, travel direction) group
    center, radius = st.session_state.search
    search = (
        tuple(pic["id"] for pic in pics),
        *center,
        radius,
        cell,
        max_dist,
    )
    groups, heats, signs = locate(items, *search)
    numbers = sign_numbers(signs)
    distances = sign_distances(signs)
    labels = tuple(
        box_label(
            [(numbers.get((a.get("id"), t)), t) for t in sign_types_of(a)]
        )
        for a in annotations
    )
    # under each box of the 360° view: how far the sign is from the camera
    below = tuple(
        distance_label(distances.get(a.get("id"))) for a in annotations
    )
    keys = sorted_groups(groups)
    colors = group_colors(keys)
    selected = None
    if view == ONE:
        if keys:
            selected = group_box.selectbox(
                "Group",
                keys,
                format_func=lambda k: (
                    f"{group_label(k)}, {len(groups[k])} rays"
                ),
            )
        else:
            group_box.caption("No sign annotation to vote with.")
    n_voted, cells, image = vote_layer(heats, colors, search, view, selected)
    rays = (
        ray_lines(groups, colors, *center, radius, max_dist, only=selected)
        if show_rays
        else None
    )

    if full_map:  # one column: the picture details go under the map
        left = right = st.container()
    else:
        left, right = st.columns([3, 2])

    with left:
        if show_pano and not full_map:
            show_panorama(pic, items, annotations, labels, below)
        st.pydeck_chart(
            heading_map(
                items,
                item,
                bbox_ring(*center, radius),
                grid_lines(*center, radius, cell),
                cells,
                show_numbers,
                rays,
                sign_markers(signs, *center, radius, item["id"])
                if show_signs
                else None,
                image,
            ),
            height=FULL_MAP_HEIGHT_PX if full_map else MAP_HEIGHT_PX,
            on_select=move_from_map,
            key="map",
        )
        if image:
            st.caption(
                f"{n_voted:,} cells with votes: drawn as an image, "
                "without numbers nor hover text. A bigger grid cell or a "
                "smaller radius brings them back."
            )
        if rays or view == WINNER:  # legend: one color per group
            shown = [selected] if selected else keys
            st.html(
                " ".join(
                    f'<span style="white-space: nowrap; margin-right: 12px">'
                    f'<span style="color: rgb{colors[k]}">&#9632;</span> '
                    f"{icon_img(k[0], 16)}{group_label(k)} ({len(groups[k])})</span>"
                    for k in shown
                )
            )

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
                f"{labels[i]} — heading from camera: "
                + ("unknown" if heading is None else f"{heading:.0f}°")
                + ", elevation: "
                + ("unknown" if elevation is None else f"{elevation:+.1f}°")
            )
            icons = "".join(icon_img(t, 32) for t in sign_types_of(annot))
            st.html(f'{icons}<span style="color: {INFO_COLOR}">{info}</span>')
            st.table(tags_table(annot.get("semantics")))

        with st.expander("Raw JSON"):
            st.json(item)


if __name__ == "__main__":
    main()
