"""FastAPI entrypoint for the Timetable Generator backend."""
from __future__ import annotations

import os
import uuid
from pathlib import Path
from typing import Optional

# Load environment from a .env file at backend/.env so API keys never need to
# be passed on the command line. .env is git-ignored.
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
except ImportError:
    pass

from fastapi import Body, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel
from starlette.middleware.base import BaseHTTPMiddleware

from .core.preflight import validate
from .core.verifier import verify
from .data.bmsit_4th_sem import build_request
from .export.renderers import render_ical, render_json, render_pdf, render_xlsx
from .models.domain import Timetable, TimetableRequest, VerificationReport, PreflightReport
from .solver.cpsat_solver import solve

app = FastAPI(title="Timetable Generator", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class BearerAuthMiddleware(BaseHTTPMiddleware):
    """Reject requests missing the shared API token.

    Only enabled when the env var BACKEND_API_TOKEN is set. Health checks and
    OpenAPI docs are always reachable so platforms can verify liveness.
    """

    PUBLIC_PATHS = {"/health", "/docs", "/openapi.json", "/redoc", "/docs/oauth2-redirect"}

    async def dispatch(self, request: Request, call_next):
        token = os.environ.get("BACKEND_API_TOKEN")
        if not token:
            return await call_next(request)
        if request.url.path in self.PUBLIC_PATHS or request.method == "OPTIONS":
            return await call_next(request)
        auth = request.headers.get("authorization", "")
        # Accept either "Bearer <token>" or raw token in X-API-Token.
        provided = ""
        if auth.lower().startswith("bearer "):
            provided = auth[7:].strip()
        if not provided:
            provided = request.headers.get("x-api-token", "").strip()
        if provided != token:
            return JSONResponse({"detail": "unauthorized"}, status_code=401)
        return await call_next(request)


app.add_middleware(BearerAuthMiddleware)


# Job store: in-memory cache + JSON files on disk so the backend can restart
# (e.g., after `systemctl restart timetable` or a redeploy) without breaking
# export URLs the user/HoD already has.
_jobs: dict[str, dict] = {}
_JOBS_DIR = Path(__file__).resolve().parent.parent / "jobs"
_JOBS_DIR.mkdir(exist_ok=True)


def _save_job(job_id: str, payload: dict) -> None:
    """Persist a job to disk (best-effort)."""
    try:
        out = {
            "req": payload["req"].model_dump(mode="json") if payload.get("req") else None,
            "tt": payload["tt"].model_dump(mode="json") if payload.get("tt") else None,
            "verify": payload["verify"].model_dump(mode="json") if payload.get("verify") else None,
            "preflight": payload["preflight"].model_dump(mode="json") if payload.get("preflight") else None,
        }
        (_JOBS_DIR / f"{job_id}.json").write_text(
            __import__("json").dumps(out), encoding="utf-8"
        )
    except Exception:
        pass  # disk full / readonly fs / etc — fall back to in-memory only


def _load_job(job_id: str) -> Optional[dict]:
    """Look up a job: hot in-memory cache first, then disk."""
    if job_id in _jobs:
        return _jobs[job_id]
    fp = _JOBS_DIR / f"{job_id}.json"
    if not fp.exists():
        return None
    try:
        raw = __import__("json").loads(fp.read_text(encoding="utf-8"))
        from .models.domain import (
            PreflightReport as _PR,
            Timetable as _TT,
            TimetableRequest as _TR,
            VerificationReport as _VR,
        )
        payload = {
            "req": _TR.model_validate(raw["req"]) if raw.get("req") else None,
            "tt": _TT.model_validate(raw["tt"]) if raw.get("tt") else None,
            "verify": _VR.model_validate(raw["verify"]) if raw.get("verify") else None,
            "preflight": _PR.model_validate(raw["preflight"]) if raw.get("preflight") else None,
        }
        _jobs[job_id] = payload
        return payload
    except Exception:
        return None


class GenerateResponse(BaseModel):
    job_id: str
    preflight: PreflightReport
    timetable: Optional[Timetable] = None
    verification: Optional[VerificationReport] = None


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/reference/bmsit_4th_sem")
def reference_bmsit() -> TimetableRequest:
    return build_request()


class DraftSkeleton(BaseModel):
    days: list[str] = ["MON", "TUE", "WED", "THU", "FRI", "SAT"]
    slots_per_day: int = 7
    slot_timings: list[list[str]] = [
        ["08:30", "09:25"],
        ["09:25", "10:20"],
        ["10:40", "11:35"],
        ["11:35", "12:30"],
        ["13:25", "14:20"],
        ["14:20", "15:15"],
        ["15:15", "16:10"],
    ]
    tea_after_slot: int = 2
    tea_minutes: int = 20
    lunch_after_slot: int = 4
    lunch_minutes: int = 55
    section_ids: list[str] = ["A", "B", "C", "D", "E", "F"]
    batches_per_section: int = 2
    classroom_by_section: dict[str, str] = {}
    inactive_sat_weeks: list[int] = [1, 3]
    sat_locks: list[dict] = []  # [{label, slots, sections?}]
    semester: int = 4


class DraftBuildRequest(BaseModel):
    skeleton: DraftSkeleton
    courses_text: str
    elective_blocks: list[dict] = []  # passed straight to builder
    time_limit_sec: int = 20


def _normalise_draft_time_limit(limit: int) -> int:
    """Keep wizard solves inside the same latency budget as the core API."""
    return max(5, min(int(limit or 20), 20))


def _solve_or_422(req: TimetableRequest) -> Timetable:
    """Run CP-SAT and surface modeling errors as actionable 422 responses."""
    try:
        return solve(req)
    except RuntimeError as e:
        raise HTTPException(422, f"Solver setup failed: {str(e)[:400]}")
    except ValueError as e:
        raise HTTPException(422, f"Solver input invalid: {str(e)[:400]}")


@app.post("/draft/import-documents")
async def draft_import_documents(
    files: list[UploadFile] = File(...),
    existing_text: str = Form(""),
    section_ids: str = Form(""),
    replace_existing: bool = Form(True),
) -> dict:
    """Extract course/faculty data from uploaded PDF/DOCX files into Step 2 text."""
    from .draft.import_docs import import_course_documents

    uploaded: list[tuple[str, bytes]] = []
    for file in files:
        name = file.filename or "document"
        payload = await file.read()
        if not payload:
            continue
        uploaded.append((name, payload))
    if not uploaded:
        raise HTTPException(400, "No files were uploaded.")

    parsed_section_ids = [part.strip() for part in section_ids.split(",") if part.strip()]
    try:
        result = import_course_documents(
            uploaded,
            section_ids=parsed_section_ids,
            existing_text=existing_text,
            replace_existing=replace_existing,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(500, f"Document import failed: {str(e)[:200]}")
    return {"ok": True, **result}


@app.post("/draft/preview")
def draft_preview(body: DraftBuildRequest) -> dict:
    """Parse the paste + skeleton WITHOUT solving — for live wizard preview."""
    from .draft.from_paste import Skeleton, build_request as build_from_paste

    sk_in = body.skeleton
    sk = Skeleton(
        days=sk_in.days,
        slots_per_day=sk_in.slots_per_day,
        slot_timings=[(a, b) for a, b in sk_in.slot_timings],
        tea_after_slot=sk_in.tea_after_slot,
        tea_minutes=sk_in.tea_minutes,
        lunch_after_slot=sk_in.lunch_after_slot,
        lunch_minutes=sk_in.lunch_minutes,
        section_ids=sk_in.section_ids,
        batches_per_section=sk_in.batches_per_section,
        classroom_by_section=sk_in.classroom_by_section
        or {s: "" for s in sk_in.section_ids},
        inactive_sat_weeks=sk_in.inactive_sat_weeks,
        sat_locks=[
            (
                lk.get("label", ""),
                [int(s) for s in lk.get("slots", [])],
                lk.get("sections") or None,
            )
            for lk in sk_in.sat_locks
        ],
        semester=sk_in.semester,
    )
    try:
        req = build_from_paste(
            sk,
            body.courses_text,
            elective_blocks_raw=body.elective_blocks,
            time_limit_sec=_normalise_draft_time_limit(body.time_limit_sec),
        )
    except Exception as e:
        return {"ok": False, "error": str(e)[:300]}
    pf = validate(req)
    return {
        "ok": True,
        "summary": {
            "sections": len(req.sections),
            "courses": len(req.courses),
            "faculty": len(req.faculty),
            "elective_blocks": len(req.elective_blocks),
        },
        "preflight": pf.model_dump(mode="json"),
        "request": req.model_dump(mode="json"),
    }


@app.post("/draft/build", response_model=GenerateResponse)
def draft_build(body: DraftBuildRequest) -> GenerateResponse:
    """Build a TimetableRequest from a wizard skeleton + a pasted course table,
    then immediately run preflight + solver + verifier."""
    from .draft.from_paste import Skeleton, build_request as build_from_paste

    sk_in = body.skeleton
    sk = Skeleton(
        days=sk_in.days,
        slots_per_day=sk_in.slots_per_day,
        slot_timings=[(a, b) for a, b in sk_in.slot_timings],
        tea_after_slot=sk_in.tea_after_slot,
        tea_minutes=sk_in.tea_minutes,
        lunch_after_slot=sk_in.lunch_after_slot,
        lunch_minutes=sk_in.lunch_minutes,
        section_ids=sk_in.section_ids,
        batches_per_section=sk_in.batches_per_section,
        classroom_by_section=sk_in.classroom_by_section
        or {s: "" for s in sk_in.section_ids},
        inactive_sat_weeks=sk_in.inactive_sat_weeks,
        sat_locks=[
            (
                lk.get("label", ""),
                [int(s) for s in lk.get("slots", [])],
                lk.get("sections") or None,
            )
            for lk in sk_in.sat_locks
        ],
        semester=sk_in.semester,
    )
    try:
        req = build_from_paste(
            sk,
            body.courses_text,
            elective_blocks_raw=body.elective_blocks,
            time_limit_sec=_normalise_draft_time_limit(body.time_limit_sec),
        )
    except Exception as e:
        raise HTTPException(400, f"Parse failed: {str(e)[:300]}")

    pf = validate(req)
    if not pf.ok:
        job_id = uuid.uuid4().hex
        payload = {"req": req, "tt": None, "verify": None, "preflight": pf}
        _jobs[job_id] = payload
        _save_job(job_id, payload)
        return GenerateResponse(
            job_id=job_id, preflight=pf, timetable=None, verification=None
        )
    tt = _solve_or_422(req)
    vr = (
        verify(req, tt)
        if tt.status in ("OPTIMAL", "FEASIBLE")
        else VerificationReport(ok=False)
    )
    job_id = uuid.uuid4().hex
    payload = {"req": req, "tt": tt, "verify": vr, "preflight": pf}
    _jobs[job_id] = payload
    _save_job(job_id, payload)
    return GenerateResponse(
        job_id=job_id, preflight=pf, timetable=tt, verification=vr
    )


@app.post("/preflight")
def preflight_endpoint(req: TimetableRequest) -> PreflightReport:
    return validate(req)


@app.post("/generate", response_model=GenerateResponse)
def generate_endpoint(req: TimetableRequest) -> GenerateResponse:
    pf = validate(req)
    if not pf.ok:
        job_id = uuid.uuid4().hex
        payload = {"req": req, "tt": None, "verify": None, "preflight": pf}
        _jobs[job_id] = payload
        _save_job(job_id, payload)
        return GenerateResponse(job_id=job_id, preflight=pf, timetable=None, verification=None)

    tt = _solve_or_422(req)
    vr = verify(req, tt) if tt.status in ("OPTIMAL", "FEASIBLE") else VerificationReport(ok=False)
    job_id = uuid.uuid4().hex
    payload = {"req": req, "tt": tt, "verify": vr, "preflight": pf}
    _jobs[job_id] = payload
    _save_job(job_id, payload)
    return GenerateResponse(job_id=job_id, preflight=pf, timetable=tt, verification=vr)


@app.get("/job/{job_id}")
def job_get(job_id: str) -> dict:
    job = _load_job(job_id)
    if not job:
        raise HTTPException(404, "job not found")
    return {
        "preflight": job["preflight"],
        "timetable": job["tt"],
        "verification": job["verify"],
    }


@app.get("/job/{job_id}/export/{fmt}")
def job_export(job_id: str, fmt: str, faculty_id: Optional[str] = None) -> Response:
    job = _load_job(job_id)
    if not job or not job["tt"]:
        raise HTTPException(404, "job or timetable not found")
    req: TimetableRequest = job["req"]
    tt: Timetable = job["tt"]
    fmt = fmt.lower()
    if fmt == "pdf":
        faculty_ids = [part.strip() for part in (faculty_id or "").split(",") if part.strip()]
        return Response(render_pdf(req, tt, faculty_ids=faculty_ids or None), media_type="application/pdf")
    if fmt in ("xlsx", "excel"):
        return Response(
            render_xlsx(req, tt),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    if fmt == "json":
        return Response(render_json(req, tt), media_type="application/json")
    if fmt == "ical":
        if not faculty_id:
            raise HTTPException(400, "faculty_id required for ical")
        return Response(render_ical(req, tt, faculty_id), media_type="text/calendar")
    raise HTTPException(400, f"unknown format {fmt}")


# ---------------------------------------------------------------------------
# LLM endpoints — only available if ANTHROPIC_API_KEY is set
# ---------------------------------------------------------------------------
class LLMParseRequest(BaseModel):
    text: str
    start_from_bmsit: bool = True
    prior_request: Optional[TimetableRequest] = None
    provider: Optional[str] = None  # "bedrock" or "anthropic"; defaults via env
    model: Optional[str] = None


@app.get("/llm/info")
def llm_info() -> dict:
    """Report the active LLM (Groq > Anthropic direct > Bedrock Claude > Nova)."""
    has_groq = bool(os.environ.get("GROQ_API_KEY"))
    has_key = bool(os.environ.get("ANTHROPIC_API_KEY"))
    region = (
        os.environ.get("AWS_REGION")
        or os.environ.get("AWS_DEFAULT_REGION")
        or "ap-southeast-2"
    )
    if has_groq:
        provider = "groq"
    elif has_key:
        provider = "anthropic"
    else:
        provider = "bedrock"

    reachable = False
    active_model: Optional[str] = None
    note: Optional[str] = None
    try:
        from .llm.claude_interface import ClaudeInterface

        iface = ClaudeInterface(provider=provider)
        iface._create_text(
            max_tokens=5,
            system=None,
            messages=[{"role": "user", "content": "ping"}],
        )
        active_model = getattr(iface, "active_model", None)
        reachable = True
    except Exception as e:
        note = str(e)[:200]
    return {
        "default_provider": provider,
        "bedrock_region": region,
        "has_groq_key": has_groq,
        "has_anthropic_key": has_key,
        "reachable": reachable,
        "active_model": active_model,
        "note": note,
    }


@app.post("/llm/parse")
def llm_parse(body: LLMParseRequest = Body(...)) -> JSONResponse:
    """Translate a natural-language edit into a patched TimetableRequest.

    Workflow:
      1. LLM emits {action: "patch", ops: [...]} based on the user's text.
      2. Backend applies the patch to the prior request server-side.
      3. Backend re-solves and returns the new timetable + apply log.
    """
    from .llm.claude_interface import ClaudeInterface
    from .llm.patch_ops import apply_patch

    hint = body.prior_request or (build_request() if body.start_from_bmsit else None)
    try:
        iface = ClaudeInterface(provider=body.provider, model=body.model)
    except Exception as e:
        raise HTTPException(503, f"LLM client init failed: {e}")
    try:
        llm_out = iface.parse(body.text, hint_request=hint)
    except Exception as e:
        raise HTTPException(500, f"LLM call failed: {str(e)[:200]}")

    action = llm_out.get("action")
    response: dict = {
        "action": action,
        "message": llm_out.get("message") or "",
        "active_model": getattr(iface, "active_model", None),
    }

    if action == "patch" and isinstance(llm_out.get("ops"), list) and hint is not None:
        new_req, applied, errors = apply_patch(hint, llm_out["ops"])
        response["applied"] = applied
        response["errors"] = errors
        response["request"] = new_req.model_dump(mode="json")
        # Re-solve immediately so the UI can pick up the new schedule.
        try:
            pf = validate(new_req)
            if pf.ok:
                tt = solve(new_req)
                vr = (
                    verify(new_req, tt)
                    if tt.status in ("OPTIMAL", "FEASIBLE")
                    else VerificationReport(ok=False)
                )
                job_id = uuid.uuid4().hex
                payload = {"req": new_req, "tt": tt, "verify": vr, "preflight": pf}
                _jobs[job_id] = payload
                _save_job(job_id, payload)
                response["job_id"] = job_id
                response["timetable"] = tt.model_dump(mode="json")
                response["verification"] = vr.model_dump(mode="json")
                response["preflight"] = pf.model_dump(mode="json")
            else:
                response["preflight"] = pf.model_dump(mode="json")
        except Exception as e:
            response["solver_error"] = str(e)[:200]
    return JSONResponse(response)


class LLMExplainRequest(BaseModel):
    job_id: str
    provider: Optional[str] = None
    model: Optional[str] = None


@app.post("/llm/explain")
def llm_explain(body: LLMExplainRequest) -> dict:
    from .llm.claude_interface import ClaudeInterface

    job = _load_job(body.job_id)
    if not job:
        raise HTTPException(404, "job not found")
    try:
        iface = ClaudeInterface(provider=body.provider, model=body.model)
    except Exception as e:
        raise HTTPException(503, f"LLM client init failed: {e}")
    try:
        text = iface.explain(job["req"], job["tt"], job["verify"], job["preflight"])
    except Exception as e:
        raise HTTPException(500, f"LLM call failed: {str(e)[:200]}")
    return {"explanation": text, "model": getattr(iface, "active_model", None)}
