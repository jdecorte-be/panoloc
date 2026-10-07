import math
from panoloc.bbox import M_PER_DEG_LAT


def signed_angle(a: float) -> float:
    return (a + 180) % 360 - 180


def bearing_distance(
    lon: float, lat: float, lon2: float, lat2: float
) -> tuple[float, float]:
    dx = (lon2 - lon) * M_PER_DEG_LAT * math.cos(math.radians(lat))
    dy = (lat2 - lat) * M_PER_DEG_LAT
    return signed_angle(math.degrees(math.atan2(dx, dy))), math.hypot(dx, dy)


def local_to_lonlat(
    lon: float, lat: float, radius_m: float, x: float, y: float
) -> list[float]:
    m_per_deg_lon = M_PER_DEG_LAT * math.cos(math.radians(lat))
    return [
        lon + (x - radius_m) / m_per_deg_lon,
        lat + (y - radius_m) / M_PER_DEG_LAT,
    ]
