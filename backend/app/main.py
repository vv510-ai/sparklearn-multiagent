"""SparkLearn 后端入口(FastAPI)。
启动时:建表 → 教材语料入库(幂等)→ 挂载 /static(TTS/封面等生成产物)→ 注册路由。
运行:uvicorn app.main:app --reload --port 8000(backend 目录下)"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.staticfiles import StaticFiles

from .api import assessment, auth, chat, courses, debug, demo, evaluate, knowledge, meta, notebooks, path, resources, tutor
from .api import pilot
from .api import personal_image
from .api import settings as model_settings
from .api import learning, jobs, library, materials, cet6, cet6_advice
from .auth import bind_request_user, decode_access_token, reset_request_user
from .config import GEN_DIR, STATIC_DIR, auth_required, get_settings, is_demo
from .models.db import init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    GEN_DIR.mkdir(parents=True, exist_ok=True)
    try:
        from .services.object_storage import restore_all_sources
        restored = restore_all_sources()
        if restored:
            print(f"[SparkLearn] restored {restored} source files from object storage")
        from .rag.ingest import ingest_corpus
        n = ingest_corpus()
        print(f"[SparkLearn] 语料入库完成:{n} 个 chunk;demo_mode={is_demo()}")
    except Exception as exc:                       # 语料缺失不阻断启动
        print(f"[SparkLearn] 语料入库跳过:{exc}")
    try:
        from .services.course_library import bootstrap
        bootstrap()
    except Exception as exc:
        import logging
        logging.getLogger("sparklearn.library").exception("Course library publication failed: %s", exc)
    import asyncio, os
    from .services.generation_jobs import enabled, worker_loop
    worker = asyncio.create_task(worker_loop()) if enabled() and os.getenv("GENERATION_WORKER_MODE", "embedded") == "embedded" else None
    try:
        yield
    finally:
        if worker:
            worker.cancel()
            await asyncio.gather(worker, return_exceptions=True)


app = FastAPI(title="知行循证 LearnLoop · 可验证个性化学习平台",
              version="1.0.0", lifespan=lifespan)


@app.exception_handler(RequestValidationError)
async def redact_settings_validation(request: Request, exc: RequestValidationError):
    if request.url.path.startswith("/api/settings/models"):
        return JSONResponse({"detail": "设置格式不正确，请检查模型选项和 API Key 字段"}, status_code=422)
    return await request_validation_exception_handler(request, exc)

_PUBLIC_PATHS = {
    "/",
    "/api/health",
    "/api/auth/login",
    "/api/auth/register",
    "/docs",
    "/openapi.json",
    "/redoc",
}


@app.middleware("http")
async def authenticate_request(request: Request, call_next):
    if request.url.path.startswith("/api/personal-image-worker/"):
        from .services.personal_image import authenticate_worker
        try:
            user = authenticate_worker(request.headers.get("authorization", ""))
        except Exception as exc:
            return JSONResponse({"detail": getattr(exc, "detail", "图片接入程序未授权")},
                                status_code=getattr(exc, "status_code", 401))
        context_token = bind_request_user(user)
        try:
            request.state.user_id = user
            return await call_next(request)
        finally:
            reset_request_user(context_token)
    public_materials = request.method == "GET" and request.url.path == "/api/materials"
    if not auth_required() or request.url.path in _PUBLIC_PATHS or public_materials:
        return await call_next(request)
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        return JSONResponse({"detail": "请先登录"}, status_code=401)
    try:
        payload = decode_access_token(token.strip())
    except Exception as exc:  # FastAPI HTTPException cannot be raised across middleware reliably
        detail = getattr(exc, "detail", "登录已失效，请重新登录")
        return JSONResponse({"detail": detail}, status_code=401)
    context_token = bind_request_user(str(payload["sub"]))
    try:
        request.state.user_id = str(payload["sub"])
        if request.url.path.startswith("/static/gen/"):
            from .services.ownership_service import asset_belongs_to_user
            if not asset_belongs_to_user(str(payload["sub"]), request.url.path):
                return JSONResponse({"detail": "asset not found"}, status_code=404)
        return await call_next(request)
    finally:
        reset_request_user(context_token)

app.add_middleware(
    CORSMiddleware,
    allow_origins=list(dict.fromkeys([get_settings().frontend_origin, "http://localhost:3000"])),
    allow_credentials=False, allow_methods=["*"], allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
app.include_router(personal_image.router)

for r in (jobs.router, assessment.router, courses.router, auth.router, chat.router, resources.router, notebooks.router, path.router, debug.router, knowledge.router,
          tutor.router, evaluate.router, demo.router, meta.router, pilot.router, model_settings.router, learning.router, library.router, materials.router, cet6.router, cet6_advice.router):
    app.include_router(r)


@app.get("/")
async def root():
    return {"app": "知行循证 LearnLoop", "docs": "/docs", "health": "/api/health"}
