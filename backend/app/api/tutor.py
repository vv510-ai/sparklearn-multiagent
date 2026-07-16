"""POST /api/tutor —— 多模态答疑(SSE)。支持 image_base64 拍照搜题(讯飞 OCR),
intent 固定 tutor,直达 Tutor Agent,逐 token 流式 + Mermaid 图解 + 引用溯源。"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from ..agents.graph import run_with_events
from ..llm import multimodal_gateway
from ..schemas.core import TutorRequest
from ..services.profile_service import ensure_user
from .sse import sse_response

router = APIRouter(prefix="/api", tags=["tutor"])


@router.post("/tutor/transcribe")
async def transcribe_question(
    file: UploadFile = File(...),
    user_id: str = Form("demo_user"),
    encoding: str = Form("raw"),
    sample_rate: int = Form(16000),
):
    """Transcribe one short voice question with the Spark speech model."""
    ensure_user(user_id)
    if encoding not in {"raw", "lame"}:
        raise HTTPException(400, "仅支持 PCM(raw) 或 MP3(lame) 音频")
    if sample_rate not in {8000, 16000}:
        raise HTTPException(400, "采样率必须是 8000 或 16000")
    audio = await file.read(4_000_001)
    if not audio:
        raise HTTPException(400, "录音内容为空")
    if len(audio) > 4_000_000:
        raise HTTPException(413, "录音文件过大，请控制在 60 秒以内")
    if encoding == "raw":
        duration_s = len(audio) / (sample_rate * 2)
        if duration_s > 60.5:
            raise HTTPException(413, "单次录音不能超过 60 秒")
    else:
        duration_s = 0.0

    result = await multimodal_gateway.speech_to_text(
        audio,
        encoding=encoding,
        sample_rate=sample_rate,
        trace_id=f"voice-question-{uuid.uuid4().hex[:8]}",
    )
    if not result.get("ok"):
        raise HTTPException(503, str(result.get("error") or "语音识别暂时不可用"))
    return {
        "text": str((result.get("data") or {}).get("text") or ""),
        "provider": str((result.get("data") or {}).get("provider") or "spark_asr"),
        "duration_s": round(duration_s, 2),
        "elapsed_ms": int(result.get("elapsed_ms") or 0),
    }


@router.post("/tutor")
async def tutor(req: TutorRequest):
    ensure_user(req.user_id)
    state = {
        "user_id": req.user_id,
        "session_id": uuid.uuid4().hex[:8],
        "messages": [{"role": "user", "content": req.question or "请讲讲这道题"}],
        "intent": "tutor",
        "tutor_extras": {"image_base64": req.image_base64, "want": req.want},
    }
    return sse_response(run_with_events(state))
