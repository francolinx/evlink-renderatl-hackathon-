from app.chargers import match_to_route
from app.geo import cumulative_mi, geocode, haversine_mi


def test_geocode_table():
    assert geocode("Nashville")[2] == "TN"
    assert geocode("nashville, tn")[3] == "Nashville, TN"
    assert geocode("  Chattanooga ")[2] == "TN"
    assert geocode("Tokyo") is None


def test_haversine_atl_nashville():
    a, n = geocode("atlanta"), geocode("nashville")
    d = haversine_mi(a[0], a[1], n[0], n[1])
    assert 200 < d < 220  # straight line ~214 mi


def synthetic_polyline(n=200):
    a, d = geocode("atlanta"), geocode("nashville")
    return [(a[0] + (d[0] - a[0]) * i / n, a[1] + (d[1] - a[1]) * i / n)
            for i in range(n + 1)]


def test_match_to_route_on_and_off_route():
    poly = synthetic_polyline()
    cum = cumulative_mi(poly)
    mid = len(poly) // 2
    on_route = {"attributes": {
        "station_name": "Mid DCFC", "ev_dc_fast_num": 6,
        "ev_connector_types": "CHADEMO J1772COMBO", "ev_network": "Electrify America",
        "latitude": poly[mid][0], "longitude": poly[mid][1], "city": "X", "state": "GA"}}
    off_route = {"attributes": {
        "station_name": "Far Away", "ev_dc_fast_num": 6,
        "ev_connector_types": "J1772COMBO", "ev_network": "EVgo",
        "latitude": poly[mid][0] + 0.5, "longitude": poly[mid][1], "city": "Y", "state": "GA"}}
    tesla_only = {"attributes": {
        "station_name": "Supercharger", "ev_dc_fast_num": 12,
        "ev_connector_types": "TESLA", "ev_network": "Tesla",
        "latitude": poly[mid][0], "longitude": poly[mid][1], "city": "Z", "state": "GA"}}
    got = match_to_route([on_route, off_route, tesla_only], poly)
    assert len(got) == 1
    c = got[0]
    assert c.name == "Mid DCFC"
    assert c.detour_mi < 0.5
    assert abs(c.route_mi - cum[mid]) < 1.0
    assert "J1772COMBO" in c.connectors
