"""Private teacher workspace: no arbitrary user-id or cross-tenant lookups."""
from fastapi import APIRouter

from ..auth import require_current_user_id
from ..services import pilot_service as service

router = APIRouter(prefix="/api/pilot", tags=["pilot"])


@router.get("/studies")
async def list_studies():
    return {"studies": service.list_studies(require_current_user_id())}


@router.post("/studies")
async def create_study(spec: service.StudyInput):
    return service.create_study(require_current_user_id(), spec)


@router.get("/studies/{study_id}")
async def report(study_id: str):
    return service.study_report(require_current_user_id(), study_id)


@router.delete("/studies/{study_id}")
async def delete_study(study_id: str):
    return service.delete_study(require_current_user_id(), study_id)


@router.post("/studies/{study_id}/observations")
async def import_observations(study_id: str, spec: service.ImportInput):
    return service.import_observations(require_current_user_id(), study_id, spec)
