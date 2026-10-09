import pytest

from panoloc.locate import (
    TILE_DEG,
    LocalCache,
    parse_tile,
    tile_id,
    tile_name,
    tiles_of,
)


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


def sign(lon, lat):
    return {"sign": "B1", "position": [lon, lat], "rays": []}


def test_local_cache_keeps_the_tiles_of_the_current_code(tmp_path):
    cache = LocalCache(tmp_path / "cache.sqlite")
    cache.put("1:2:0.5:45", "new", [sign(1.0, 2.0)])
    cache.put("1:3:0.5:45", "old", [sign(1.0, 3.0)])
    cache.put("1:4:0.5:45", "new", [sign(0, 0)])
    cache.put("1:4:0.5:45", "new", [])  # located again
    ids = ["1:2:0.5:45", "1:3:0.5:45", "1:4:0.5:45", "9:9:0.5:45"]
    assert cache.get(ids, "new") == {"1:2:0.5:45": [sign(1.0, 2.0)], "1:4:0.5:45": []}
    # read again from the file
    assert LocalCache(tmp_path / "cache.sqlite").get(ids, "old") == {
        "1:3:0.5:45": [sign(1.0, 3.0)]
    }


def test_local_cache_counts_the_tiles_with_signs(tmp_path):
    cache = LocalCache(tmp_path / "cache.sqlite")
    cache.put("1:2:0.5:45", "new", [sign(1.0, 2.0), sign(3.0, 4.0)])
    cache.put("1:3:1:45", "new", [sign(1.0, 3.0)])  # other parameters
    cache.put("1:4:0.5:45", "new", [])
    assert list(cache.counts(":0.5:45", "new")) == [("1:2:0.5:45", 2, 4.0, 6.0)]


def test_local_cache_gets_more_ids_than_a_query_takes(tmp_path):
    cache = LocalCache(tmp_path / "cache.sqlite")
    ids = [f"{i}:0:0.5:45" for i in range(1200)]
    for id in ids:
        cache.put(id, "new", [])
    assert len(cache.get(ids, "new")) == len(ids)
