"""EVLink — FastAPI app. UI -> /api/chat -> Gemini function-calling -> deterministic planner."""
import os
import threading

from dotenv import load_dotenv

load_dotenv()  # before app modules read env

from fastapi import FastAPI  # noqa: E402
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse  # noqa: E402
from pydantic import BaseModel  # noqa: E402

from . import gemini, jobs, vehicle  # noqa: E402
from .planner import plan_ev_trip  # noqa: E402

app = FastAPI(title="EVLink")

STATIC_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static")


class ChatBody(BaseModel):
    message: str


class PlanBody(BaseModel):
    destination: str
    min_soc_pct: int = 15
    preference: str = "minimize charging time"


@app.get("/")
def index():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


@app.get("/healthz")
def healthz():
    return {"ok": True, "gemini": gemini.gemini_enabled(),
            "smartcar_configured": vehicle.smartcar_configured(),
            "smartcar_connected": vehicle.connected()}


@app.get("/api/vehicle")
def api_vehicle():
    return vehicle.get_vehicle_state().model_dump()


@app.post("/api/chat")
def api_chat(body: ChatBody):
    job_id = jobs.create_job(body.message)

    def worker():
        try:
            result = gemini.chat(
                body.message,
                on_step=lambda k, s, d="": jobs.set_step(job_id, k, s, d),
                on_tool_call=lambda n, a: jobs.add_tool_call(job_id, n, a))
            jobs.finish(job_id, result=result)
        except Exception as e:  # noqa: BLE001 - surfaced to the UI, never swallowed
            jobs.finish(job_id, error=f"{type(e).__name__}: {e}")

    threading.Thread(target=worker, daemon=True).start()
    return {"job_id": job_id}


@app.get("/api/jobs/{job_id}")
def api_job(job_id: str):
    job = jobs.get_job(job_id)
    if not job:
        return JSONResponse({"error": "unknown job"}, status_code=404)
    return job


@app.post("/api/plan")
def api_plan(body: PlanBody):
    """Direct deterministic planner (no LLM) — used for testing and as an honest dev path."""
    return plan_ev_trip(body.destination, body.min_soc_pct, body.preference).model_dump()


@app.get("/auth/login")
def auth_login():
    if not vehicle.smartcar_configured():
        return JSONResponse({"error": "Set SMARTCAR_CLIENT_ID / SMARTCAR_CLIENT_SECRET / "
                                      "SMARTCAR_REDIRECT_URI first"}, status_code=400)
    return RedirectResponse(vehicle.build_connect_url())


@app.get("/callback")
def auth_callback(code: str = "", error: str = ""):
    if error or not code:
        return RedirectResponse(f"/?smartcar_error={error or 'no_code'}")
    try:
        vehicle.exchange_code(code)
        return RedirectResponse("/?connected=1")
    except Exception as e:  # noqa: BLE001
        return RedirectResponse(f"/?smartcar_error={type(e).__name__}")
