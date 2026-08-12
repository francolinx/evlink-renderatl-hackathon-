"""Optimizer must handle the verified ATL->Nashville numbers BEFORE wiring to Gemini:
248.7 mi, 42% SOC, Ioniq 5-class (303 mi rated / 77.4 kWh) -> 1-2 stops, feasible."""
from app.models import ChargerCandidate
from app.optimizer import optimize

RATED, KWH = 303.0, 77.4
TOTAL = 248.7


def stations_every(spacing_mi: float, total: float = TOTAL, ports: int = 4):
    out, mi = [], spacing_mi
    i = 0
    while mi < total - 5:
        out.append(ChargerCandidate(
            name=f"Test DCFC {i}", lat=34.0, lon=-85.0, dcfc_ports=ports,
            connectors=["J1772COMBO", "CHADEMO"], network="TestNet",
            route_mi=round(mi, 1), detour_mi=0.5))
        mi += spacing_mi
        i += 1
    return out


def test_atl_nashville_produces_1_to_2_stops():
    stops, arrival, feasible, reason = optimize(
        TOTAL, stations_every(12.0), RATED, KWH, current_soc=42.0, min_soc=15.0)
    assert feasible, reason
    assert 1 <= len(stops) <= 2, [s.charger.route_mi for s in stops]
    assert arrival >= 15
    for s in stops:
        assert s.arrive_soc >= 14  # rounding tolerance on the 15% floor
        assert s.depart_soc <= 80
        assert s.charge_min >= 1
        assert s.depart_soc > s.arrive_soc


def test_charge_math_is_consistent():
    stops, _, feasible, _ = optimize(
        TOTAL, stations_every(12.0), RATED, KWH, current_soc=42.0, min_soc=15.0)
    assert feasible
    s = stops[0]
    expect_kwh = (s.depart_soc - s.arrive_soc) / 100 * KWH
    assert abs(s.added_kwh - expect_kwh) < 1.5  # rounding of SOCs
    assert abs(s.charge_min - s.added_kwh / 100.0 * 60) <= 1


def test_no_stop_needed_when_soc_high():
    stops, arrival, feasible, _ = optimize(
        100.0, stations_every(15.0, total=100), RATED, KWH, current_soc=90.0, min_soc=15.0)
    assert feasible and stops == [] and arrival > 15


def test_infeasible_when_no_chargers_in_reach():
    stops, _, feasible, reason = optimize(
        TOTAL, [], RATED, KWH, current_soc=42.0, min_soc=15.0)
    assert not feasible
    assert reason and "charger" in reason.lower()


def test_infeasible_when_gap_too_large():
    # single charger beyond the reachable window from 42% SOC (floor at ~73.6 mi)
    far = [ChargerCandidate(name="Too Far", lat=35.0, lon=-86.0, dcfc_ports=8,
                            connectors=["J1772COMBO"], network="X",
                            route_mi=150.0, detour_mi=0.2)]
    stops, _, feasible, reason = optimize(TOTAL, far, RATED, KWH, 42.0, 15.0)
    assert not feasible and reason


def test_low_start_soc_multiple_stops():
    stops, arrival, feasible, reason = optimize(
        TOTAL, stations_every(10.0), RATED, KWH, current_soc=20.0, min_soc=15.0)
    assert feasible, reason
    assert len(stops) >= 2
    assert arrival >= 15
