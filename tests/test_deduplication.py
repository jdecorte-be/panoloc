import json
import math
from collections import defaultdict
from pathlib import Path

import pytest

from panoloc.bbox import M_PER_DEG_LAT
from panoloc.deduplication import find_signs, the_ray_voting_algorithm

ROOT = Path(__file__).parent.parent
SEQUENCE_DIR = ROOT / "data/raw/0fc301f5-a742-4405-8e6a-1c180a2121ff"
TARGET = "cfbce3b6-2904-41aa-9837-a3d2dffec6d5"  # the app's default picture
RADIUS_M, CELL_M, MAX_RAY_M = 50, 0.5, 45  # default setup
TOLERANCE_M = 2.0

POLES = json.loads(
    (Path(__file__).parent / "fixtures/strasbourg_poincare.json").read_text()
)

# Strasbourg's local names for signs that have a standard code
ALIASES = {
    "Eurométropole Stationnement PMR": ["B6d", "M6h"]
}  # disabled parking

# Poles where the photos (2025-09-16) contradict Strasbourg's survey (2023-06-07)
CORRECTIONS = {
    "20240209011251": [
        "B27a"
    ],  # Strasbourg says B22a, the photos show a bus lane sign
}


def codes(traffic_sign: str) -> list[str]:
    """'FR:B14[30];FR:M9v' -> ['B14', 'M9v']"""
    return [
        c.removeprefix("FR:").partition("[")[0]
        for c in traffic_sign.split(";")
    ]


def main_codes(traffic_sign: str) -> list[str]:
    """The signs themselves, without their sub-panels (M...) when there is one."""
    all_codes = codes(traffic_sign)
    return [c for c in all_codes if not c.startswith("M")] or all_codes


def same_sign(a: str, b: str) -> bool:
    """Same code, or a variant of it: AB3 and AB3a are both 'give way'."""
    short, long = sorted((a, b), key=len)
    return long.startswith(short) and (
        long == short or long[len(short) :].isalpha()
    )


@pytest.fixture(scope="module")
def sequence():
    if not SEQUENCE_DIR.exists():
        pytest.skip(
            f"{SEQUENCE_DIR} missing: load the app's default URL first"
        )
    items = [json.loads(p.read_text()) for p in SEQUENCE_DIR.glob("*.json")]
    target = next(i for i in items if i["id"] == TARGET)
    return items, target["geometry"]["coordinates"]


@pytest.fixture(scope="module")
def heats(sequence):
    items, center = sequence
    return center, the_ray_voting_algorithm(
        items, *center, RADIUS_M, CELL_M, MAX_RAY_M
    )


@pytest.fixture(scope="module")
def signs(sequence):
    items, center = sequence
    return center, find_signs(items, *center, RADIUS_M, CELL_M, MAX_RAY_M)


def local_xy(center, lon: float, lat: float) -> tuple[float, float]:
    """(lon, lat) in the meters of the voting grid."""
    clon, clat = center
    x = (lon - clon) * M_PER_DEG_LAT * math.cos(math.radians(clat)) + RADIUS_M
    y = (lat - clat) * M_PER_DEG_LAT + RADIUS_M
    return x, y


def expected_signs(pole) -> list[str]:
    registered = CORRECTIONS.get(
        pole["id_support"], pole["registres_panneaux"]
    )
    return [a for c in registered for a in ALIASES.get(c, [c])]


def votes_around(heats, lon: float, lat: float) -> list[tuple[str, float]]:
    """Best heat of every sign type within TOLERANCE_M of (lon, lat), strongest first."""
    center, groups = heats
    x, y = local_xy(center, lon, lat)
    per_type: dict[str, float] = defaultdict(float)
    for (sign_type, _sector), heat in groups.items():
        for (cx, cy), score in heat.items():
            if (
                math.hypot((cx + 0.5) * CELL_M - x, (cy + 0.5) * CELL_M - y)
                <= TOLERANCE_M
            ):
                per_type[sign_type] = max(per_type[sign_type], score)
    return sorted(per_type.items(), key=lambda kv: -kv[1])


@pytest.mark.parametrize(
    "pole",
    POLES,
    ids=[
        f"{'+'.join(p['registres_panneaux'])}-{p['id_support']}" for p in POLES
    ],
)
def test_sign_type_matches_strasbourg(heats, pole):
    expected = expected_signs(pole)
    point = pole["geo_point_2d"]
    votes = votes_around(heats, point["lon"], point["lat"])
    assert votes, (
        f"no typed vote within {TOLERANCE_M} m, Strasbourg has {expected}"
    )

    winner = votes[0][0]
    ranking = ", ".join(f"{t} {v:.1f}" for t, v in votes[:4])
    assert any(
        same_sign(c, e) for c in main_codes(winner) for e in expected
    ), f"computed {winner}, Strasbourg has {expected} (votes: {ranking})"


@pytest.mark.parametrize(
    "pole",
    POLES,
    ids=[
        f"{'+'.join(p['registres_panneaux'])}-{p['id_support']}" for p in POLES
    ],
)
def test_one_number_per_sign(signs, pole):
    """Every picture of a sign must get the same number: one sign, not one per picture."""
    center, found = signs
    point = pole["geo_point_2d"]
    x, y = local_xy(center, point["lon"], point["lat"])
    numbers = {
        e: [
            s.number
            for s in found
            if any(same_sign(c, e) for c in codes(s.sign_type))
            and math.hypot(s.x - x, s.y - y) <= TOLERANCE_M
        ]
        for e in main_codes(";".join(expected_signs(pole)))
    }
    assert all(len(n) <= 1 for n in numbers.values()), (
        f"a sign got several numbers: {numbers}"
    )
    assert any(numbers.values()), (
        f"no sign numbered within {TOLERANCE_M} m: {numbers}"
    )
