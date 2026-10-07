from math import pi
from typing import NamedTuple


class Point(NamedTuple):
    """A named tuple to represent 2d points.

    Attributes:
        x: The x coordinate.
        y: The y coordinate.
    """

    x: float
    y: float


class Node(NamedTuple):
    """A named tuple to represent a panoramax node.


    Attributes:
        coordinate: 2d coordinates of the node.
        rotation: rotation relative to north to target.
    """

    coordinate: Point
    rotation: float


def rad(degrees: float) -> float:
    """Convert degrees to radians

    Args:
        degrees: The degrees.

    Returns:
        The degrees as radians.
    """
    return degrees * pi / 180
