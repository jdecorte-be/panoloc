import pydeck as pdk

from panoloc.bbox import Item
from panoloc.frontend.map_shapes import offset

# length of the heading
HEADING_LENGTH_M = 30


def heat_color(vmax: float) -> str:
    """deck.gl color expression: transparent for 0, dark gray shifting to red as value approaches vmax.

    Cells with an rgb (winning group view) take that color, more opaque as value grows.
    """
    t = f"value / {vmax}" if vmax > 0 else "0"
    return (
        f"rgb ? [rgb[0], rgb[1], rgb[2], 80 + 160 * {t}]"
        f" : [60 + 160 * {t}, 60 * (1 - {t}), 60 * (1 - {t}), value > 0 ? 160 : 0]"
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
) -> pdk.Deck:
    """cells: votes.vote_cells output; rays: votes.ray_lines output (None: hidden);
    signs: map_shapes.sign_markers output (None: hidden)."""
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
                get_radius=0.6,
                # orange like the boxes of the 360° view: the signs this picture shows
                get_fill_color="current ? [255, 140, 0] : [255, 255, 255]",
                get_line_color=[0, 0, 0],
                stroked=True,
                line_width_min_pixels=1,
                radius_min_pixels=5,
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
                get_pixel_offset=[0, -16],
                background=True,
                get_background_color=[255, 255, 255, 210],
            ),
        ]
    view = pdk.ViewState(longitude=lon, latitude=lat, zoom=17)
    # Streamlit puts deck.gl's widget root under the map instead of over it, which
    # draws the tooltip one map height above the cursor: top 100% moves it back
    tooltip = {"text": "{info}", "style": {"top": "100%"}}
    return pdk.Deck(layers=layers, initial_view_state=view, tooltip=tooltip)
