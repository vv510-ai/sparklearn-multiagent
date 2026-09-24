"""SSE 公共封装:把异步事件字典流包装为 text/event-stream(手写协议,零额外依赖)。"""
from __future__ import annotations

import json
from typing import AsyncIterator

from fastapi.responses import StreamingResponse

HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no",
           "Connection": "keep-alive"}


async def _wrap(gen: AsyncIterator[dict], release_id: str = ""):
    try:
        async for ev in gen:
            from ..services.course_library import is_withdrawn, blocked_payload, WITHDRAWN
            if (release_id and is_withdrawn(release_id)) or blocked_payload(ev):
                yield f"data: {json.dumps({'type': 'error', 'detail': WITHDRAWN}, ensure_ascii=False)}\n\n"
                break
            yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"
    finally:
        close = getattr(gen, "aclose", None)
        if close:
            await close()


def sse_response(gen: AsyncIterator[dict]) -> StreamingResponse:
    from ..services.learning_scope import current_space
    release_id = str((current_space() or {}).get("course", {}).get("course_release_id") or "")
    return StreamingResponse(_wrap(gen, release_id), media_type="text/event-stream", headers=HEADERS)
