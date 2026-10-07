"""360° view: a Pannellum viewer with clickable arrows to the nearby pictures."""

import math

import streamlit.components.v2 as components_v2

from panoloc.bbox import Item
from panoloc.geo import bearing_distance, signed_angle

PANNELLUM = "https://cdnjs.cloudflare.com/ajax/libs/pannellum/2.5.6"
PANO_HEIGHT_PX = 450
MOVE_MAX_TARGETS = (
    8  # nearest pictures shown as clickable arrows in the 360° view
)
CAMERA_HEIGHT_M = 2.5  # used to place the arrows below the horizon


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
        bearing, dist = bearing_distance(
            lon, lat, *f["geometry"]["coordinates"]
        )
        if dist < 0.5:  # same spot: no meaningful direction
            continue
        targets.append(
            {
                "idx": idx,
                "yaw": signed_angle(bearing - azimuth),
                "pitch": -math.degrees(math.atan2(CAMERA_HEIGHT_M, dist)),
                "text": f"Move {dist:.0f} m",
                "dist": dist,
            }
        )
    return sorted(targets, key=lambda t: t["dist"])[:limit]


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
            {
                "yaw": t["yaw"],
                "pitch": t["pitch"],
                "text": t["text"],
                "idx": t["idx"],
            }
            for t in targets
        ],
    }
    if (
        azimuth is not None
    ):  # compass: yaw 0 (image center) points to view:azimuth
        config |= {"northOffset": azimuth, "compass": True}
        if fov >= 360:  # open the view facing north (yaw of north = -azimuth)
            config["yaw"] = signed_angle(-azimuth)
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
