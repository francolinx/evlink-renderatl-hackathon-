"""In-memory job store: real backend step completion drives the UI ticks (no fake timers)."""
import threading
import uuid
from typing import Dict, List, Optional

_LOCK = threading.Lock()
_JOBS: Dict[str, dict] = {}

STEP_ORDER = [
    ("gemini", "Gemini interprets your request"),
    ("vehicle", "Reading vehicle state"),
    ("route", "Fetching driving route (OSRM)"),
    ("chargers", "Finding DC fast chargers (US DOE AFDC)"),
    ("optimize", "Optimizing charging stops"),
    ("answer", "Gemini writes the itinerary"),
]


def create_job(message: str) -> str:
    job_id = uuid.uuid4().hex[:12]
    with _LOCK:
        _JOBS[job_id] = {
            "id": job_id,
            "message": message,
            "status": "running",
            "steps": [{"key": k, "label": lbl, "state": "pending", "detail": ""}
                      for k, lbl in STEP_ORDER],
            "tool_calls": [],   # genuine Gemini functionCalls, in order
            "result": None,
            "error": None,
        }
    return job_id


def set_step(job_id: str, key: str, state: str, detail: str = "") -> None:
    with _LOCK:
        job = _JOBS.get(job_id)
        if not job:
            return
        for s in job["steps"]:
            if s["key"] == key:
                s["state"] = state
                if detail:
                    s["detail"] = detail


def add_tool_call(job_id: str, name: str, args: dict) -> None:
    with _LOCK:
        job = _JOBS.get(job_id)
        if job is not None:
            job["tool_calls"].append({"name": name, "args": args})


def finish(job_id: str, result: Optional[dict] = None, error: Optional[str] = None) -> None:
    with _LOCK:
        job = _JOBS.get(job_id)
        if not job:
            return
        job["status"] = "error" if error else "done"
        job["result"] = result
        job["error"] = error
        for s in job["steps"]:  # anything never reached stays visibly skipped
            if s["state"] in ("pending", "running") and error:
                s["state"] = "skipped" if s["state"] == "pending" else "error"


def get_job(job_id: str) -> Optional[dict]:
    with _LOCK:
        job = _JOBS.get(job_id)
        return dict(job) if job else None
