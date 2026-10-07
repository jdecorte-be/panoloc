from .errors import ImpossibleTriangleError, PrecisionError
from .triangulation import triangulate, triangulate_many
from .utils import Node, Point


def test() -> None:
    """Test battery for triangulate function."""
    # 1
    # A
    #  \
    #   \T
    #   /
    #  /
    # B
    point = triangulate(Point(1, 7), Point(1, 1), 135, 45)
    print("1: Expected Point(4.0, 4.0), got", point)
    if point.x == 4 and point.y == 4:
        print("\033[0;42mOK\033[0m")
    else:
        print("\033[0;41mKO\033[0m")

    # 2
    # A
    #  \
    #   \
    #    \T
    #    /
    #   B
    point = triangulate(Point(1, 7), Point(3, 1), 135, 45)
    print("2: Expected Point(5.0, 3.0), got", point)
    if point.x == 5 and point.y == 3:
        print("\033[0;42mOK\033[0m")
    else:
        print("\033[0;41mKO\033[0m")

    # 3  /
    #   /
    # B/
    #
    # A\
    #   \
    #    \
    #     \
    #
    try:
        point = triangulate(Point(1, 1), Point(1, 3), 135, 45)
        print("3: Expected ImpossibleTriangleError, got", point)
        print("\033[0;41mKO\033[0m")
    except ImpossibleTriangleError as e:
        print("3: Expected ImpossibleTriangleError, got", e.__class__.__name__)
        print("\033[0;42mOK\033[0m")

    # 4   \
    #      \
    #       \
    #        \
    #         \
    #          \    /
    #           A  /
    #             /
    #            /
    #           B
    try:
        point = triangulate(Point(1, 4), Point(1, 1), -45, 45)
        print("4: Expected ImpossibleTriangleError, got", point)
        print("\033[0;41mKO\033[0m")
    except ImpossibleTriangleError as e:
        print("4: Expected ImpossibleTriangleError, got", e.__class__.__name__)
        print("\033[0;42mOK\033[0m")

    # 5
    # |
    # |
    # |
    # |
    # A
    # |
    # |
    # |
    # |
    # B
    try:
        point = triangulate(Point(1, 4), Point(1, 1), 0, 0)
        print("5: Expected PrecisionError, got", point)
        print("\033[0;41mKO\033[0m")
    except PrecisionError as e:
        print("5: Expected PrecisionError, got", e.__class__.__name__)
        print("\033[0;42mOK\033[0m")

    # 6
    # ||
    # ||
    # ||
    # ||
    # A|
    #  |
    #  |
    #  |
    #  |
    #  B
    try:
        point = triangulate(Point(1, 4), Point(2, 1), 0, 0)
        print("6: Expected PrecisionError, got", point)
        print("\033[0;41mKO\033[0m")
    except PrecisionError as e:
        print("6: Expected PrecisionError, got", e.__class__.__name__)
        print("\033[0;42mOK\033[0m")

    # 7
    # A
    # |
    # |
    # |
    # |
    # |
    # B
    try:
        point = triangulate(Point(1, 6), Point(1, 1), 180, 0)
        print("7: Expected PrecisionError, got", point)
        print("\033[0;41mKO\033[0m")
    except PrecisionError as e:
        print("7: Expected PrecisionError, got", e.__class__.__name__)
        print("\033[0;42mOK\033[0m")

    # 8
    # A
    #  \
    #   \
    #    \
    #     \
    #      \
    #       B
    try:
        point = triangulate(Point(1, 7), Point(7, 1), 135, -45)
        print("8: Expected PrecisionError, got", point)
        print("\033[0;41mKO\033[0m")
    except PrecisionError as e:
        print("8: Expected PrecisionError, got", e.__class__.__name__)
        print("\033[0;42mOK\033[0m")

    #       8
    #       A
    #      /
    #     /
    #    /
    #   /
    #  /
    # B
    try:
        point = triangulate(Point(7, 7), Point(1, 1), -135, 45)
        print("8: Expected PrecisionError, got", point)
        print("\033[0;41mKO\033[0m")
    except PrecisionError as e:
        print("8: Expected PrecisionError, got", e.__class__.__name__)
        print("\033[0;42mOK\033[0m")

    # 9
    # A--T
    #    |
    #    |
    #    |
    #    |
    #    B
    point = triangulate(Point(1, 7), Point(4, 1), 90, 0)
    print("9: Expected Point(4.0, 7.0), got", point)
    if point.x == 4 and point.y == 7:
        print("\033[0;42mOK\033[0m")
    else:
        print("\033[0;41mKO\033[0m")

    # 10
    #    A
    #    |
    #    |
    #    |
    #    |
    # B__T
    point = triangulate(Point(4, 7), Point(1, 1), 180, 90)
    print("10: Expected Point(4.0, 1.0), got", point)
    if point.x == 4 and point.y == 1:
        print("\033[0;42mOK\033[0m")
    else:
        print("\033[0;41mKO\033[0m")

    # 11
    # A
    #  \
    #   \
    #    \
    #     \
    # B____\
    point = triangulate(Point(1, 7), Point(1, 1), 135, 90)
    print("11: Expected Point(7.0, 1.0), got", point)
    if point.x == 7.0 and point.y == 1:
        print("\033[0;42mOK\033[0m")
    else:
        print("\033[0;41mKO\033[0m")

    # 12
    #    A
    #     \
    #      \
    # ----B \
    #        \
    try:
        point = triangulate(Point(1, 4), Point(2, 1), 135, -90)
        print("12: Expected ImpossibleTriangleError, got", point)
        print("\033[0;41mKO\033[0m")
    except ImpossibleTriangleError as e:
        print(
            "12: Expected ImpossibleTriangleError, got", e.__class__.__name__
        )
        print("\033[0;42mOK\033[0m")
    print()


def test_many() -> None:
    """Test battery for triangulate_many function."""
    # 1
    # A____
    #     /
    #    /|
    #   B |
    #     C
    print("1:")
    for key, value in triangulate_many(
        [
            Node(Point(1, 5), 90),
            Node(Point(3, 2), 45),
            Node(Point(6, 1), 0),
        ]
    ).items():
        print(f"{key}: {value},")
    print()

    # 2
    #    D
    #     \
    # A____X
    #     /
    #    /|
    #   B |
    #     C
    print("2:")
    for key, value in triangulate_many(
        [
            Node(Point(1, 5), 90),
            Node(Point(3, 2), 45),
            Node(Point(6, 1), 0),
            Node(Point(5, 7), 150),
        ]
    ).items():
        print(f"{key}: {value},")
    print()

    # 3
    #    D
    #     \
    # A____X
    #     /\
    #    /| \
    #   B |  E
    #     C
    print("3:")
    for key, value in triangulate_many(
        [
            Node(Point(1, 5), 90),
            Node(Point(3, 2), 45),
            Node(Point(6, 1), 0),
            Node(Point(5, 7), 150),
            Node(Point(9, 2), -45),
        ]
    ).items():
        print(f"{key}: {value},")
    print()

    # 4
    # A____X
    #     /\
    #    /| \
    #   B |  E
    #     C
    print("4:")
    for key, value in triangulate_many(
        [
            Node(Point(1, 5), 90),
            Node(Point(3, 2), 45),
            Node(Point(6, 1), 0),
            Node(Point(9, 2), -45),
        ]
    ).items():
        print(f"{key}: {value},")
    print()
