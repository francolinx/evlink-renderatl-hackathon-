"""Full planner composition with synthetic route + stations (network stubbed out)."""
from app import planner
from app.geo import geocode


def synth_route(o, d, okey, dkey, assumptions):
    assumptions.append("Route: synthetic test route")
    n = 100
    poly = [(o[0] + (d[0] - o[0]) * i / n, o[1] + (d[1] - o[1]) * i / n) for i in range(n + 1)]
    return {"total_mi": 248.7, "drive_min": 4.7 * 60, "polyline": poly}


def synth_stations(states, assumptions):
    assumptions.append("Chargers: synthetic test stations")
    a, d = geocode("atlanta"), geocode("nashville")
    feats = []
    for i in range(1, 20):  # stations sprinkled directly on the straight line
        t = i / 20
        feats.append({"attributes": {
            "station_name": f"Synth DCFC {i}", "ev_dc_fast_num": 4,
            "ev_connector_types": "J1772COMBO CHADEMO", "ev_network": "TestNet",
            "latitude": a[0] + (d[0] - a[0]) * t, "longitude": a[1] + (d[1] - a[1]) * t,
            "city": "X", "state": "GA"}})
    return feats


def test_full_planner_chain(monkeypatch):
    monkeypatch.setattr(planner.routing, "get_route", synth_route)
    monkeypatch.setattr(planner.chg, "fetch_stations", synth_stations)
    plan = planner.plan_ev_trip("Nashville", 15, "minimize charging time")
    assert plan.feasible, plan.reason
    assert 1 <= len(plan.stops) <= 2
    assert plan.arrival_soc >= 15
    assert plan.total_mi == 248.7
    assert plan.destination == "Nashville, TN"
    assert len(plan.assumptions) >= 6
    for s in plan.stops:
        assert s.depart_soc <= 80 and s.charge_min >= 1


def test_unknown_destination_is_graceful():
    plan = planner.plan_ev_trip("Tokyo", 15)
    assert not plan.feasible
    assert plan.reason and "Tokyo" in plan.reason
    assert plan.assumptions
