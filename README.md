# ⚡ EVLink

**The physical EV as an AI-usable tool surface.** EVLink connects a driver's (simulated) electric
vehicle to Gemini through genuine function calling: you type *"Get me to Nashville. Keep me above
15% and minimize charging time,"* Gemini reads the car's real state via a tool call, a
**deterministic** backend plans charging stops from real route and charger data, and the UI renders
the itinerary. Trip planning is the first application — the point is the car itself as a tool AI
can understand.

Built entirely during **Hack RenderATL 2026** (Aug 12, 2026).

## Architecture

```
UI ──text──► POST /api/chat ──► Gemini 2.5 Flash (function-calling loop)
                                  │ tool 1: get_vehicle_state ─► Smartcar test-mode vehicle
                                  │ tool 2: plan_ev_trip ──────► OSRM route → AFDC chargers
                                  │                               → deterministic optimizer → TripPlan
                                  ◄─ structured tool results ──┘
              ◄── Gemini itinerary text + TripPlan JSON ──► UI renders result
GET /api/vehicle ─► vehicle card on load
```

Exactly two Gemini tools. `plan_ev_trip` composes routing + chargers + optimization **server-side**,
so the deterministic chain never depends on the model sequencing five calls.

## Gemini integration (genuine function calling)

`gemini-2.5-flash` via REST `v1beta:generateContent` with two `functionDeclarations`. Every
`functionCall` the model emits is executed against the real backend and its structured result
returned as a `functionResponse`; the UI logs each call it actually made (`🔧 Gemini →
plan_ev_trip({...})`). Gemini handles **intent**; it is instructed to never estimate battery,
range, distance, or charging times itself — all numbers come from tool results. If
`GEMINI_API_KEY` is unset the app runs in a clearly-labeled *direct mode* (no LLM, never
simulated tool calls).

## Vehicle (Smartcar — simulated, disclosed)

The vehicle is a **Smartcar test-mode / Simulator** vehicle (Ioniq 5-class, ~42% SOC, Atlanta) —
a real OAuth + REST integration against `api.smartcar.com`, reading battery, range, and location
from a simulated car. The UI badges it as a *connected demo vehicle*. Without Smartcar credentials
the app falls back to a static profile badged **"demo vehicle profile (static)"** — every state is
labeled on screen; nothing simulated is ever presented as live.

## Deterministic optimizer

Greedy farthest-reachable-stop planner (fewest stops ⇒ minimal charging time), 80% charge ceiling,
user-set floor (default 15%). Battery math is code, not LLM output. Assumptions are **always**
returned and **always** rendered in the UI:

- Ioniq 5-class energy model: 303 mi rated range, 77.4 kWh pack
- 10% consumption safety margin on all range math
- Effective 100 kW DC fast-charge rate (per-port kW not in the AFDC dataset)
- CCS (J1772COMBO) stations only, ≥1 DC fast port, ≤3 mi detour off route
- Charge ceiling 80% SOC (taper), floor = requested minimum
- Destination geocoding via a built-in southeastern-US city table (hackathon scope)
- Route/charger source (live vs cached fixture vs straight-line estimate) is always stated

## Data sources (keyless)

- **Routing:** [OSRM demo server](https://router.project-osrm.org) — first successful response is
  cached to `fixtures/` and used as a labeled fallback if OSRM rate-limits mid-demo; final
  fallback is a labeled straight-line ×1.25 estimate.
- **Chargers:** US DOE **AFDC** (Alternative Fueling Stations) via the USDOT **NTAD** ArcGIS
  mirror — public, in-service DC fast stations, filtered to the trip's states, matched to the
  route polyline (distance-along-route + detour), also fixture-cached on first success.

## Run it

```bash
pip install -r requirements.txt
cp .env.example .env          # paste GEMINI_API_KEY (and Smartcar creds if you have them)
uvicorn app.main:app --port 8000
# open http://localhost:8000 and type:
#   Get me to Nashville. Keep me above 15% and minimize charging time.
```

- Gemini key: https://aistudio.google.com/apikey → `GEMINI_API_KEY`
- Smartcar (optional): set `SMARTCAR_CLIENT_ID/SECRET/REDIRECT_URI` (redirect URI must exactly
  match one registered in your Smartcar dashboard, e.g. `http://localhost:8000/callback`), then
  click **Connect vehicle via Smartcar** in the UI.
- Deploy: `render.yaml` included (`uvicorn` web service; set the same env vars in Render).

Tests: `python -m pytest` — 11 tests including the ATL→Nashville optimizer validation
(248.7 mi @ 42% SOC → 1–2 stops).

## Devpost

Hack RenderATL 2026 submission: **[paste Devpost link here after submitting]**

## Endpoints

| Route | Purpose |
|---|---|
| `GET /` | single-file UI (no build step) |
| `GET /api/vehicle` | vehicle card state |
| `POST /api/chat` | starts a Gemini job → `{job_id}` |
| `GET /api/jobs/{id}` | real step progress + tool-call log + result |
| `POST /api/plan` | deterministic planner directly (no LLM) |
| `GET /auth/login` → `/callback` | Smartcar Connect OAuth |
