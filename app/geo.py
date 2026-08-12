"""Geometry helpers + hardcoded southeastern-US geocode table (hackathon scope)."""
import math
from typing import List, Optional, Tuple

EARTH_MI = 3958.8


def haversine_mi(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_MI * math.asin(math.sqrt(a))


# name -> (lat, lon, state, display)
GEOCODE = {
    "atlanta":     (33.7490, -84.3880, "GA", "Atlanta, GA"),
    "nashville":   (36.1627, -86.7816, "TN", "Nashville, TN"),
    "chattanooga": (35.0456, -85.3097, "TN", "Chattanooga, TN"),
    "knoxville":   (35.9606, -83.9207, "TN", "Knoxville, TN"),
    "memphis":     (35.1495, -90.0490, "TN", "Memphis, TN"),
    "birmingham":  (33.5186, -86.8104, "AL", "Birmingham, AL"),
    "huntsville":  (34.7304, -86.5861, "AL", "Huntsville, AL"),
    "charlotte":   (35.2271, -80.8431, "NC", "Charlotte, NC"),
    "asheville":   (35.5951, -82.5515, "NC", "Asheville, NC"),
    "savannah":    (32.0809, -81.0912, "GA", "Savannah, GA"),
    "macon":       (32.8407, -83.6324, "GA", "Macon, GA"),
    "augusta":     (33.4735, -82.0105, "GA", "Augusta, GA"),
    "greenville":  (34.8526, -82.3940, "SC", "Greenville, SC"),
    "columbia":    (34.0007, -81.0348, "SC", "Columbia, SC"),
}


def geocode(name: str) -> Optional[Tuple[float, float, str, str]]:
    key = name.strip().lower().split(",")[0].strip()
    if key in GEOCODE:
        return GEOCODE[key]
    for k, v in GEOCODE.items():  # substring tolerance ("nashville tn", "to nashville")
        if k in key:
            return v
    return None


def nearest_city_label(lat: float, lon: float) -> str:
    best = min(GEOCODE.values(), key=lambda v: haversine_mi(lat, lon, v[0], v[1]))
    d = haversine_mi(lat, lon, best[0], best[1])
    return best[3] if d < 40 else f"{lat:.3f}, {lon:.3f}"


def cumulative_mi(polyline: List[Tuple[float, float]]) -> List[float]:
    """Cumulative distance along a [(lat, lon), ...] polyline."""
    out = [0.0]
    for i in range(1, len(polyline)):
        a, b = polyline[i - 1], polyline[i]
        out.append(out[-1] + haversine_mi(a[0], a[1], b[0], b[1]))
    return out


def downsample(polyline: List[Tuple[float, float]], cum: List[float],
               spacing_mi: float = 0.4) -> Tuple[List[Tuple[float, float]], List[float]]:
    """Thin the polyline to ~spacing_mi between points (station matching speed)."""
    pts, dists = [polyline[0]], [cum[0]]
    for i in range(1, len(polyline)):
        if cum[i] - dists[-1] >= spacing_mi or i == len(polyline) - 1:
            pts.append(polyline[i])
            dists.append(cum[i])
    return pts, dists
