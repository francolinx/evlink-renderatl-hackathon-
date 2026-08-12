"""Route retrieval: live OSRM -> cached fixture -> straight-line estimate."""
import json
import os
import time
from typing import Dict, List, Tuple

import httpx

from .geo import haversine_mi

FIXTURES_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fixtures")
OSRM_URL = "https://router.project-osrm.org/route/v1/driving/{lon1},{lat1};{lon2},{lat2}"


def _fixture_path(okey: str, dkey: str) -> str:
    return os.path.join(FIXTURES_DIR, f"route_{okey}_{dkey}.json")


def _parse_osrm(data: dict) -> Dict:
    r = data["routes"][0]
    coords = r["geometry"]["coordinates"]  # [lon, lat]
    return {
        "total_mi": r["distance"] / 1609.34,
        "drive_min": r["duration"] / 60.0,
        "polyline": [(lat, lon) for lon, lat in coords],
    }


def _straight_line(o: Tuple[float, float], d: Tuple[float, float]) -> Dict:
    direct = haversine_mi(o[0], o[1], d[0], d[1])
    total = direct * 1.25
    n = 60
    poly: List[Tuple[float, float]] = [
        (o[0] + (d[0] - o[0]) * i / n, o[1] + (d[1] - o[1]) * i / n) for i in range(n + 1)
    ]
    return {"total_mi": total, "drive_min": total / 55.0 * 60, "polyline": poly}


def get_route(o: Tuple[float, float], d: Tuple[float, float],
              okey: str, dkey: str, assumptions: List[str]) -> Dict:
    """Returns {total_mi, drive_min, polyline[(lat,lon)]}, appending source notes."""
    url = OSRM_URL.format(lon1=f"{o[1]:.5f}", lat1=f"{o[0]:.5f}",
                          lon2=f"{d[1]:.5f}", lat2=f"{d[0]:.5f}")
    params = {"overview": "full", "geometries": "geojson"}
    last_err = None
    for attempt in range(3):
        try:
            resp = httpx.get(url, params=params, timeout=20)
            resp.raise_for_status()
            data = resp.json()
            if data.get("code") != "Ok":
                raise RuntimeError(f"OSRM code={data.get('code')}")
            os.makedirs(FIXTURES_DIR, exist_ok=True)
            with open(_fixture_path(okey, dkey), "w") as f:
                json.dump(data, f)
            assumptions.append("Route: live OSRM driving route")
            return _parse_osrm(data)
        except Exception as e:  # noqa: BLE001 - any network/parse failure falls through
            last_err = e
            time.sleep(1 + attempt)
    fp = _fixture_path(okey, dkey)
    if os.path.exists(fp):
        with open(fp) as f:
            data = json.load(f)
        assumptions.append("Route: cached OSRM fixture (live OSRM unreachable)")
        return _parse_osrm(data)
    assumptions.append(f"Route: straight-line estimate x1.25 (OSRM unreachable: {type(last_err).__name__})")
    return _straight_line(o, d)
