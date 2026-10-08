import pytest

from panoloc.frontend import settings

DEFAULTS = {"radius": 50, "cell": 0.5, "view": "Winning group per cell", "rays": False}


@pytest.fixture(autouse=True)
def cache_file(tmp_path, monkeypatch):
    path = tmp_path / "panoloc" / "sidebar.json"
    monkeypatch.setattr(settings, "CACHE_FILE", path)
    return path


def test_defaults_when_nothing_saved():
    assert settings.load(DEFAULTS) == DEFAULTS


def test_saved_options_are_restored():
    options = {"radius": 200, "cell": 1.0, "view": "One group", "rays": True}
    settings.save(options)
    assert settings.load(DEFAULTS) == options


@pytest.mark.parametrize(
    "content",
    [
        pytest.param("{not json", id="broken"),
        pytest.param("[1, 2]", id="not-an-object"),
        pytest.param('{"radius": "200", "cell": 1, "rays": 0}', id="wrong-types"),
    ],
)
def test_bad_file_falls_back_to_defaults(cache_file, content):
    cache_file.parent.mkdir(parents=True)
    cache_file.write_text(content)
    assert settings.load(DEFAULTS) == DEFAULTS


def test_unknown_and_missing_keys(cache_file):
    settings.save({"radius": 200, "removed_option": 1})
    assert settings.load(DEFAULTS) == {**DEFAULTS, "radius": 200}


def test_save_leaves_no_temporary_file(cache_file):
    settings.save(DEFAULTS)
    settings.save({**DEFAULTS, "radius": 100})
    assert [p.name for p in cache_file.parent.iterdir()] == ["sidebar.json"]
