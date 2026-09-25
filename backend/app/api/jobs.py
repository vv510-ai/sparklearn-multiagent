"""Read-only job status and resumable events, always scoped to the logged-in user."""
from fastapi import APIRouter, Query
from ..auth import require_current_user_id
from ..services import generation_jobs as jobs
from .sse import sse_response
router = APIRouter(prefix="/api/jobs", tags=["jobs"])

@router.get("")
async def list_jobs(notebook_id: str = ""):
    return {"items": jobs.list_jobs(require_current_user_id(), notebook_id)}

@router.get("/{job_id}")
async def get_job(job_id: str):
    return jobs.owned(require_current_user_id(), job_id)

@router.get("/{job_id}/events")
async def job_events(job_id: str, after: int = Query(0, ge=0)):
    user = require_current_user_id()
    jobs.owned(user, job_id)
    return sse_response(jobs.events(user, job_id, after))
