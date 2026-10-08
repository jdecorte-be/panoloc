import pytest

from panoloc.locate import TILE_DEG, parse_tile, tile_id, tile_name, tiles_of


@pytest.mark.parametrize(
    "bbox, expected",
    [
        pytest.param(
            (0.1 * TILE_DEG, 0.1 * TILE_DEG, 0.9 * TILE_DEG, 0.9 * TILE_DEG),
            [(0, 0)],
            id="inside-one-tile",
        ),
        pytest.param(
            (0.5 * TILE_DEG, 0.5 * TILE_DEG, 1.5 * TILE_DEG, 1.5 * TILE_DEG),
            [(0, 0), (0, 1), (1, 0), (1, 1)],
            id="across-four",
        ),
        pytest.param(
            (-0.5 * TILE_DEG, 0.0, 0.5 * TILE_DEG, TILE_DEG),
            [(-1, 0), (0, 0)],
            id="negative-longitude",
        ),
    ],
)
def test_tiles_of(bbox, expected):
    assert sorted(tiles_of(*bbox)) == expected


def test_tiles_cover_the_bbox():
    west, south, east, north = 7.7345, 48.5870, 7.7482, 48.5927
    tiles = tiles_of(west, south, east, north)
    i0, j0 = min(tiles)
    i1, j1 = max(tiles)
    assert i0 * TILE_DEG <= west and (i1 + 1) * TILE_DEG >= east
    assert j0 * TILE_DEG <= south and (j1 + 1) * TILE_DEG >= north


def test_tile_id_depends_on_the_parameters():
    assert tile_id((1, 2), 0.5, 45) != tile_id((1, 2), 1.0, 45)


def test_tile_id_ignores_how_numbers_are_written():
    assert tile_id((1, 2), 0.5, 45) == tile_id((1, 2), 0.5, 45.0)


@pytest.mark.parametrize("tile", [(0, 0), (3081, 19433), (-12, 7)])
def test_tile_name_round_trip(tile):
    assert parse_tile(tile_name(tile)) == tile
