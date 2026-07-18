"""全局配置:读取环境变量,集中管理密钥占位与运行模式。

设计原则(对应赛题"可演示性"硬指标):
- 任何外部密钥缺失都不应让系统崩溃,而是逐级降级(真实 API → 讯飞备选 → 本地模拟);
- DEMO_MODE=auto 时,只要未配置 SPARK_API_PASSWORD 就进入演示模式,
  全链路(画像→规划→并行生成→质检→评估)仍可离线跑通,便于评委一键体验。
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path


def _env_bool(name: str, default: bool = True) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() not in {"0", "false", "no", "off"}


try:  # pydantic-settings 可用时走标准路径
    from pydantic_settings import BaseSettings, SettingsConfigDict

    class Settings(BaseSettings):
        model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

        # 讯飞星火 OpenAI 兼容
        spark_api_password: str = ""
        spark_base_url: str = "https://spark-api-open.xf-yun.com/v1/"
        spark_x2_base_url: str = "https://spark-api-open.xf-yun.com/x2/"
        spark_reasoning_mode: str = "auto"  # enabled | disabled | auto

        # 讯飞三元组(WebSocket/HTTP 旧鉴权:TTS、文生图、OCR)
        spark_appid: str = ""
        spark_api_key: str = ""
        spark_api_secret: str = ""
        spark_image_domain: str = "general"

        # 讯飞超拟人语音合成（独立服务授权，优先于普通在线 TTS）
        spark_super_tts_api_password: str = ""
        spark_super_tts_appid: str = ""
        spark_super_tts_api_key: str = ""
        spark_super_tts_api_secret: str = ""
        spark_super_tts_url: str = "wss://cbm01.cn-huabei-1.xf-yun.com/v1/private/mcd9m97e6"
        spark_super_tts_voice: str = "x6_lingxiaoxuan_pro"
        spark_tts_speed: int = 42

        # 讯飞中英识别大模型（与其他讯飞服务分开授权）
        spark_asr_appid: str = ""
        spark_asr_api_key: str = ""
        spark_asr_api_secret: str = ""
        spark_asr_url: str = "wss://iat.xf-yun.com/v1"

        # 讯飞星火智能 PPT（新版；可复用 WebAPI APPID/APISecret）
        spark_ppt_appid: str = ""
        spark_ppt_api_secret: str = ""
        spark_ppt_base_url: str = "https://zwapi.xfyun.cn"

        # OpenAI GPT Image 备用文生图
        openai_api_key: str = ""
        openai_base_url: str = "https://api.openai.com/v1"
        openai_image_model: str = "gpt-image-2"
        openai_image_quality: str = "low"

        # 小云雀（剪映）图片 / 视频生成
        xyq_access_key: str = ""
        xyq_base_url: str = "https://xyq.jianying.com"
        xyq_video_model: str = "Seedance_2.0_mini_lite"
        xyq_video_ratio: str = "16:9"
        xyq_video_duration: int = 10
        xyq_video_resolution: str = "720p"

        # 多模态能力开关与单次调用预算
        mm_ocr_enabled: bool = True
        mm_local_ocr_enabled: bool = True
        mm_asr_enabled: bool = True
        mm_tts_enabled: bool = True
        mm_image_enabled: bool = True
        mm_openai_image_enabled: bool = True
        mm_xyq_image_enabled: bool = True
        mm_video_enabled: bool = True
        mm_ppt_enabled: bool = True
        mm_ocr_max_pages: int = 6
        mm_ocr_tutor_timeout_s: float = 20
        mm_ocr_ingest_timeout_s: float = 30
        mm_local_ocr_timeout_s: float = 20
        mm_asr_timeout_s: float = 75
        mm_tts_timeout_s: float = 60
        mm_image_timeout_s: float = 30
        mm_xyq_image_wait_budget_s: float = 150
        mm_xyq_image_poll_interval_s: float = 2
        mm_image_download_timeout_s: float = 60
        mm_image_max_mb: int = 32
        mm_video_create_timeout_s: float = 15
        mm_video_wait_budget_s: float = 45
        mm_video_poll_timeout_s: float = 15
        mm_video_download_timeout_s: float = 90
        mm_video_max_mb: int = 256
        mm_ppt_create_timeout_s: float = 75
        mm_ppt_poll_timeout_s: float = 15
        mm_ppt_download_timeout_s: float = 45

        # 存储
        database_url: str = ""
        milvus_uri: str = ""
        redis_url: str = ""
        object_storage_endpoint: str = ""
        object_storage_bucket: str = ""
        object_storage_access_key: str = ""
        object_storage_secret_key: str = ""
        object_storage_region: str = "auto"

        # 用户登录与会话
        auth_secret: str = ""
        auth_required: bool = True
        auth_token_minutes: int = 10080

        embedding_backend: str = "auto"  # auto | bge-m3 | iflytek | hash
        iflytek_embedding_url: str = "https://emb-cn-huabei-1.xf-yun.com/"
        embedding_timeout_s: float = 12.0
        rerank_mode: str = "auto"  # auto | api | hybrid | vector
        rerank_api_url: str = ""
        rerank_api_key: str = ""
        rerank_top_k: int = 5
        demo_mode: str = "auto"          # auto | true | false
        trace_enabled: bool = True       # write backend/runs/{session_id} debug artifacts
        backend_port: int = 8000
        frontend_origin: str = "http://localhost:3000"

except Exception:  # pragma: no cover - 极端环境兜底(未安装 pydantic-settings)
    class Settings:  # type: ignore[no-redef]
        def __init__(self) -> None:
            g = os.environ.get
            self.spark_api_password = g("SPARK_API_PASSWORD", "")
            self.spark_base_url = g("SPARK_BASE_URL", "https://spark-api-open.xf-yun.com/v1/")
            self.spark_x2_base_url = g("SPARK_X2_BASE_URL", "https://spark-api-open.xf-yun.com/x2/")
            self.spark_reasoning_mode = g("SPARK_REASONING_MODE", "auto")
            self.spark_appid = g("SPARK_APPID", "")
            self.spark_api_key = g("SPARK_API_KEY", "")
            self.spark_api_secret = g("SPARK_API_SECRET", "")
            self.spark_image_domain = g("SPARK_IMAGE_DOMAIN", "general")
            self.spark_super_tts_api_password = g("SPARK_SUPER_TTS_API_PASSWORD", "")
            self.spark_super_tts_appid = g("SPARK_SUPER_TTS_APPID", "")
            self.spark_super_tts_api_key = g("SPARK_SUPER_TTS_API_KEY", "")
            self.spark_super_tts_api_secret = g("SPARK_SUPER_TTS_API_SECRET", "")
            self.spark_super_tts_url = g(
                "SPARK_SUPER_TTS_URL",
                "wss://cbm01.cn-huabei-1.xf-yun.com/v1/private/mcd9m97e6",
            )
            self.spark_super_tts_voice = g("SPARK_SUPER_TTS_VOICE", "x6_lingxiaoxuan_pro")
            self.spark_tts_speed = int(g("SPARK_TTS_SPEED", "42"))
            self.spark_asr_appid = g("SPARK_ASR_APPID", "")
            self.spark_asr_api_key = g("SPARK_ASR_API_KEY", "")
            self.spark_asr_api_secret = g("SPARK_ASR_API_SECRET", "")
            self.spark_asr_url = g("SPARK_ASR_URL", "wss://iat.xf-yun.com/v1")
            self.spark_ppt_appid = g("SPARK_PPT_APPID", "")
            self.spark_ppt_api_secret = g("SPARK_PPT_API_SECRET", "")
            self.spark_ppt_base_url = g("SPARK_PPT_BASE_URL", "https://zwapi.xfyun.cn")
            self.openai_api_key = g("OPENAI_API_KEY", "")
            self.openai_base_url = g("OPENAI_BASE_URL", "https://api.openai.com/v1")
            self.openai_image_model = g("OPENAI_IMAGE_MODEL", "gpt-image-2")
            self.openai_image_quality = g("OPENAI_IMAGE_QUALITY", "low")
            self.xyq_access_key = g("XYQ_ACCESS_KEY", "")
            self.xyq_base_url = g("XYQ_BASE_URL", "https://xyq.jianying.com")
            self.xyq_video_model = g("XYQ_VIDEO_MODEL", "Seedance_2.0_mini_lite")
            self.xyq_video_ratio = g("XYQ_VIDEO_RATIO", "16:9")
            self.xyq_video_duration = int(g("XYQ_VIDEO_DURATION", "10"))
            self.xyq_video_resolution = g("XYQ_VIDEO_RESOLUTION", "720p")
            self.mm_ocr_enabled = _env_bool("MM_OCR_ENABLED")
            self.mm_local_ocr_enabled = _env_bool("MM_LOCAL_OCR_ENABLED")
            self.mm_asr_enabled = _env_bool("MM_ASR_ENABLED")
            self.mm_tts_enabled = _env_bool("MM_TTS_ENABLED")
            self.mm_image_enabled = _env_bool("MM_IMAGE_ENABLED")
            self.mm_openai_image_enabled = _env_bool("MM_OPENAI_IMAGE_ENABLED")
            self.mm_xyq_image_enabled = _env_bool("MM_XYQ_IMAGE_ENABLED")
            self.mm_video_enabled = _env_bool("MM_VIDEO_ENABLED")
            self.mm_ppt_enabled = _env_bool("MM_PPT_ENABLED")
            self.mm_ocr_max_pages = int(g("MM_OCR_MAX_PAGES", "6"))
            self.mm_ocr_tutor_timeout_s = float(g("MM_OCR_TUTOR_TIMEOUT_S", "20"))
            self.mm_ocr_ingest_timeout_s = float(g("MM_OCR_INGEST_TIMEOUT_S", "30"))
            self.mm_local_ocr_timeout_s = float(g("MM_LOCAL_OCR_TIMEOUT_S", "20"))
            self.mm_asr_timeout_s = float(g("MM_ASR_TIMEOUT_S", "75"))
            self.mm_tts_timeout_s = float(g("MM_TTS_TIMEOUT_S", "60"))
            self.mm_image_timeout_s = float(g("MM_IMAGE_TIMEOUT_S", "30"))
            self.mm_xyq_image_wait_budget_s = float(g("MM_XYQ_IMAGE_WAIT_BUDGET_S", "150"))
            self.mm_xyq_image_poll_interval_s = float(g("MM_XYQ_IMAGE_POLL_INTERVAL_S", "2"))
            self.mm_image_download_timeout_s = float(g("MM_IMAGE_DOWNLOAD_TIMEOUT_S", "60"))
            self.mm_image_max_mb = int(g("MM_IMAGE_MAX_MB", "32"))
            self.mm_video_create_timeout_s = float(g("MM_VIDEO_CREATE_TIMEOUT_S", "15"))
            self.mm_video_wait_budget_s = float(g("MM_VIDEO_WAIT_BUDGET_S", "45"))
            self.mm_video_poll_timeout_s = float(g("MM_VIDEO_POLL_TIMEOUT_S", "15"))
            self.mm_video_download_timeout_s = float(g("MM_VIDEO_DOWNLOAD_TIMEOUT_S", "90"))
            self.mm_video_max_mb = int(g("MM_VIDEO_MAX_MB", "256"))
            self.mm_ppt_create_timeout_s = float(g("MM_PPT_CREATE_TIMEOUT_S", "75"))
            self.mm_ppt_poll_timeout_s = float(g("MM_PPT_POLL_TIMEOUT_S", "15"))
            self.mm_ppt_download_timeout_s = float(g("MM_PPT_DOWNLOAD_TIMEOUT_S", "45"))
            self.database_url = g("DATABASE_URL", "")
            self.milvus_uri = g("MILVUS_URI", "")
            self.redis_url = g("REDIS_URL", "")
            self.object_storage_endpoint = g("OBJECT_STORAGE_ENDPOINT", "")
            self.object_storage_bucket = g("OBJECT_STORAGE_BUCKET", "")
            self.object_storage_access_key = g("OBJECT_STORAGE_ACCESS_KEY", "")
            self.object_storage_secret_key = g("OBJECT_STORAGE_SECRET_KEY", "")
            self.object_storage_region = g("OBJECT_STORAGE_REGION", "auto")
            self.auth_secret = g("AUTH_SECRET", "")
            self.auth_required = _env_bool("AUTH_REQUIRED")
            self.auth_token_minutes = int(g("AUTH_TOKEN_MINUTES", "10080"))
            self.embedding_backend = g("EMBEDDING_BACKEND", "auto")
            self.iflytek_embedding_url = g(
                "IFLYTEK_EMBEDDING_URL", "https://emb-cn-huabei-1.xf-yun.com/"
            )
            self.embedding_timeout_s = float(g("EMBEDDING_TIMEOUT_S", "12"))
            self.rerank_mode = g("RERANK_MODE", "auto")
            self.rerank_api_url = g("RERANK_API_URL", "")
            self.rerank_api_key = g("RERANK_API_KEY", "")
            self.rerank_top_k = int(g("RERANK_TOP_K", "5"))
            self.demo_mode = g("DEMO_MODE", "auto")
            self.trace_enabled = g("TRACE_ENABLED", "true").lower() not in {"0", "false", "no", "off"}
            self.backend_port = int(g("BACKEND_PORT", "8000"))
            self.frontend_origin = g("FRONTEND_ORIGIN", "http://localhost:3000")


BASE_DIR = Path(__file__).resolve().parent          # backend/app
DATA_DIR = BASE_DIR / "data"
CORPUS_DIR = DATA_DIR / "seed_corpus"
EXTRA_SOURCES_DIR = DATA_DIR / "extra_sources"
UPLOAD_SOURCES_DIR = DATA_DIR / "uploaded_sources"
STATIC_DIR = BASE_DIR / "static"
GEN_DIR = STATIC_DIR / "gen"
GEN_DIR.mkdir(parents=True, exist_ok=True)
RUNS_DIR = BASE_DIR.parent / "runs"

COURSE_NAME = "数据结构与算法"


def _env_file_paths() -> tuple[Path, ...]:
    """固定读取仓库根目录和 backend 目录的 .env,避免受启动目录影响。"""
    return (BASE_DIR.parent.parent / ".env", BASE_DIR.parent / ".env")


def _load_env_files() -> None:
    initial_keys = set(os.environ)
    for env_path in _env_file_paths():
        if not env_path.exists():
            continue
        for raw in env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            if not key or key in initial_keys:
                continue
            os.environ[key] = value.strip().strip('"').strip("'")


@lru_cache
def get_settings() -> "Settings":
    _load_env_files()
    env_files = tuple(path for path in _env_file_paths() if path.exists())
    try:
        return Settings(_env_file=env_files)  # type: ignore[call-arg]
    except TypeError:
        return Settings()



def is_demo() -> bool:
    """无星火密钥 → 自动演示模式;可用 DEMO_MODE 显式覆盖。"""
    s = get_settings()
    flag = (s.demo_mode or "auto").lower()
    if flag in {"1", "true", "yes", "on"}:
        return True
    if flag in {"0", "false", "no", "off"}:
        return False
    return not bool(s.spark_api_password)


def auth_required() -> bool:
    """离线 demo 保持一键可用；真实模式默认必须经过登录认证。"""
    return False if is_demo() else bool(get_settings().auth_required)


def sqlite_default_url() -> str:
    return f"sqlite:///{(BASE_DIR.parent / 'sparklearn.db').as_posix()}"
