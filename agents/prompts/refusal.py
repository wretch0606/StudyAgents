"""
拒答模板 — V1.0

对应开发文档 5.7 节。7 种拒答场景，每种包含：
- 当前无法确认的结论
- 已检索的范围
- 建议补充的资料
"""

from typing import Optional

# ── 拒答原因 → 对用户展示的文案映射 ──────────────


class RefusalTemplate:
    """根据 reason 生成拒答文本"""

    REASON_MAP: dict[str, dict[str, str]] = {
        "no_results": {
            "label": "未找到相关内容",
            "message": "当前无法确认该问题的答案。",
            "action": "换个问法试试",
        },
        "topic_mismatch": {
            "label": "主题不匹配",
            "message": "当前知识库未覆盖该主题，无法确认答案。",
            "action": "确认问题是否在课程范围内",
        },
        "missing_condition": {
            "label": "计算条件不足",
            "message": "回答问题缺少关键的数值或条件，无法完成计算。",
            "action": "补充必要的数值或条件后重新提问",
        },
        "conflicting": {
            "label": "来源信息矛盾",
            "message": "不同资料中的信息存在矛盾，暂时无法给出确定答案。",
            "action": "已记录该矛盾，管理员将进行人工核验",
        },
        "staff_only": {
            "label": "受限内容",
            "message": "该问题的相关证据仅限内部使用，不向学生展示。",
            "action": "可咨询教师获取更多信息",
        },
        "image_unavailable": {
            "label": "图表暂时不可用",
            "message": "回答该问题需要查看图表，但相关页图暂时无法访问。",
            "action": "稍后重试或查阅原始资料",
        },
    }

    @classmethod
    def build(
        cls,
        reason: str,
        searched_chapters: Optional[list[str]] = None,
        suggestion: Optional[str] = None,
    ) -> dict[str, str]:
        """
        生成拒答的公开响应。

        Returns:
            {
                "conclusion": "当前无法确认...",
                "searched_scope": "已在第1-3章中检索...",
                "suggestion": "建议补充资料或换个问法"
            }
        """
        info = cls.REASON_MAP.get(reason, cls.REASON_MAP["no_results"])

        # 检索范围
        scope = "已在全部资料范围内检索"
        if searched_chapters:
            chapters = "、".join(searched_chapters)
            scope = f"已在以下章节中检索：{chapters}"

        # 建议
        if suggestion is None:
            suggestion = info["action"]

        return {
            "conclusion": f"「{info['label']}」{info['message']}",
            "searched_scope": scope,
            "suggestion": suggestion,
            "refusal_reason": reason,
        }


# ── 知识 Agent 输出中的拒答判断逻辑 ─────────────────


def should_refuse(sufficient: bool, reason: str) -> bool:
    """知识 Agent 输出了 sufficient=false 时应拒答"""
    return not sufficient


def is_retryable_refusal(reason: str) -> bool:
    """某些拒答用户可以修改输入后重试"""
    return reason in ("no_results", "topic_mismatch", "missing_condition")
