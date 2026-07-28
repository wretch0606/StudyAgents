"""
核心数据类定义 — 成员 B（知识库与 RAG）

SourceRef、PageResult、Chunk 等是 B 对外暴露的公共契约，
与 C（Agent）、D（后端）协商后确定，变更需同步更新版本号。
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional
from uuid import uuid4


# ============================================================
# 检索相关
# ============================================================

@dataclass
class SourceRef:
    """指向原始资料中某个位置的可引用证据"""
    document_id: str
    document_name: str
    page_number: int
    question_no: Optional[str] = None    # 如 "3" 或 "二.1"
    chunk_id: str = ""
    excerpt: str = ""                    # 摘录 ≤ 300 字
    page_image_url: Optional[str] = None
    score: float = 0.0                   # RRF 融合分数


@dataclass
class RetrievalFilters:
    """检索过滤条件"""
    chapter_ids: list[str] = field(default_factory=list)
    question_types: Optional[list[str]] = None  # choice / fill_blank / calculation / short_answer
    difficulty: Optional[int] = None            # 1-3
    exclude_chunk_ids: list[str] = field(default_factory=list)
    knowledge_point_ids: list[str] = field(default_factory=list)
    year: Optional[int] = None


@dataclass
class RetrievalResult:
    """混合检索的完整返回"""
    source_refs: list[SourceRef]
    sufficient: bool
    reason: str
    requires_vision: bool = False
    elapsed_ms: float = 0.0


class EvidenceSufficiency(str, Enum):
    """证据充足性枚举"""
    SUFFICIENT = "sufficient"
    NO_RESULTS = "no_results"
    TOPIC_MISMATCH = "topic_mismatch"
    MISSING_CONDITION = "missing_condition"
    CONFLICTING = "conflicting"
    STAFF_ONLY = "staff_only"
    IMAGE_UNAVAILABLE = "image_unavailable"


# ============================================================
# 解析与页面
# ============================================================

class BlockType(str, Enum):
    TEXT = "text"
    FORMULA = "formula"
    TABLE = "table"
    FIGURE = "figure"


class PageType(str, Enum):
    DIGITAL = "digital"    # 数字文本，可直接提取
    SCANNED = "scanned"    # 扫描件，需 OCR


@dataclass
class LayoutBlock:
    """版面结构块"""
    bbox: tuple[float, float, float, float]  # x0, y0, x1, y1
    block_type: BlockType
    content: str                              # text→纯文本, formula→LaTeX, table→Markdown
    confidence: float
    reading_order: int


@dataclass
class PageResult:
    """单页解析结果"""
    page_no: int
    text: str                        # 纯文本
    image_path: str                  # 页图保存路径（相对路径）
    layout: list[LayoutBlock] = field(default_factory=list)
    confidence: float = 1.0
    is_digital: bool = True


# ============================================================
# 版面结构化
# ============================================================

@dataclass
class Section:
    """章节区域"""
    heading: Optional[str]        # 标题文本
    level: int                    # 1-4
    paragraphs: list[str] = field(default_factory=list)
    formulas: list[str] = field(default_factory=list)    # LaTeX
    image_refs: list[str] = field(default_factory=list)


@dataclass
class TableBlock:
    """表格块"""
    markdown: str
    headers: list[str] = field(default_factory=list)
    page_no: int = 0
    bbox: Optional[tuple[float, float, float, float]] = None


@dataclass
class FigureBlock:
    """图表块"""
    image_path: str
    caption: str = ""
    page_no: int = 0
    bbox: Optional[tuple[float, float, float, float]] = None


@dataclass
class StructuredPage:
    """结构化后的页面"""
    page_no: int
    sections: list[Section] = field(default_factory=list)
    tables: list[TableBlock] = field(default_factory=list)
    figures: list[FigureBlock] = field(default_factory=list)


# ============================================================
# 切块
# ============================================================

class ChunkVisibility(str, Enum):
    PUBLIC = "public"
    STAFF_ONLY = "staff_only"


class MaterialType(str, Enum):
    TEXT = "text"
    EXAM = "exam"
    FORMULA = "formula"
    TABLE = "table"


@dataclass
class Chunk:
    """知识块 — 检索最小单元"""
    chunk_id: str = field(default_factory=lambda: str(uuid4()))
    document_id: str = ""
    page_from: int = 0
    page_to: int = 0
    content: str = ""
    private_content: Optional[str] = None   # 答案块（仅 staff 可访问）
    question_no: Optional[str] = None
    section_path: list[str] = field(default_factory=list)  # ["第三章", "3.1"]
    knowledge_point_ids: list[str] = field(default_factory=list)
    material_type: MaterialType = MaterialType.TEXT
    year: Optional[int] = None
    image_refs: list[str] = field(default_factory=list)
    visibility: ChunkVisibility = ChunkVisibility.PUBLIC
    content_version: int = 1


# ============================================================
# 真题
# ============================================================

class QuestionType(str, Enum):
    CHOICE = "choice"
    FILL_BLANK = "fill_blank"
    CALCULATION = "calculation"
    SHORT_ANSWER = "short_answer"


@dataclass
class Option:
    """选择题选项"""
    id: str                          # "A", "B", "C", "D"
    text: str


@dataclass
class RubricItem:
    """评分点"""
    id: str                          # "R1"
    description: str
    max_score: float
    source_ref_ids: list[str] = field(default_factory=list)


@dataclass
class ExamQuestion:
    """结构化真题"""
    document_id: str
    question_no: str                 # "3" 或 "二.1"
    part_no: Optional[str] = None    # 子题号
    question_type: QuestionType = QuestionType.CHOICE
    stem: str = ""                   # 题干（含 LaTeX）
    options: list[Option] = field(default_factory=list)
    max_score: Optional[float] = None
    answer_private: str = ""         # 私有，不入检索
    rubric_private: list[RubricItem] = field(default_factory=list)
    knowledge_point_ids: list[str] = field(default_factory=list)
    source_ref: Optional[SourceRef] = None
    confidence: float = 1.0
    answer_origin: str = "original"  # original / ai_reviewed


# ============================================================
# 导入任务
# ============================================================

class IngestionStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED_RETRYABLE = "failed_retryable"
    FAILED_PERMANENT = "failed_permanent"


class IngestionStage(str, Enum):
    VALIDATING = "validating"
    EXTRACTING = "extracting"
    OCR = "ocr"
    STRUCTURING = "structuring"
    EXAM_EXTRACTION = "exam_extraction"
    CHUNKING = "chunking"
    VECTORIZING = "vectorizing"
    INDEXING = "indexing"
    COMPLETING = "completing"


@dataclass
class IngestionJob:
    """导入任务"""
    job_id: str = field(default_factory=lambda: str(uuid4()))
    document_id: str = ""
    stage: IngestionStage = IngestionStage.VALIDATING
    status: IngestionStatus = IngestionStatus.PENDING
    progress: float = 0.0            # 0-100
    attempts: int = 0
    max_attempts: int = 2
    error: Optional[str] = None
    lease_until: Optional[str] = None  # ISO 8601


# ============================================================
# 复核
# ============================================================

class ReviewKind(str, Enum):
    OCR_FORMULA = "ocr_formula"
    OCR_TEXT = "ocr_text"
    MISSING_ANSWER = "missing_answer"
    LOW_CONFIDENCE = "low_confidence"


class ReviewStatus(str, Enum):
    PENDING = "pending"
    RESOLVED = "resolved"
    DISMISSED = "dismissed"


@dataclass
class ReviewItem:
    """低置信度复核项"""
    review_id: str = field(default_factory=lambda: str(uuid4()))
    kind: ReviewKind = ReviewKind.LOW_CONFIDENCE
    target_type: str = ""             # "document_page" / "exam_question" / "knowledge_chunk"
    target_id: str = ""
    confidence: float = 0.0
    status: ReviewStatus = ReviewStatus.PENDING
    payload: dict = field(default_factory=dict)
    resolution: Optional[str] = None


# ============================================================
# 文件校验
# ============================================================

# 允许的文件扩展名 → MIME 映射
ALLOWED_EXTENSIONS: dict[str, str] = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
}

# Magic bytes 签名校验（前 8 字节）
MAGIC_SIGNATURES: dict[str, bytes] = {
    ".pdf": b"%PDF-",
    ".docx": b"PK\x03\x04",
    ".pptx": b"PK\x03\x04",
    ".jpg": b"\xff\xd8\xff",
    ".jpeg": b"\xff\xd8\xff",
    ".png": b"\x89PNG\r\n\x1a\n",
}

# 默认上传限制
DEFAULT_MAX_UPLOAD_MB = 100

# 数字文本页判定阈值
DIGITAL_TEXT_MIN_CHARS = 80

# OCR / 答案复核阈值
DEFAULT_OCR_REVIEW_THRESHOLD = 0.80

# 切块参数
CHUNK_TARGET_CHARS = 500
CHUNK_MAX_CHARS = 800
CHUNK_OVERLAP_CHARS = 80
CHUNK_MIN_MERGE_CHARS = 100

# 检索参数
RETRIEVAL_VECTOR_K = 20
RETRIEVAL_KEYWORD_K = 20
RETRIEVAL_FINAL_K = 8
RRF_K = 60

# 租约时长（秒）
LEASE_DURATION = 300


@dataclass
class ValidationResult:
    """文件校验结果"""
    is_valid: bool
    filename: str = ""
    mime: str = ""
    sha256: str = ""
    size_bytes: int = 0
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    existing_document_id: Optional[str] = None  # 重复时返回已有文档
