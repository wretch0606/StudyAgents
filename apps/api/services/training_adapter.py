"""TrainingAdapter — C 的出题适配器接口与 Fake 实现。

C 的真实实现必须符合 TrainingAdapterProtocol。
FakeTrainingAdapter 模拟出题行为，用于 D 侧测试。
"""

from __future__ import annotations

from typing import Protocol


class TrainingAdapterProtocol(Protocol):
    """C 的出题适配器接口。"""

    async def generate_questions(
        self,
        *,
        session_id: str,
        user_id: str,
        chapter_ids: list[str],
        question_types: list[str],
        difficulty: int,
        count: int,
    ) -> list[dict]:
        """生成 count 道题。

        返回: [{"public": PublicQuestion, "private": GeneratedQuestionPrivate}, ...]
        若证据不足，返回少于 count 的结果（最少 3 题）。
        """
        ...


class FakeTrainingAdapter:
    """模拟 C 的出题行为。

    - 默认生成指定数量的伪随机题目（至少 3 题）
    - 场景 evidence_insufficient: 只生成 1 题，触发明确错误
    """

    def __init__(self, *, scenario: str = "normal", question_count: int = 5):
        self._scenario = scenario
        self._count = question_count
        self._generated: dict[str, int] = {}  # session_id → count

    async def generate_questions(
        self,
        *,
        session_id: str,
        user_id: str,  # noqa: ARG002
        chapter_ids: list[str],
        question_types: list[str],
        difficulty: int,
        count: int,
    ) -> list[dict]:
        """生成伪随机题目。"""
        actual_count = count
        if self._scenario == "evidence_insufficient":
            actual_count = 1  # 只有 1 题，无法满足最少 3 题要求

        questions = []
        for i in range(actual_count):
            qtype = question_types[i % len(question_types)] if question_types else "choice"
            q = {
                "public": {
                    "item_id": f"q-{session_id[:8]}-{i + 1}",
                    "order_no": i + 1,
                    "question_type": qtype,
                    "difficulty": difficulty,
                    "stem": _STEMS[i % len(_STEMS)],
                    "source_kind": "generated_variant",
                    "source_label": f"模拟题 {i + 1}",
                    "progress": {"current": i + 1, "total": actual_count},
                },
                "private": {
                    "question_id": f"q-{session_id[:8]}-{i + 1}",
                    "source_kind": "generated_variant",
                    "question_type": qtype,
                    "difficulty": difficulty,
                    "stem": _STEMS[i % len(_STEMS)],
                    "confidence": 0.85,
                    "private": {
                        "expected_answer": _ANSWERS[i % len(_ANSWERS)],
                        "rubric": [
                            {"id": "R1", "description": "概念理解", "max_score": 3},
                            {"id": "R2", "description": "计算过程", "max_score": 4},
                            {"id": "R3", "description": "最终答案", "max_score": 3},
                        ],
                    },
                },
            }
            questions.append(q)

        self._generated[session_id] = actual_count
        return questions


_STEMS = [
    "在杨氏双缝干涉实验中，两缝间距 d=0.2mm，缝与屏距离 D=1.0m，"
    "用波长 λ=500nm 的单色光照射。求相邻明条纹间距 Δx。",
    "质量为 m=2kg 的物体从静止开始沿光滑斜面下滑，斜面倾角 θ=30°。"
    "求 2s 末物体的速度。",
    "求函数 f(x)=x³-3x²+2 在 [-1,3] 上的最大值和最小值。",
    "某理想气体在等温过程中体积从 V₁=2L 膨胀到 V₂=6L，对外做功 400J。"
    "求气体的初始压强。",
    "写出下列反应的离子方程式：碳酸钙与盐酸反应。",
    "已知数列 {aₙ} 满足 a₁=1, aₙ₊₁=2aₙ+1，求通项公式。",
    "在 ΔABC 中，a=3, b=4, C=60°，求 c 边的长度。",
]

_ANSWERS = [
    "Δx = λD/d = (500×10⁻⁹)(1.0)/(0.2×10⁻³) = 2.5×10⁻³m = 2.5mm",
    "v = g×sin30°×t = 9.8×0.5×2 = 9.8 m/s",
    "f(-1)=4, f(0)=2, f(2)=-2, f(3)=20，最大值 20，最小值 -2",
    "p₁ = W/(V₂-V₁) = 400/(6-2) = 100 kPa（等温过程）",
    "CaCO₃ + 2H⁺ = Ca²⁺ + H₂O + CO₂↑",
    "aₙ = 2ⁿ - 1（构造等比数列 aₙ+1=2(aₙ₋₁+1)）",
    "c² = a² + b² - 2ab·cosC = 9+16-24×0.5 = 13, c = √13",
]
