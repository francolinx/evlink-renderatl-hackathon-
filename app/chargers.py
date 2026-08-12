"""DC fast chargers from US DOE AFDC (USDOT NTAD ArcGIS mirror, keyless)."""
import json
import os
import re
import time
from typing import Dict, List, Tuple

import httpx

from .geo import cumulative_mi, downsample, haversine_mi
from .models import ChargerCandidate

FIXTURES_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fixtures")
AFDC_URL = ("https://services.arcgis.com/xOi1kZaI0eWDREZv/ArcGIS/rest/services/"
            "Alternative_Fueling_Stations/FeatureServer/0/query")
OUT_FIELDS = ("station_name,ev_dc_fast_num,ev_connector_types,ev_network,"
              "latitude,longitude,city,state")
MAX_DETOUR_MI = 3.0


def _fixture_path(states: List[str]) -> str:
    return os.path.join(FIXTURES_DIR, f"chargers_{'_'.join(sorted(states))}.json")


def fetch_stations(states: List[str], assumptions: List[str]) -> List[dict]:
    """All public, in-service DCFC stations in the given states (paged)."""
    where = ("fuel_type_code='ELEC' AND status_code='E' AND access_code='public' "
             "AND ev_dc_fast_num > 0 AND state IN ({})").format(
                 ",".join(f"'{s}'" for s in sorted(states)))
    feats: List[dict] = []
    try:
        offset = 0
        for _ in range(6):  # up to 6000 stations
            resp = httpx.post(AFDC_URL, data={
                "where": where, "outFields": OUT_FIELDS, "f": "json",
                "resultOffset": offset, "resultRecordCount": 1000,
            }, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            if "error" in data:
                raise RuntimeError(str(data["error"])[:200])
            page = data.get("features", [])
            feats.extend(page)
            if len(page) < 1000:
                break
            offset += 1000
        os.makedirs(FIXTURES_DIR, exist_ok=True)
        with open(_fixture_path(states), "w") as f:
            json.dump({"features": feats}, f)
        assumptions.append(f"Chargers: live US DOE AFDC data ({len(feats)} DCFC stations in {'/'.join(sorted(states))})")
        return feats
    except Exception as e:  # noqa: BLE001
        fp = _fixture_path(states)
        if os.path.exists(fp):
            with open(fp) as f:
                feats = json.load(f)["features"]
            assumptions.append(f"Chargers: cached AFDC fixture ({len(feats)} stations; live API unreachable)")
            return feats
        assumptions.append(f"Chargers: AFDC unreachable ({type(e).__name__}) and no cached fixture")
        return []


def _connectors(raw) -> List[str]:
    if raw is None:
        return []
    return [t for t in re.split(r"[^A-Z0-9]+", str(raw).upper()) if t]


def match_to_route(stations: List[dict],
                   polyline: List[Tuple[float, float]]) -> List[ChargerCandidate]:
    """route_mi (distance along route) + detour_mi per station; keep detour <= 3 mi, CCS only."""
    cum = cumulative_mi(polyline)
    pts, dists = downsample(polyline, cum, spacing_mi=0.4)
    out: List[ChargerCandidate] = []
    for f in stations:
        a = f.get("attributes", f)
        lat, lon = a.get("latitude"), a.get("longitude")
        if lat is None or lon is None:
            continue
        best_d, best_i = 1e9, 0
        for i, (plat, plon) in enumerate(pts):
            # cheap prefilter: skip points >0.1 deg (~7mi) away in either axis
            if abs(plat - lat) > 0.1 or abs(plon - lon) > 0.1:
                continue
            d = haversine_mi(lat, lon, plat, plon)
            if d < best_d:
                best_d, best_i = d, i
        if best_d > MAX_DETOUR_MI:
            continue
        conns = _connectors(a.get("ev_connector_types"))
        if "J1772COMBO" not in conns:  # CCS1 required for the demo vehicle
            continue
        out.append(ChargerCandidate(
            name=a.get("station_name") or "Unnamed station",
            lat=lat, lon=lon,
            dcfc_ports=int(a.get("ev_dc_fast_num") or 0),
            connectors=conns,
            network=a.get("ev_network") or "Unknown",
            route_mi=round(dists[best_i], 1),
            detour_mi=round(best_d, 2),
            city=a.get("city") or "", state=a.get("state") or "",
        ))
    out.sort(key=lambda c: c.route_mi)
    return out
