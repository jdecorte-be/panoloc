import re

import streamlit as st

from panoloc.annotations import annotation_elevation, annotation_heading
from panoloc.bbox import VIEWER, Item, PictureNotFound, nearby_pictures
from panoloc.deduplication import (
    group_label,
    ray_groups,
    the_ray_voting_algorithm,
)
from panoloc.frontend.drawing import annotation_label, tags_table
from panoloc.frontend.heading_map import heading_map
from panoloc.frontend.images import annotated, pano_data_url
from panoloc.frontend.map_shapes import bbox_ring, grid_cells, grid_lines
from panoloc.frontend.panorama import move_targets, panorama, panorama_config
from panoloc.frontend.votes import (
    ONE,
    VIEWS,
    WINNER,
    group_colors,
    ray_lines,
    sorted_groups,
    vote_cells,
)

DEFAULT_URL = (
    "https://explore.panoramax.fr/fr/index?focus=map&map=15.12/48.589898/7.741354"
    "&pic=cfbce3b6-2904-41aa-9837-a3d2dffec6d5&seq=0fc301f5-a742-4405-8e6a-1c180a2121ff"
    "&speed=250&theme=default&users=default&xyz=66.88/-13.30/30"
)
INFO_COLOR = "#4fa8ff"  # light blue, readable on light and dark themes
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
        btn_col.form_submit_button(
            "Load", on_click=load_from_url, width="stretch"
        )
    if err := st.session_state.pop("url_error", None):
        st.error(err)

    # bbox parameter, used by the Load button (keyed: read in load_from_url)
    st.sidebar.markdown("**Search area**")
    st.sidebar.number_input(
        "Radius (m)",
        min_value=5,
        max_value=1000,
        value=50,
        step=5,
        key="radius",
    )
    cell = st.sidebar.number_input(
        "Grid cell (m)", min_value=0.1, max_value=100.0, value=0.5, step=0.1
    )
    st.sidebar.markdown("**Heatmap**")
    max_dist = st.sidebar.number_input(
        "Max ray distance (m)", min_value=1, max_value=3000, value=30, step=5
    )
    view = st.sidebar.radio("Votes", VIEWS)
    group_box = st.sidebar.container()  # filled once the groups are known
    show_numbers = st.sidebar.checkbox("Show numbers", value=False)
    show_rays = st.sidebar.checkbox("Show voting rays", value=False)
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
    groups = ray_groups(items, *center, radius)
    heats = the_ray_voting_algorithm(items, *center, radius, cell, max_dist)
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
    cells = vote_cells(
        grid_cells(*center, radius, cell), heats, colors, view, selected
    )
    rays = (
        ray_lines(groups, colors, *center, radius, max_dist, only=selected)
        if show_rays
        else None
    )

    left, right = st.columns([3, 2])

    with left:
        try:
            with st.spinner("Loading picture..."):
                st.image(annotated(pic["jpg"], annotations), width="stretch")
        except Exception as e:  # noqa: BLE001 - shown in the page, not a crash
            st.warning(f"Could not load {pic['jpg']}: {e}")
        st.pydeck_chart(
            heading_map(
                items,
                item,
                bbox_ring(*center, radius),
                grid_lines(*center, radius, cell),
                cells,
                show_numbers,
                rays,
            ),
            on_select=move_from_map,
            key="map",
        )
        if rays or view == WINNER:  # legend: one color per group
            shown = [selected] if selected else keys
            st.html(
                " ".join(
                    f'<span style="white-space: nowrap; margin-right: 12px">'
                    f'<span style="color: rgb{colors[k]}">&#9632;</span> '
                    f"{group_label(k)} ({len(groups[k])})</span>"
                    for k in shown
                )
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
