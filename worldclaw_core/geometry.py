from __future__ import annotations

import math
from collections.abc import Sequence

Point3 = Sequence[float]


def _distance(a: Point3, b: Point3) -> float:
    return math.sqrt(sum((float(a[index]) - float(b[index])) ** 2 for index in range(3)))


def circle_radial_error(points: Sequence[Point3], center: Point3) -> float:
    """Maximum absolute radial deviation from the mean radius in 3D."""
    if len(points) < 3:
        raise ValueError("Circle audit requires at least three points")
    radii = [_distance(point, center) for point in points]
    mean = sum(radii) / len(radii)
    return max(abs(radius - mean) for radius in radii)


def planarity_error(points: Sequence[Point3], normal: Point3 = (0.0, 0.0, 1.0)) -> float:
    """Maximum point-to-plane deviation using a caller-supplied reference normal."""
    if len(points) < 3:
        raise ValueError("Planarity audit requires at least three points")
    length = math.sqrt(sum(float(value) ** 2 for value in normal))
    if length == 0:
        raise ValueError("Plane normal must be non-zero")
    unit = [float(value) / length for value in normal]
    origin = points[0]
    distances = [
        abs(sum((float(point[index]) - float(origin[index])) * unit[index] for index in range(3)))
        for point in points
    ]
    return max(distances)


def line_deviation(points: Sequence[Point3]) -> float:
    """Maximum perpendicular distance to the line through first and last points."""
    if len(points) < 2:
        raise ValueError("Line audit requires at least two points")
    start, end = points[0], points[-1]
    direction = [float(end[index]) - float(start[index]) for index in range(3)]
    length_sq = sum(value * value for value in direction)
    if length_sq == 0:
        raise ValueError("Line endpoints must be distinct")
    maximum = 0.0
    for point in points:
        offset = [float(point[index]) - float(start[index]) for index in range(3)]
        scale = sum(offset[index] * direction[index] for index in range(3)) / length_sq
        closest = [float(start[index]) + direction[index] * scale for index in range(3)]
        maximum = max(maximum, _distance(point, closest))
    return maximum


def verticality_error_deg(start: Point3, end: Point3, up: Point3 = (0.0, 0.0, 1.0)) -> float:
    direction = [float(end[index]) - float(start[index]) for index in range(3)]
    length = math.sqrt(sum(value * value for value in direction))
    up_length = math.sqrt(sum(float(value) ** 2 for value in up))
    if not length or not up_length:
        raise ValueError("Verticality vectors must be non-zero")
    cosine = abs(
        sum(direction[index] * float(up[index]) for index in range(3)) / (length * up_length)
    )
    return math.degrees(math.acos(max(-1.0, min(1.0, cosine))))
