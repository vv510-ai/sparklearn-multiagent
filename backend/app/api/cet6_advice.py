from fastapi import APIRouter, BackgroundTasks

from ..auth import require_current_user_id
from ..schemas.cet6_advice import AdviceRequest
from ..services import cet6_advice as advice

router = APIRouter(prefix="/api/notebooks/{notebook_id}/cet6/advice", tags=["cet6"])


@router.get("")
def get_advice(notebook_id: str):
    return advice.get(require_current_user_id(), notebook_id)


@router.post("")
def generate_advice(notebook_id: str, req: AdviceRequest, tasks: BackgroundTasks):
    user = require_current_user_id()
    result, claim = advice.request(user, notebook_id, req.profile_revision)
    if claim:
        tasks.add_task(advice.generate, user, notebook_id, claim)
    return result
