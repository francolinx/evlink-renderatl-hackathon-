"""EVLink data contracts."""
from typing import List, Optional

from pydantic import BaseModel


class VehicleState(BaseModel):
    make: str
    model: str
    year: int
    battery_pct: float
    range_mi: Optional[float] = None
    lat: float
    lon: float
    is_simulated: bool = True
    # "smartcar_simulator" when read live from Smartcar test mode,
    # "static_profile" when the labeled static demo profile is in use.
    source: str = "static_profile"


class ChargerCandidate(BaseModel):
    name: str
    lat: float
    lon: float
    dcfc_ports: int
    connectors: List[str]
    network: str
    route_mi: float
    detour_mi: float
    city: str = ""
    state: str = ""


class OptimizedStop(BaseModel):
    charger: ChargerCandidate
    arrive_soc: int
    depart_soc: int
    charge_min: int
    added_kwh: float


class TripPlan(BaseModel):
    origin: str
    destination: str
    total_mi: float
    drive_min: int
    stops: List[OptimizedStop]
    arrival_soc: int
    feasible: bool
    assumptions: List[str]
    reason: Optional[str] = None  # plain-English reason when feasible=false
