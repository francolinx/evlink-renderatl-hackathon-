"""Deterministic charging-stop optimizer. Gemini never computes any of this.

Consumption model (safety factor applied consistently to all SOC math):
    effective_range     = rated_range_mi * 0.90
    eff_mi_per_kwh      = effective_range / battery_kwh
    soc_drop(miles)     = miles / effective_range * 100
Charging: effective 100 kW flat rate (per-port kW not in the AFDC dataset).
"""
from typing import List, Optional, Tuple

from .models import ChargerCandidate, OptimizedStop

SAFETY = 0.90
CHARGE_KW = 100.0
MAX_DEPART_SOC = 80.0
MIN_HOP_MI = 20.0  # don't stop within the first 20 mi of the current position
MAX_STOPS = 6


def optimize(total_mi: float,
             candidates: List[ChargerCandidate],
             rated_range_mi: float,
             battery_kwh: float,
             current_soc: float,
             min_soc: float) -> Tuple[List[OptimizedStop], int, bool, Optional[str]]:
    """Returns (stops, arrival_soc, feasible, reason)."""
    eff_range = rated_range_mi * SAFETY

    def soc_drop(miles: float) -> float:
        return miles / eff_range * 100.0

    def soc_at_dest(pos: float, soc: float) -> float:
        return soc - soc_drop(total_mi - pos)

    pos, soc = 0.0, float(current_soc)
    stops: List[OptimizedStop] = []

    while soc_at_dest(pos, soc) < min_soc:
        if len(stops) >= MAX_STOPS:
            return stops, round(soc_at_dest(pos, soc)), False, \
                f"More than {MAX_STOPS} charging stops required — trip not planned."
        reach = pos + (soc - min_soc) / 100.0 * eff_range
        window = [c for c in candidates
                  if pos + MIN_HOP_MI < c.route_mi <= reach and c.dcfc_ports > 0]
        if not window and reach - pos <= MIN_HOP_MI:
            # battery too low to honor the 20-mi minimum hop — take any charger ahead
            window = [c for c in candidates
                      if pos < c.route_mi <= reach and c.dcfc_ports > 0]
        if not window:
            miles_left = round(total_mi - pos)
            return stops, round(soc_at_dest(pos, soc)), False, (
                f"No compatible DC fast charger within reach "
                f"(needed one between mile {round(pos + MIN_HOP_MI)} and mile {round(reach)} "
                f"of the route; {miles_left} mi still to go). "
                f"Try a lower minimum battery or a different destination.")
        # farthest reachable stop; tiebreak by most DC fast ports
        cand = max(window, key=lambda c: (c.route_mi, c.dcfc_ports))
        arrive_soc = soc - soc_drop(cand.route_mi - pos)
        soc_needed_rest = soc_drop(total_mi - cand.route_mi)
        depart_soc = min(MAX_DEPART_SOC, soc_needed_rest + min_soc + 5.0)
        depart_soc = max(depart_soc, arrive_soc)
        added_kwh = max(0.0, (depart_soc - arrive_soc) / 100.0 * battery_kwh)
        charge_min = added_kwh / CHARGE_KW * 60.0
        stops.append(OptimizedStop(
            charger=cand,
            arrive_soc=round(arrive_soc),
            depart_soc=round(depart_soc),
            charge_min=max(1, round(charge_min)) if added_kwh > 0 else 0,
            added_kwh=round(added_kwh, 1),
        ))
        pos, soc = cand.route_mi, depart_soc

    return stops, round(soc_at_dest(pos, soc)), True, None
