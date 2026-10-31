"""Bounding-box and court geometry helpers (pure numpy, no CV dependency)."""
from __future__ import annotations

import math

import numpy as np

# FIBA court, metres. Origin = top-left corner seen from the main camera.
COURT_LENGTH = 28.0
COURT_WIDTH = 15.0
BASKETS = ((1.575, 7.5), (COURT_LENGTH - 1.575, 7.5))
THREE_POINT_RADIUS = 6.75
RIM_ZONE_RADIUS = 1.6


def center(b) -> tuple[float, float]:
    return ((b[0] + b[2]) / 2.0, (b[1] + b[3]) / 2.0)


def foot(b) -> tuple[float, float]:
    """Bottom-centre of a player box: the point that touches the floor."""
    return ((b[0] + b[2]) / 2.0, float(b[3]))


def dist(p, q) -> float:
    return math.hypot(p[0] - q[0], p[1] - q[1])


def containment(outer, inner) -> float:
    """Share of `inner`'s area that lies inside `outer`."""
    ix1, iy1 = max(outer[0], inner[0]), max(outer[1], inner[1])
    ix2, iy2 = min(outer[2], inner[2]), min(outer[3], inner[3])
    if ix2 <= ix1 or iy2 <= iy1:
        return 0.0
    area = max((inner[2] - inner[0]) * (inner[3] - inner[1]), 1e-9)
    return (ix2 - ix1) * (iy2 - iy1) / area


def homography(src, dst) -> np.ndarray:
    """Direct linear transform from >=4 point pairs (image -> court)."""
    src = np.asarray(src, float)
    dst = np.asarray(dst, float)
    if len(src) < 4 or len(src) != len(dst):
        raise ValueError("need >=4 matching point pairs")
    rows = []
    for (x, y), (u, v) in zip(src, dst):
        rows.append([-x, -y, -1, 0, 0, 0, u * x, u * y, u])
        rows.append([0, 0, 0, -x, -y, -1, v * x, v * y, v])
    _, _, vt = np.linalg.svd(np.asarray(rows))
    h = vt[-1].reshape(3, 3)
    return h / h[2, 2]


def project(h: np.ndarray, p) -> tuple[float, float]:
    x, y, w = h @ np.array([p[0], p[1], 1.0])
    return (float(x / w), float(y / w))


def court_zone(court_xy) -> str:
    """rim / mid / three, measured from the nearest basket."""
    d = min(dist(court_xy, b) for b in BASKETS)
    if d <= RIM_ZONE_RADIUS:
        return "rim"
    if d < THREE_POINT_RADIUS:
        return "mid"
    return "three"
