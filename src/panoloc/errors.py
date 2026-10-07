class TriangulationError(Exception):
    """Error class for triangulisation."""

    def __init__(self, *_args: object) -> None:
        """Construct TriangulisationError."""
        super().__init__(*_args)


class PrecisionError(TriangulationError):
    """Error class for precision.

    When two points are looking in the exact same directions.
    """

    def __init__(self, *_args: object) -> None:
        """Construct PrecisionError."""
        super().__init__(*_args)


class ImpossibleTriangleError(TriangulationError):
    """Error class for impossible triangulations.

    When two points are looking in the exact same directions.
    """

    def __init__(self, *_args: object) -> None:
        """Construct ImpossibleTriangleError."""
        super().__init__(*_args)
