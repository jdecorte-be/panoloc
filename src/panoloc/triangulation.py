from math import cos, pi, radians, sin

from .errors import ImpossibleTriangleError, PrecisionError, TriangulationError
from .utils import Node, Point


def _get_quadrant(rad: float) -> int:
    rad = rad % (2 * pi)
    if rad < pi / 2 and rad >= 0:
        return 1
    elif rad < pi and rad >= pi / 2:
        return 2
    elif rad < 3 * pi / 2 and rad >= pi:
        return 3
    # rad < 2 * pi and rad >= 3 * pi / 2:
    else:
        return 4


def _check_result(quadrant: int, target: Point, origin: Point) -> None:
    if quadrant == 0:
        if target.x == origin.x != target.y == origin.y:
            raise ImpossibleTriangleError(
                "Target and origin are the same coordinates"
            )
        return
    if quadrant in [1, 4]:
        if target.x < origin.x:
            raise ImpossibleTriangleError("points view never join.")
    else:
        if target.x > origin.x:
            raise ImpossibleTriangleError("points view never join.")
    if quadrant in [1, 2]:
        if target.y < origin.y:
            raise ImpossibleTriangleError("points view never join.")
    else:
        if target.y > origin.y:
            raise ImpossibleTriangleError("points view never join.")


def triangulate(
    a: Point,
    b: Point,
    ra: float,
    rb: float,
) -> Point:
    """Get the parralax between two 2d points.

        Both rotation need to be relative to the north
        or else the rotations values will not match.
    Args:
        a: The first point need to be beyond b.
        b: The second point need to be behind a.
        ra: The angle between a and target.
        rb: The angle between b and target.

    Returns:
        The target coordinates.
    """
    if abs(ra - rb) == 180:
        raise PrecisionError("points look at perfectly opposed directions.")
    angle_a = radians(90 - ra)
    dxa = cos(angle_a)
    dya = sin(angle_a)
    quadrant_a = _get_quadrant(angle_a)

    angle_b = radians(90 - rb)
    dxb = cos(angle_b)
    dyb = sin(angle_b)
    quadrant_b = _get_quadrant(angle_b)

    cross_product = dxa * dyb - dya * dxb

    if cross_product == 0:
        raise PrecisionError("both points look at the same direction.")

    t = ((b.x - a.x) * dyb - (b.y - a.y) * dxb) / cross_product

    target = Point(round(a.x + t * dxa, 5), round(a.y + t * dya, 5))
    _check_result(quadrant_a, target, a)
    _check_result(quadrant_b, target, b)
    # Adittional optional metadatas
    # The distance between target and base points
    # delta_a = sqrt((intersect.x - a.x) ** 2 + (intersect.y - a.y) ** 2)
    # delta_b = sqrt((intersect.x - b.x) ** 2 + (intersect.y - b.y) ** 2)

    # The interior angle of the triangle
    # interior_angle = arccos(
    #     (
    #         delta_a**2
    #         + delta_b**2
    #         - sqrt((a.x - b.x) ** 2 + (a.y - b.y) ** 2) ** 2
    #     )
    #     / (2 * delta_a * delta_b)
    # )
    return target


def triangulate_many(nodes: list[Node]) -> dict[Point, float]:
    """Triangulate a list of points together.
        Complexity of this is ~O((n - 1)!).

    Args:
        points: The list of points.

    Returns:
        A dict of points and their probability.
    """
    results: dict[Point, float] = {}
    total = 0
    for i, n1 in enumerate(nodes, start=1):
        if i == len(nodes):
            break
        for _, n2 in enumerate(nodes[i:]):
            total += 1
            try:
                res = triangulate(
                    n1.coordinate, n2.coordinate, n1.rotation, n2.rotation
                )
                if res in results:
                    results[res] += 1
                else:
                    results[res] = 1
            except TriangulationError:
                pass
    scores: dict[Point, float] = {}
    for s, value in results.items():
        scores[s] = 100 * value / total
    return scores
