from __future__ import annotations

import math


def distance_km(latitude: float, longitude: float, other_latitude: float, other_longitude: float) -> float:
    """Great-circle distance between two points in kilometres."""
    radius = 6371.0
    lat1, lat2 = math.radians(latitude), math.radians(other_latitude)
    delta_lat = lat2 - lat1
    delta_lon = math.radians(other_longitude - longitude)
    arc = math.sin(delta_lat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(delta_lon / 2) ** 2
    arc = min(1.0, max(0.0, arc))
    return radius * 2 * math.atan2(math.sqrt(arc), math.sqrt(1 - arc))


def bounding_box(
    latitude: float,
    longitude: float,
    radius_km: float,
) -> tuple[float, float, list[tuple[float, float]]]:
    """Return south, north and one or more longitude ranges.

    Longitude ranges are split when the search circle crosses the antimeridian.
    Distances are still verified precisely after the coarse box query.
    """
    lat_delta = radius_km / 110.574
    lon_delta = min(
        180.0,
        radius_km / max(111.320 * abs(math.cos(math.radians(latitude))), 0.01),
    )
    south = max(-90.0, latitude - lat_delta)
    north = min(90.0, latitude + lat_delta)
    west = longitude - lon_delta
    east = longitude + lon_delta

    if west < -180:
        ranges = [(west + 360, 180.0), (-180.0, east)]
    elif east > 180:
        ranges = [(west, 180.0), (-180.0, east - 360)]
    else:
        ranges = [(west, east)]
    return south, north, ranges
