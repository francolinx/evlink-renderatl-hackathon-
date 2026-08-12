"""Gemini Flash function-calling loop (REST v1beta:generateContent).

Two genuine tools; every functionCall the model emits is executed against the
real backend and its structured result returned as a functionResponse. If
GEMINI_API_KEY is unset the app runs in a clearly-labeled "direct" mode that
skips Gemini entirely (never simulated tool calls).
"""
import os
import re
from typing import Callable, List, Optional

import httpx

from .geo import GEOCODE
from .models import TripPlan, VehicleState
from .planner import plan_ev_trip
from .vehicle import get_vehicle_state

# gemini-2.5-flash is sunset for new API projects (404); 3.6-flash verified live tonight
MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.6-flash").strip()
URL = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent"

SYSTEM_INSTRUCTION = (
    "You are EVLink. Always call get_vehicle_state before planning. Never estimate "
    "battery, range, distance, or charging times yourself — report only values "
    "returned by tools. Explain the itinerary concisely and mention the stated assumptions."
)

TOOLS = [{
    "function_declarations": [
        {
            "name": "get_vehicle_state",
            "description": ("Read the connected EV's live state: make/model, battery percent, "
                            "estimated range in miles, and GPS location."),
            "parameters": {"type": "object", "properties": {}},
        },
        {
            "name": "plan_ev_trip",
            "description": ("Plan an EV road trip from the vehicle's current location. Returns a "
                            "deterministic TripPlan with charging stops (arrive/depart SOC, charge "
                            "minutes), total distance, arrival SOC, feasibility, and assumptions."),
            "parameters": {
                "type": "object",
                "properties": {
                    "destination": {"type": "string",
                                    "description": "Destination city, e.g. 'Nashville'"},
                    "min_soc_pct": {"type": "integer",
                                    "description": "Minimum battery percent to stay above (default 15)"},
                    "preference": {"type": "string",
                                   "description": "Optimization preference, e.g. 'minimize charging time'"},
                },
                "required": ["destination"],
            },
        },
    ]
}]


def gemini_enabled() -> bool:
    return bool(os.environ.get("GEMINI_API_KEY", "").strip())


def _call_gemini(contents: list) -> dict:
    resp = httpx.post(
        URL,
        headers={"x-goog-api-key": os.environ["GEMINI_API_KEY"].strip(),
                 "Content-Type": "application/json"},
        json={
            "system_instruction": {"parts": [{"text": SYSTEM_INSTRUCTION}]},
            "contents": contents,
            "tools": TOOLS,
        },
        timeout=60,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"Gemini HTTP {resp.status_code}: {resp.text[:300]}")
    return resp.json()


def chat(message: str,
         on_step: Callable[[str, str, str], None],
         on_tool_call: Callable[[str, dict], None]) -> dict:
    """Returns {text, trip_plan, vehicle, mode}."""
    if not gemini_enabled():
        return _direct_mode(message, on_step)

    last_vehicle: Optional[VehicleState] = None
    last_plan: Optional[TripPlan] = None

    def exec_tool(name: str, args: dict) -> dict:
        nonlocal last_vehicle, last_plan
        on_tool_call(name, args)
        if name == "get_vehicle_state":
            on_step("vehicle", "running", "")
            last_vehicle = get_vehicle_state()
            on_step("vehicle", "done",
                    f"{last_vehicle.make} {last_vehicle.model} @ {last_vehicle.battery_pct:.0f}%")
            return last_vehicle.model_dump()
        if name == "plan_ev_trip":
            last_plan = plan_ev_trip(
                destination=str(args.get("destination", "")),
                min_soc_pct=int(args.get("min_soc_pct") or 15),
                preference=str(args.get("preference") or "minimize charging time"),
                vehicle=last_vehicle,
                on_step=on_step)
            return last_plan.model_dump()
        return {"error": f"unknown tool {name}"}

    on_step("gemini", "running", "")
    contents: List[dict] = [{"role": "user", "parts": [{"text": message}]}]
    text = ""
    for _round in range(6):
        data = _call_gemini(contents)
        cand = (data.get("candidates") or [{}])[0]
        parts = (cand.get("content") or {}).get("parts") or []
        calls = [p["functionCall"] for p in parts if "functionCall" in p]
        texts = [p["text"] for p in parts if "text" in p]
        if not calls:
            text = "\n".join(texts).strip()
            break
        on_step("gemini", "done", f"tool call: {', '.join(c['name'] for c in calls)}")
        contents.append({"role": "model", "parts": parts})
        responses = [{"functionResponse": {"name": c["name"],
                                           "response": exec_tool(c["name"], c.get("args") or {})}}
                     for c in calls]
        contents.append({"role": "user", "parts": responses})
        on_step("answer", "running", "")
    on_step("gemini", "done", "")
    on_step("answer", "done" if text else "error", "")
    if not text:
        text = "Gemini returned no final text; the structured plan below is from the deterministic planner."
    return {
        "text": text,
        "trip_plan": last_plan.model_dump() if last_plan else None,
        "vehicle": last_vehicle.model_dump() if last_vehicle else None,
        "mode": "gemini",
        "model": MODEL,
    }


# ---------------- direct mode (no LLM, clearly labeled; used only when no API key) ---


def _direct_mode(message: str, on_step: Callable[[str, str, str], None]) -> dict:
    on_step("gemini", "error", "GEMINI_API_KEY not set — deterministic direct mode")
    lower = message.lower()
    hits = [(lower.rfind(k), k) for k in GEOCODE if k in lower]
    dest = max(hits)[1] if hits else None  # last city mentioned = destination
    m = re.search(r"(\d{1,2})\s*%", message)
    min_soc = int(m.group(1)) if m else 15
    if not dest:
        on_step("answer", "error", "")
        return {"text": ("Direct mode (no GEMINI_API_KEY): tell me a destination city, e.g. "
                         "'Get me to Nashville. Keep me above 15%.'"),
                "trip_plan": None, "vehicle": get_vehicle_state().model_dump(), "mode": "direct"}
    vehicle = get_vehicle_state()
    plan = plan_ev_trip(destination=dest, min_soc_pct=min_soc, vehicle=vehicle, on_step=on_step)
    on_step("answer", "done", "deterministic summary (no LLM)")
    if plan.feasible:
        stop_txt = "; ".join(
            f"{s.charger.name} (mi {s.charger.route_mi:.0f}): {s.arrive_soc}%->{s.depart_soc}%, "
            f"{s.charge_min} min" for s in plan.stops) or "no charging needed"
        text = (f"[Direct mode — Gemini disabled] {plan.origin} to {plan.destination}: "
                f"{plan.total_mi} mi, ~{plan.drive_min} min driving. Stops: {stop_txt}. "
                f"Arrive at {plan.arrival_soc}%.")
    else:
        text = f"[Direct mode — Gemini disabled] Trip not feasible: {plan.reason}"
    return {"text": text, "trip_plan": plan.model_dump(),
            "vehicle": vehicle.model_dump(), "mode": "direct"}
