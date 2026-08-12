"""plan_ev_trip: composes vehicle -> route -> chargers -> optimizer server-side,
so the deterministic chain never depends on the model sequencing five calls."""
from typing import Callable, List, Optional

from . import chargers as chg
from . import routing
from .geo import geocode, nearest_city_label
from .models import TripPlan, VehicleState
from .optimizer import CHARGE_KW, MAX_DEPART_SOC, SAFETY, optimize
from .vehicle import BATTERY_KWH, RATED_RANGE_MI, get_vehicle_state

StepFn = Callable[[str, str, str], None]  # (step_key, state, detail)


def _noop(step: str, state: str, detail: str = "") -> None:
    pass


def plan_ev_trip(destination: str,
                 min_soc_pct: int = 15,
                 preference: str = "minimize charging time",
                 vehicle: Optional[VehicleState] = None,
                 on_step: StepFn = _noop) -> TripPlan:
    assumptions: List[str] = []
    min_soc = max(5, min(50, int(min_soc_pct or 15)))

    on_step("vehicle", "running", "")
    if vehicle is None:
        vehicle = get_vehicle_state(assumptions)
    else:
        assumptions.append("Vehicle: state from the connected demo vehicle"
                           if vehicle.source == "smartcar_simulator"
                           else "Vehicle: static demo profile (Smartcar not connected)")
    origin_label = nearest_city_label(vehicle.lat, vehicle.lon) + " (vehicle location)"
    on_step("vehicle", "done", f"{vehicle.make} {vehicle.model} @ {vehicle.battery_pct:.0f}%")

    dest = geocode(destination)
    if not dest:
        on_step("route", "error", f"unknown destination '{destination}'")
        assumptions.append("Destination geocoding: built-in southeastern-US city table")
        return TripPlan(
            origin=origin_label, destination=destination, total_mi=0, drive_min=0,
            stops=[], arrival_soc=round(vehicle.battery_pct), feasible=False,
            assumptions=assumptions,
            reason=(f"I don't have coordinates for '{destination}'. Tonight's build geocodes "
                    "these southeastern cities: Nashville, Chattanooga, Knoxville, Memphis, "
                    "Birmingham, Huntsville, Charlotte, Asheville, Savannah, Macon, Augusta, "
                    "Greenville, Columbia, Atlanta."))
    dlat, dlon, dstate, dlabel = dest

    on_step("route", "running", "")
    okey = nearest_city_label(vehicle.lat, vehicle.lon).split(",")[0].strip().lower().replace(" ", "")
    route = routing.get_route((vehicle.lat, vehicle.lon), (dlat, dlon),
                              okey or "origin", dlabel.split(",")[0].lower(), assumptions)
    total_mi = round(route["total_mi"], 1)
    on_step("route", "done", f"{total_mi} mi, {route['drive_min']/60:.1f} h")

    on_step("chargers", "running", "")
    ostate = geocode(okey)[2] if geocode(okey) else "GA"
    states = sorted({ostate, dstate})
    stations = chg.fetch_stations(states, assumptions)
    candidates = chg.match_to_route(stations, route["polyline"])
    on_step("chargers", "done", f"{len(candidates)} CCS DCFC within 3 mi of route")

    on_step("optimize", "running", "")
    stops, arrival_soc, feasible, reason = optimize(
        total_mi=total_mi, candidates=candidates,
        rated_range_mi=RATED_RANGE_MI, battery_kwh=BATTERY_KWH,
        current_soc=vehicle.battery_pct, min_soc=min_soc)
    on_step("optimize", "done" if feasible else "error",
            f"{len(stops)} stop(s), arrive {arrival_soc}%" if feasible else (reason or "infeasible"))

    assumptions += [
        f"Demo vehicle energy model: {RATED_RANGE_MI:.0f} mi rated range, {BATTERY_KWH} kWh pack (Ioniq 5-class)",
        f"{(1-SAFETY)*100:.0f}% consumption safety margin applied to all range math",
        f"Effective DC fast-charge rate {CHARGE_KW:.0f} kW (per-port kW not in the AFDC dataset)",
        f"Stops limited to CCS (J1772COMBO) stations with >=1 DC fast port, detour <= {chg.MAX_DETOUR_MI:.0f} mi off route",
        f"Charge ceiling {MAX_DEPART_SOC:.0f}% SOC (fast-charge taper); floor {min_soc}% per your request",
        f"Preference applied: {preference or 'minimize charging time'} (farthest reachable stop, fewest stops)",
        "Destination geocoding: built-in southeastern-US city table",
    ]
    return TripPlan(
        origin=origin_label, destination=dlabel, total_mi=total_mi,
        drive_min=round(route["drive_min"]),
        stops=stops, arrival_soc=max(0, arrival_soc), feasible=feasible,
        assumptions=assumptions, reason=reason,
    )
