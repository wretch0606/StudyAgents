"""
配置管理 — 环境变量读取 + 默认值

所有可变参数集中在此外露，不在业务代码中硬编码。
"""

import os
from pathlib import Path

# ---- 基础路径 ----
BASE_DIR = Path(__file__).resolve().parent.parent.parent  # Agent/ (src/worker/config.py → src/ → Agent/)
FILES_ROOT = Path(os.getenv("FILES_ROOT", BASE_DIR / "data" / "files"))
PAGE_IMAGES_DIR = FILES_ROOT / "pages"

# ---- 数据库 ----
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg://postgres:postgres@localhost:5432/studyagents",
)
ASYNC_DATABASE_URL = os.getenv(
    "ASYNC_DATABASE_URL",
    "postgresql+asyncpg://postgres:postgres@localhost:5432/studyagents",
)

# ---- Embedding ----
EMBEDDING_PROVIDER = os.getenv("EMBEDDING_PROVIDER", "api")     # "api" | "local"
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "text-embedding-3-small")
EMBEDDING_API_BASE = os.getenv("EMBEDDING_API_BASE", "")
EMBEDDING_API_KEY = os.getenv("EMBEDDING_API_KEY", "")

# ---- 模型 API（文本/视觉，供 B 模块内少量判断用）----
MODEL_BASE_URL = os.getenv("MODEL_BASE_URL", "")
MODEL_API_KEY = os.getenv("MODEL_API_KEY", "")
MODEL_TEXT_NAME = os.getenv("MODEL_TEXT_NAME", "")
MODEL_VISION_NAME = os.getenv("MODEL_VISION_NAME", "")

# ---- 上传限制 ----
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "100"))

# ---- 阈值 ----
OCR_REVIEW_THRESHOLD = float(os.getenv("OCR_REVIEW_THRESHOLD", "0.80"))
DIGITAL_TEXT_MIN_CHARS = int(os.getenv("DIGITAL_TEXT_MIN_CHARS", "80"))

# ---- 切块 ----
CHUNK_TARGET_CHARS = int(os.getenv("CHUNK_TARGET_CHARS", "500"))
CHUNK_MAX_CHARS = int(os.getenv("CHUNK_MAX_CHARS", "800"))
CHUNK_OVERLAP_CHARS = int(os.getenv("CHUNK_OVERLAP_CHARS", "80"))
CHUNK_MIN_MERGE_CHARS = int(os.getenv("CHUNK_MIN_MERGE_CHARS", "100"))

# ---- 检索 ----
RETRIEVAL_VECTOR_K = int(os.getenv("RETRIEVAL_VECTOR_K", "20"))
RETRIEVAL_KEYWORD_K = int(os.getenv("RETRIEVAL_KEYWORD_K", "20"))
RETRIEVAL_FINAL_K = int(os.getenv("RETRIEVAL_FINAL_K", "8"))
RRF_K = int(os.getenv("RRF_K", "60"))

# ---- Worker ----
LEASE_DURATION = int(os.getenv("LEASE_DURATION", "300"))
WORKER_POLL_INTERVAL = int(os.getenv("WORKER_POLL_INTERVAL", "2"))   # 轮询间隔（秒）
WORKER_HEARTBEAT = int(os.getenv("WORKER_HEARTBEAT", "60"))         # 心跳间隔（秒）

# ---- 请求超时 ----
HTTP_CONNECT_TIMEOUT = int(os.getenv("HTTP_CONNECT_TIMEOUT", "10"))
HTTP_TOTAL_TIMEOUT = int(os.getenv("HTTP_TOTAL_TIMEOUT", "25"))

# ---- 调试 ----
APP_ENV = os.getenv("APP_ENV", "development")
DEBUG = APP_ENV != "production"


def ensure_dirs():
    """确保必要的本地目录存在"""
    FILES_ROOT.mkdir(parents=True, exist_ok=True)
    PAGE_IMAGES_DIR.mkdir(parents=True, exist_ok=True)
