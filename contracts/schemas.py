"""
C（Agent）接口契约 — 由 B（知识库）提供

变更需同步更新版本号。当前版本 V1.0。
C 可通过以下方式调用：
  1. 直接 import：from worker.retrieval.retriever import HybridRetriever
  2. 通过 D 的 API：POST /api/retrieve
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


# ============================================================
# 检索输入
# ============================================================

@dataclass
class RetrievalFilters:
    """
    检索过滤条件。

    所有字段可选，传空表示不过滤。
    训练模式下由协调 Agent 根据用户选择的章节/题型/难度填充。
    """
    chapter_ids: list[str] = field(default_factory=list)
    """章节 ID 列表，如 ["ch-03", "ch-05"]"""

    question_types: Optional[list[str]] = None
    """题型限制: "choice" | "fill_blank" | "calculation" | "short_answer" """

    difficulty: Optional[int] = None
    """难度限制: 1-3"""

    exclude_chunk_ids: list[str] = field(default_factory=list)
    """排除已用过的块 ID（避免同题重复）"""

    knowledge_point_ids: list[str] = field(default_factory=list)
    """限定知识点"""

    year: Optional[int] = None
    """限定真题年份"""


# ============================================================
# 检索输出
# ============================================================

@dataclass
class SourceRef:
    """
    指向原始资料中某个位置的可引用证据。

    每个知识性结论至少关联一个 SourceRef。
    C 负责在回答中引用 document_name + page_number。
    """
    document_id: str
    """文档 UUID"""

    document_name: str
    """文档展示名，如 "光学讲义.pdf" """

    page_number: int
    """页码（从 1 开始）"""

    question_no: Optional[str] = None
    """题号，如 "3" 或 "二.1"，非真题为 None"""

    chunk_id: str
    """知识块 UUID，用于去重和排除"""

    excerpt: str
    """摘录文本 (≤300 字)"""

    page_image_url: Optional[str] = None
    """页图 URL: /api/documents/{id}/pages/{n}/image"""

    score: float = 0.0
    """RRF 融合分数，用于结果排序"""


class EvidenceSufficiency(str, Enum):
    """证据充足性枚举 — 与 RetrievalResult.sufficient 配合使用"""
    SUFFICIENT = "sufficient"
    NO_RESULTS = "no_results"
    TOPIC_MISMATCH = "topic_mismatch"
    MISSING_CONDITION = "missing_condition"
    CONFLICTING = "conflicting"
    STAFF_ONLY = "staff_only"
    IMAGE_UNAVAILABLE = "image_unavailable"


@dataclass
class RetrievalResult:
    """
    混合检索完整返回。

    由 B 的 HybridRetriever.retrieve() 返回。
    C 根据 sufficient 决定进入回答节点还是拒答节点。
    """
    source_refs: list[SourceRef]
    """Top 8 可引用证据（已过滤权限）"""

    sufficient: bool
    """证据是否足以回答问题"""

    reason: str
    """充足性说明，对应 EvidenceSufficiency 的值:
       "sufficient" | "no_results" | "topic_mismatch" |
       "missing_condition" | "conflicting" | "staff_only" |
       "image_unavailable"
    """

    requires_vision: bool = False
    """是否需要将页图发送给视觉模型"""

    elapsed_ms: float = 0.0
    """检索耗时（毫秒）"""


# ============================================================
# 检索接口
# ============================================================

# 调用方式 1：直接调用
#   from worker.retrieval.retriever import HybridRetriever
#   result: RetrievalResult = await retriever.retrieve(
#       query="光的干涉条件是什么？",
#       query_embedding=[...],      # 可选，128/768/1536 维向量
#       filters=RetrievalFilters(
#           chapter_ids=["ch-03"],
#           question_types=["calculation"],
#           difficulty=2,
#       ),
#       user_role="member",         # "member" | "admin"
#   )

# 调用方式 2：通过 D 的 API
#   POST /api/retrieve
#   {
#     "query": "光的干涉条件是什么？",
#     "filters": { "chapter_ids": ["ch-03"] },
#     "top_k": 8
#   }
#   → {
#     "source_refs": [...],
#     "sufficient": true,
#     "reason": "sufficient",
#     "requires_vision": false,
#     "elapsed_ms": 320
#   }


# ============================================================
# 公开题目（训练模式）
# ============================================================

@dataclass
class PublicQuestion:
    """
    公开题目 — 不含答案和评分点。

    由出题 Agent 通过检索真题候选后生成，
    前端直接展示此结构。
    """
    item_id: str
    order_no: int
    source_kind: str
    """ "past_exam" | "generated_variant" """

    question_type: str
    """ "choice" | "fill_blank" | "calculation" | "short_answer" """

    difficulty: int
    """ 1-3 """

    stem: str
    """ 题干 (LaTeX 公式用 $...$ 或 $$...$$) """

    options: list[dict] = field(default_factory=list)
    """ 选择题选项 [{"id":"A","text":"..."}, ...] """

    source_label: str = ""
    """ 展示标签，如 "2024 年真题，第 3 题" """

    progress: dict = field(default_factory=dict)
    """ {"current": 2, "total": 5} """
