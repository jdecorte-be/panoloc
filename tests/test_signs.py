import pytest

from panoloc.frontend.map_shapes import sign_icon
from panoloc.frontend.signs import (
    ICONS_DIR,
    icon_key,
    icon_ratio,
    manifest,
    sign_name,
)


@pytest.mark.parametrize(
    "traffic_sign, expected",
    [
        pytest.param("FR:B14[50]", "B14[50]", id="own-pictogram"),
        pytest.param("FR:B14[33]", "B14", id="bare-code"),
        pytest.param("FR:A13b", "A13B", id="lower-case"),
        pytest.param("FR:B0,M9v2", "B0", id="composite"),
        pytest.param("FR:XX1", None, id="unknown"),
        pytest.param("stop", None, id="not-a-code"),
    ],
)
def test_icon_key(traffic_sign, expected):
    assert icon_key(traffic_sign) == expected


def test_every_pictogram_has_a_file_and_a_ratio():
    for key in manifest():
        assert (ICONS_DIR / f"{key}.svg").is_file()
        assert icon_ratio(key) > 0


def test_wide_sub_panel_fits_the_atlas():
    icon = sign_icon("FR:M6h")
    assert icon["width"] > 2 * icon["height"]
    assert max(icon["width"], icon["height"]) == 128


def test_sign_name_falls_back_to_the_pictogram_name():
    assert sign_name("FR:B14[30]") == "Speed limit (B14[30])"
    assert sign_name("FR:A1a") == "Virage à droite (A1a)"
    assert sign_name("FR:XX1") == "FR:XX1"
