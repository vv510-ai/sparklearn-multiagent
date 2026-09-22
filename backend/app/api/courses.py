from fastapi import APIRouter, Query

from ..auth import require_current_user_id
from ..services.course_service import recommend
from ..services.learning_scope import scoped_endpoint

router = APIRouter(prefix="/api/courses", tags=["courses"])


@router.get("")
@scoped_endpoint
def courses(q: str = Query(default="", max_length=120), kp: str = Query(default="", max_length=64),
            platform: str = Query(default="", pattern="^(|bilibili|youtube)$"), topic: str = Query(default="", max_length=6000), notebook_id: str = ""):
    return recommend(require_current_user_id(), q, kp, platform, topic)
