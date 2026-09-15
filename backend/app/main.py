"""SparkLearn 后端入口(FastAPI)。
启动时:建表 → 教材语料入库(幂等)→ 挂载 /static(TTS/封面等生成产物)→ 注册路由。
运行:uvicorn app.main:app --reload --port 8000(backend 目录下)"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from .api import assessment, auth, chat, courses, debug, demo, evaluate, knowledge, meta, notebooks, path, resources, tutor
from .api import pilot
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
    yield


app = FastAPI(title="知行循证 LearnLoop · 可验证个性化学习平台",
              version="1.0.0", lifespan=lifespan)

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
    if not auth_required() or request.url.path in _PUBLIC_PATHS:
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

for r in (assessment.router, courses.router, auth.router, chat.router, resources.router, notebooks.router, path.router, debug.router, knowledge.router,
          tutor.router, evaluate.router, demo.router, meta.router, pilot.router):
    app.include_router(r)


@app.get("/")
async def root():
    return {"app": "知行循证 LearnLoop", "docs": "/docs", "health": "/api/health"}
