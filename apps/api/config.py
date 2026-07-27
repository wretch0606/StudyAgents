"""应用配置 — 全部从环境变量读取，无硬编码默认值（非开发环境）。"""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """FastAPI 应用配置。

    生产环境必须设置所有必填变量；开发环境可使用 .env 中的默认值。
    """

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}

    # ---- 环境 ----
    app_env: str = "development"

    # ---- 数据库 ----
    database_url: str = ""

    # ---- 安全 ----
    session_secret: str = ""

    # ---- 模型 ----
    model_base_url: str = ""
    model_api_key: str = ""
    model_text_name: str = ""
    model_vision_name: str = ""

    # ---- 嵌入 ----
    embedding_provider: str = "api"
    embedding_model: str = ""

    # ---- 文件 ----
    files_root: str = "/data/files"
    max_upload_mb: int = 100

    # ---- 阈值 ----
    ocr_review_threshold: float = 0.80
    grade_review_threshold: float = 0.70

    # ---- 检索 ----
    retrieval_vector_k: int = 20
    retrieval_keyword_k: int = 20
    retrieval_final_k: int = 8
    rrf_k: int = 60

    # ---- 限制 ----
    max_model_calls: int = 4
    max_node_hops: int = 8
    budget_cny: int = 100


settings = Settings()
