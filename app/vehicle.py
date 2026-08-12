"""Vehicle state: Smartcar test-mode/Simulator first, labeled static profile as fallback."""
import base64
import json
import os
import time
from typing import List, Optional
from urllib.parse import urlencode

import httpx

from .models import VehicleState

TOKENS_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           ".smartcar_tokens.json")
CONNECT_URL = "https://connect.smartcar.com/oauth/authorize"
TOKEN_URL = "https://auth.smartcar.com/oauth/token"
API = "https://api.smartcar.com/v2.0"
SCOPES = "read_vehicle_info read_battery read_location"

# Ioniq 5-class demo profile (also provides rated range / pack size for the optimizer)
RATED_RANGE_MI = 303.0
BATTERY_KWH = 77.4
STATIC_PROFILE = dict(make="Hyundai", model="IONIQ 5 (demo profile)", year=2024,
                      battery_pct=42.0, lat=33.7756, lon=-84.3963)  # Midtown Atlanta


def _env(name: str) -> str:
    return os.environ.get(name, "").strip()


def smartcar_configured() -> bool:
    return bool(_env("SMARTCAR_CLIENT_ID") and _env("SMARTCAR_CLIENT_SECRET")
                and _env("SMARTCAR_REDIRECT_URI"))


def build_connect_url(state: str = "evlink") -> str:
    q = {
        "response_type": "code",
        "client_id": _env("SMARTCAR_CLIENT_ID"),
        "redirect_uri": _env("SMARTCAR_REDIRECT_URI"),
        "scope": SCOPES,
        "state": state,
        "mode": _env("SMARTCAR_MODE") or "simulated",
    }
    return f"{CONNECT_URL}?{urlencode(q)}"


def _basic_auth() -> str:
    raw = f"{_env('SMARTCAR_CLIENT_ID')}:{_env('SMARTCAR_CLIENT_SECRET')}"
    return "Basic " + base64.b64encode(raw.encode()).decode()


def _save_tokens(tok: dict) -> None:
    tok["saved_at"] = time.time()
    with open(TOKENS_PATH, "w") as f:
        json.dump(tok, f)


def _load_tokens() -> Optional[dict]:
    if os.path.exists(TOKENS_PATH):
        with open(TOKENS_PATH) as f:
            return json.load(f)
    return None


def exchange_code(code: str) -> dict:
    resp = httpx.post(TOKEN_URL, headers={"Authorization": _basic_auth()}, data={
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": _env("SMARTCAR_REDIRECT_URI"),
    }, timeout=20)
    resp.raise_for_status()
    tok = resp.json()
    _save_tokens(tok)
    return tok


def _refresh(tok: dict) -> dict:
    resp = httpx.post(TOKEN_URL, headers={"Authorization": _basic_auth()}, data={
        "grant_type": "refresh_token",
        "refresh_token": tok["refresh_token"],
    }, timeout=20)
    resp.raise_for_status()
    new_tok = resp.json()
    _save_tokens(new_tok)
    return new_tok


def _access_token() -> Optional[str]:
    tok = _load_tokens()
    if not tok:
        return None
    age = time.time() - tok.get("saved_at", 0)
    if age > tok.get("expires_in", 7200) - 300:
        try:
            tok = _refresh(tok)
        except Exception:  # noqa: BLE001
            return None
    return tok.get("access_token")


def _get(path: str, token: str) -> dict:
    resp = httpx.get(f"{API}{path}", headers={
        "Authorization": f"Bearer {token}",
        "SC-Unit-System": "imperial",
    }, timeout=20)
    resp.raise_for_status()
    return resp.json()


def _static_state(assumptions: Optional[List[str]] = None) -> VehicleState:
    p = STATIC_PROFILE
    if assumptions is not None:
        assumptions.append("Vehicle: static demo profile (Smartcar not connected)")
        assumptions.append(f"Range estimated as rated range ({RATED_RANGE_MI:.0f} mi) x SOC")
    return VehicleState(
        make=p["make"], model=p["model"], year=p["year"],
        battery_pct=p["battery_pct"],
        range_mi=round(RATED_RANGE_MI * p["battery_pct"] / 100, 1),
        lat=p["lat"], lon=p["lon"],
        is_simulated=True, source="static_profile",
    )


def get_vehicle_state(assumptions: Optional[List[str]] = None) -> VehicleState:
    """Live read from the Smartcar simulator; falls back to the labeled static profile."""
    token = _access_token() if smartcar_configured() else None
    if not token:
        return _static_state(assumptions)
    try:
        vehicles = _get("/vehicles", token).get("vehicles", [])
        if not vehicles:
            return _static_state(assumptions)
        vid = vehicles[0]
        attrs = _get(f"/vehicles/{vid}", token)
        battery = _get(f"/vehicles/{vid}/battery", token)
        loc = _get(f"/vehicles/{vid}/location", token)
        pct = round(float(battery["percentRemaining"]) * 100, 1)
        range_mi = battery.get("range")
        notes: List[str] = []
        if range_mi is None:
            range_mi = round(RATED_RANGE_MI * pct / 100, 1)
            notes.append(f"Range estimated as rated range ({RATED_RANGE_MI:.0f} mi) x SOC "
                         "(vehicle did not report range)")
        if assumptions is not None:
            assumptions.append("Vehicle: live Smartcar simulator read (simulated vehicle)")
            assumptions.extend(notes)
        return VehicleState(
            make=attrs.get("make", "Unknown"), model=attrs.get("model", "EV"),
            year=int(attrs.get("year") or 2024),
            battery_pct=pct, range_mi=float(range_mi),
            lat=float(loc["latitude"]), lon=float(loc["longitude"]),
            is_simulated=True, source="smartcar_simulator",
        )
    except Exception:  # noqa: BLE001 - any Smartcar failure degrades honestly
        return _static_state(assumptions)


def connected() -> bool:
    return _load_tokens() is not None
