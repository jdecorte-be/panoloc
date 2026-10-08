import pydeck as pdk

from panoloc.bbox import Item
from panoloc.frontend.map_shapes import SIGN_ICON_PX, offset

# length of the heading
HEADING_LENGTH_M = 30
# radius of the disc behind a sign pictogram
SIGN_DISC_PX = SIGN_ICON_PX // 2 + 3
SIGN_DOT_PX = 5  # radius of the dot of a sign without pictogram


def heat_color(vmax: float) -> str:
    """deck.gl color expression: transparent for 0, dark gray shifting to red as value approaches vmax.

    Cells with an rgb (winning group view) take that color, more opaque as value grows.
    """
    t = f"value / {vmax}" if vmax > 0 else "0"
    return (
        f"rgb ? [rgb[0], rgb[1], rgb[2], 80 + 160 * {t}]"
        f" : [60 + 160 * {t}, 60 * (1 - {t}), 60 * (1 - {t}), value > 0 ? 160 : 0]"
    )


def heat_rgba(
    value: float, vmax: float, rgb: tuple[int, int, int] | None
) -> tuple[int, int, int, int]:
    """heat_color in Python, for the cells drawn as an image (votes.vote_image)."""
    t = value / vmax if vmax > 0 else 0
    if rgb:
        return (*rgb, round(80 + 160 * t))
    return (
        round(60 + 160 * t),
        round(60 * (1 - t)),
        round(60 * (1 - t)),
        160 if value > 0 else 0,
    )


# draw the heading
def heading_map(
    items: list[Item],
    current: Item,
    bbox: list[list[float]],
    grid: list[dict[str, list[float]]],
    cells: list[dict[str, object]],
    show_numbers: bool = False,
    rays: list[dict[str, object]] | None = None,
    signs: list[dict[str, object]] | None = None,
    image: dict[str, object] | None = None,
) -> pdk.Deck:
    """cells: votes.vote_cells output; rays: votes.ray_lines output (None: hidden);
    signs: map_shapes.sign_markers output (None: hidden);
    image: votes.vote_image output, the cells drawn as one picture (None: no image)."""
    vmax = max((c["value"] for c in cells), default=0)
    # label at the center of each non-zero cell
    labels = [
        {
            "pos": [
                (c["polygon"][0][0] + c["polygon"][2][0]) / 2,
                (c["polygon"][0][1] + c["polygon"][2][1]) / 2,
            ],
            "text": str(round(c["value"])),
        }
        for c in cells
        if show_numbers and c["value"]
    ]
    cameras = [
        {
            "pos": f["geometry"]["coordinates"],
            "current": f["id"] == current["id"],
            "info": f"picture {i + 1}",
        }
        for i, f in enumerate(items)
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
            "PolygonLayer",
            id="cells",
            data=cells,
            pickable=True,  # hover a cell to see which groups vote for it
            get_polygon="polygon",
            get_fill_color=heat_color(vmax),
            stroked=False,
        ),
    ]
    if image:
        layers.append(
            pdk.Layer(
                "BitmapLayer",
                id="cells_image",
                # quoted: pydeck would turn the data URL into a JS expression
                image=f"'{image['image']}'",
                bounds=image["bounds"],
                # one pixel per cell: sharp squares when zoomed in, not a blur
                texture_parameters={
                    "minFilter": "nearest",
                    "magFilter": "nearest",
                },
            )
        )
    layers += [
        pdk.Layer(
            "LineLayer",
            data=grid,
            get_source_position="from",
            get_target_position="to",
            get_color=[40, 120, 230, 30],
            get_width=1,
        ),
        pdk.Layer(
            "TextLayer",
            data=labels,
            get_position="pos",
            get_text="text",
            get_size=12,
            get_color=[0, 0, 0],
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
    if rays:
        layers.append(
            pdk.Layer(
                "LineLayer",
                id="rays",
                data=rays,
                pickable=True,
                get_source_position="from",
                get_target_position="to",
                get_color="color",
                get_width=1,
            )
        )
    if signs:
        layers += [
            pdk.Layer(
                "ScatterplotLayer",
                id="signs",
                data=signs,
                pickable=True,  # hover a sign to see its type
                get_position="pos",
                # a disc behind each pictogram (readable on the heatmap), a dot without
                get_radius=f"icon ? {SIGN_DISC_PX} : {SIGN_DOT_PX}",
                # quoted: pydeck turns the other strings into JS expressions
                radius_units="'pixels'",
                # orange like the boxes of the 360° view: the signs this picture shows
                get_fill_color="current ? [255, 140, 0] : [255, 255, 255]",
            ),
            pdk.Layer(
                "IconLayer",
                id="sign_icons",
                data=[s for s in signs if s["icon"]],
                pickable=True,
                get_position="pos",
                get_icon="icon",
                get_size="size",
                size_units="'pixels'",
            ),
            pdk.Layer(
                "TextLayer",
                id="sign_labels",
                data=signs,
                pickable=True,  # the #n label too, else its hover shows the cell below
                get_position="pos",
                get_text="text",
                get_size=13,
                get_color=[20, 20, 20],
                get_pixel_offset=f"[0, icon ? {-SIGN_DISC_PX - 10} : -16]",
                background=True,
                get_background_color=[255, 255, 255, 210],
            ),
        ]
    view = pdk.ViewState(longitude=lon, latitude=lat, zoom=17)
    # Streamlit puts deck.gl's widget root under the map instead of over it, which
    # draws the tooltip one map height above the cursor: top 100% moves it back
    tooltip = {"text": "{info}", "style": {"top": "100%"}}
    return pdk.Deck(layers=layers, initial_view_state=view, tooltip=tooltip)
