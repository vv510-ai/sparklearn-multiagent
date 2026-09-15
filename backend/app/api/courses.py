from fastapi import APIRouter, Query

from ..auth import require_current_user_id
from ..services.course_service import recommend

router = APIRouter(prefix="/api/courses", tags=["courses"])


@router.get("")
def courses(q: str = Query(default="", max_length=120), kp: str = Query(default="", max_length=64)):
    return recommend(require_current_user_id(), q, kp)
