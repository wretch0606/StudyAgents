"""
证据充足性判断

纯函数，不依赖外部服务。基于规则判断检索结果是否足以回答问题。
"""

from dataclasses import dataclass, field

from apps.worker.schemas import EvidenceSufficiency, SourceRef


@dataclass
class SufficiencyResult:
    """充足性判断结果"""
    sufficient: bool
    reason: EvidenceSufficiency
    detail: str = ""
    requires_vision: bool = False


def judge_sufficiency(
    source_refs: list[SourceRef],
    query: str = "",
    query_embedding_similarity: float = 1.0,
) -> SufficiencyResult:
    """
    判断检索证据是否足够回答问题。

    判断规则（按优先级）：
      1. 无结果 → NO_RESULTS
      2. 全部为 staff_only → STAFF_ONLY
      3. 最大 RRF 分数过低 → TOPIC_MISMATCH
      4. 查询含计算关键词但证据无数值 → MISSING_CONDITION
      5. 需要图像但页图不可用 → IMAGE_UNAVAILABLE
      6. 多来源核心结论冲突 → CONFLICTING
      7. 通过 → SUFFICIENT
    """
    # 规则 1：无结果
    if not source_refs:
        return SufficiencyResult(
            sufficient=False,
            reason=EvidenceSufficiency.NO_RESULTS,
            detail="知识库中未找到相关内容",
        )

    # 规则 2：全部私有
    if all(_is_staff_only(ref) for ref in source_refs):
        return SufficiencyResult(
            sufficient=False,
            reason=EvidenceSufficiency.STAFF_ONLY,
            detail="相关内容为受限资料，无法向学生展示",
        )

    # 过滤掉私有块后的有效结果
    public_refs = [ref for ref in source_refs if not _is_staff_only(ref)]
    if not public_refs:
        return SufficiencyResult(
            sufficient=False,
            reason=EvidenceSufficiency.STAFF_ONLY,
            detail="所有匹配内容均为受限资料",
        )

    # 规则 3：主题不匹配（最高分低于阈值）
    max_score = max(ref.score for ref in public_refs)
    if max_score < 0.05:
        return SufficiencyResult(
            sufficient=False,
            reason=EvidenceSufficiency.TOPIC_MISMATCH,
            detail=f"检索结果与问题相关性过低（最高分: {max_score:.4f}）",
        )

    # 规则 4：计算条件缺失
    if _needs_computation(query) and not _has_numeric_evidence(public_refs):
        return SufficiencyResult(
            sufficient=False,
            reason=EvidenceSufficiency.MISSING_CONDITION,
            detail="问题涉及计算，但检索结果中缺少必要的数值条件",
        )

    # 规则 5：图片不可用
    requires_vision = any(
        ref.page_image_url is None and "[图" in ref.excerpt
        for ref in public_refs
    )
    if requires_vision and _needs_visual(query):
        return SufficiencyResult(
            sufficient=False,
            reason=EvidenceSufficiency.IMAGE_UNAVAILABLE,
            detail="问题需要查看图表，但相关页图不可用",
        )

    # 规则 6：多来源核心结论冲突（简化启发式）
    if len(public_refs) >= 3 and _has_conflicting_claims(public_refs):
        return SufficiencyResult(
            sufficient=False,
            reason=EvidenceSufficiency.CONFLICTING,
            detail="多个来源的核心结论不一致，建议人工核验",
        )

    # 通过
    return SufficiencyResult(
        sufficient=True,
        reason=EvidenceSufficiency.SUFFICIENT,
        detail=f"找到 {len(public_refs)} 条可引用证据",
        requires_vision=requires_vision,
    )


# ============================================================
# 辅助判断函数
# ============================================================

# 计算类关键词
_COMPUTATION_KEYWORDS = {
    "计算", "求", "求解", "算出", "推导", "证明", "推导出",
    "等于", "是多少", "多大", "求值", "推导过程",
    "calculate", "compute", "solve", "derive", "evaluate",
}

# 视觉类关键词
_VISUAL_KEYWORDS = {
    "如图", "见图", "图中", "下图", "上图", "所示", "示意图",
    "曲线", "图像", "图表", "图示", "看图",
}

# 否定/相反结论关键词（用于冲突检测）
_NEGATION_KEYWORDS = {"不是", "并非", "错误", "不正确", "反之", "相反", "但", "然而"}


def _is_staff_only(ref: SourceRef) -> bool:
    """检查是否为私有块（摘录中包含答案标记）"""
    return "[答案]" in ref.excerpt or "[评分点]" in ref.excerpt


def _needs_computation(query: str) -> bool:
    """判断查询是否涉及计算"""
    return any(kw in query.lower() for kw in _COMPUTATION_KEYWORDS)


def _needs_visual(query: str) -> bool:
    """判断查询是否需要视觉信息"""
    return any(kw in query for kw in _VISUAL_KEYWORDS)


def _has_numeric_evidence(refs: list[SourceRef]) -> bool:
    """检查证据中是否包含数值数据"""
    import re
    num_pattern = re.compile(r"\d+(\.\d+)?\s*[a-zA-Z]*[=＝]|"  # 等式
                             r"\d+\s*[（）(]\s*[a-zA-Z一-鿿]+\s*[)）]|"  # 数值(单位)
                             r"[=＝]\s*\d+(\.\d+)?")             # = 数值
    for ref in refs:
        if num_pattern.search(ref.excerpt):
            return True
    return False


def _has_conflicting_claims(refs: list[SourceRef]) -> bool:
    """
    简化冲突检测：如果多段摘录中存在否定词且来自不同文档，
    可能存在冲突。
    """
    neg_count = 0
    doc_ids = set()
    for ref in refs:
        if any(kw in ref.excerpt for kw in _NEGATION_KEYWORDS):
            neg_count += 1
            doc_ids.add(ref.document_id)

    # 多个文档都含否定表述 → 标记潜在冲突
    return neg_count >= 2 and len(doc_ids) >= 2
