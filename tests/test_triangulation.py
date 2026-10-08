import pytest

from panoloc.errors import ImpossibleTriangleError, PrecisionError
from panoloc.triangulation import triangulate, triangulate_many
from panoloc.utils import Node, Point

# rotations are relative to north, clockwise: 0 = up, 90 = right
A = Node(Point(1, 5), 90)
B = Node(Point(3, 2), 45)
C = Node(Point(6, 1), 0)
D = Node(Point(5, 7), 150)
E = Node(Point(9, 2), -45)


@pytest.mark.parametrize(
    "a, b, rot_a, rot_b, expected",
    [
        # A
        #  \
        #   \T
        #   /
        #  /
        # B
        pytest.param(
            Point(1, 7), Point(1, 1), 135, 45, Point(4, 4), id="symmetric"
        ),
        # A
        #  \
        #   \
        #    \T
        #    /
        #   B
        pytest.param(
            Point(1, 7), Point(3, 1), 135, 45, Point(5, 3), id="shifted"
        ),
        # A--T
        #    |
        #    |
        #    B
        pytest.param(
            Point(1, 7), Point(4, 1), 90, 0, Point(4, 7), id="right-angle"
        ),
        #    A
        #    |
        #    |
        # B__T
        pytest.param(
            Point(4, 7),
            Point(1, 1),
            180,
            90,
            Point(4, 1),
            id="right-angle-below",
        ),
        # A
        #  \
        #   \
        # B____\
        pytest.param(
            Point(1, 7),
            Point(1, 1),
            135,
            90,
            Point(7, 1),
            id="diagonal-horizontal",
        ),
    ],
)
def test_triangulate(a, b, rot_a, rot_b, expected):
    assert triangulate(a, b, rot_a, rot_b) == pytest.approx(expected)


@pytest.mark.parametrize(
    "a, b, rot_a, rot_b",
    [
        #   /
        # B/
        #
        # A\
        #   \
        pytest.param(Point(1, 1), Point(1, 3), 135, 45, id="diverging"),
        #   \    /
        #    A  /
        #      /
        #     B
        pytest.param(Point(1, 4), Point(1, 1), -45, 45, id="crossing-behind"),
        #    A
        #     \
        # ----B \
        #        \
        pytest.param(Point(1, 4), Point(2, 1), 135, -90, id="pointing-away"),
    ],
)
def test_triangulate_impossible(a, b, rot_a, rot_b):
    with pytest.raises(ImpossibleTriangleError):
        triangulate(a, b, rot_a, rot_b)


@pytest.mark.parametrize(
    "a, b, rot_a, rot_b",
    [
        # |
        # A
        # |
        # B
        pytest.param(Point(1, 4), Point(1, 1), 0, 0, id="same-line"),
        # ||
        # A|
        #  |
        #  B
        pytest.param(Point(1, 4), Point(2, 1), 0, 0, id="parallel"),
        # A
        # |
        # |
        # B
        pytest.param(Point(1, 6), Point(1, 1), 180, 0, id="facing"),
        # A
        #  \
        #   \
        #    B
        pytest.param(Point(1, 7), Point(7, 1), 135, -45, id="facing-diagonal"),
        #     A
        #    /
        #   /
        #  B
        pytest.param(
            Point(7, 7), Point(1, 1), -135, 45, id="facing-diagonal-back"
        ),
    ],
)
def test_triangulate_imprecise(a, b, rot_a, rot_b):
    with pytest.raises(PrecisionError):
        triangulate(a, b, rot_a, rot_b)


@pytest.mark.parametrize(
    "nodes, expected",
    [
        # A____
        #     /
        #    /|
        #   B |
        #     C
        pytest.param([A, B, C], {Point(6, 5): 100}, id="3-agree"),
        #    D
        #     \
        # A____X
        #     /
        #    /|
        #   B |
        #     C
        pytest.param(
            [A, B, C, D],
            {
                Point(6, 5): 50,  # A-B, A-C, B-C out of 6 pairs
                Point(6.1547, 5): 100 / 6,  # A-D
                Point(6.09808, 5.09808): 100 / 6,  # B-D
                Point(6, 5.26795): 100 / 6,  # C-D
            },
            id="3-agree-1-off",
        ),
        #    D
        #     \
        # A____X
        #     /\
        #    /| \
        #   B |  E
        #     C
        pytest.param(
            [A, B, C, D, E],
            {
                Point(6, 5): 60,  # 6 pairs out of 10
                Point(6.1547, 5): 10,
                Point(6.09808, 5.09808): 10,
                Point(6, 5.26795): 10,
                Point(6.36603, 4.63397): 10,  # D-E
            },
            id="4-agree-1-off",
        ),
        # A____X
        #     /\
        #    /| \
        #   B |  E
        #     C
        pytest.param([A, B, C, E], {Point(6, 5): 100}, id="4-agree"),
    ],
)
def test_triangulate_many(nodes, expected):
    # flat (x, y, score) numbers: approx doesn't look inside nested points
    def flat(scores):
        return [v for p, s in sorted(scores.items()) for v in (*p, s)]

    assert flat(triangulate_many(nodes)) == pytest.approx(flat(expected))
