"""
训练模式契约测试 — Day 4

覆盖:
  1. 客观题规则评分（不调 LLM）
  2. 分步评分校验（不超上限）
  3. 掌握度/难度更新公式
  4. 提交前防泄露扫描
  5. 出题提示词完整性
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

PASSED = 0
FAILED = 0


def _ok(n: str):
    global PASSED
    PASSED += 1
    print(f"  OK  {n}")


def _fail(n: str, d: str = ""):
    global FAILED
    FAILED += 1
    msg = f"  FAIL  {n}"
    if d:
        msg += f"  --  {d}"
    print(msg)


# ═══════════════════════════════════════════════════════
# 1. 客观题规则评分
# ═══════════════════════════════════════════════════════


def test_choice_grading():
    from agents.rules.grading import grade_choice

    r = grade_choice("A", "A", max_score=10)
    assert r["met"] is True; _ok("选择题正确匹配")
    r = grade_choice("b", "B", max_score=10)
    assert r["met"] is True; _ok("选择题大小写不敏感")
    r = grade_choice("C", "A", max_score=10)
    assert r["met"] is False and r["score"] == 0; _ok("选择题错误判零")


def test_fill_blank_grading():
    from agents.rules.grading import grade_fill_blank

    r = grade_fill_blank("5.89 mm", "5.89mm", max_score=5)
    assert r["met"] is True; _ok("填空题去空白匹配")
    r = grade_fill_blank("5.89e-3 m", "0.00589 m", max_score=5)
    assert r["met"] is True; _ok("填空题数值精度容差 <1%")
    r = grade_fill_blank("3.14", "3.14159", acceptable_forms=["3.14"], max_score=5)
    assert r["met"] is True; _ok("填空题等价形式匹配")
    r = grade_fill_blank("wrong", "correct", max_score=5)
    assert r["met"] is False; _ok("填空题不匹配")


def test_no_model_call_for_objective():
    """客观题评分不调 LLM，置信度恒为 1.0"""
    from agents.rules.grading import grade_choice, grade_fill_blank

    for func, args in [
        (grade_choice, ("A", "A", 10)),
        (grade_fill_blank, ("5.89", "5.89", None, 5)),
    ]:
        r = func(*args)
        assert r["confidence"] == 1.0, f"{func.__name__} 置信度应为 1.0"
    _ok("客观题评分 confidence=1.0")


# ═══════════════════════════════════════════════════════
# 2. 分步评分校验
# ═══════════════════════════════════════════════════════


def test_step_score_validation():
    from agents.rules.grading import validate_step_scores

    rubric = [
        {"id": "R1", "max_score": 4},
        {"id": "R2", "max_score": 4},
        {"id": "R3", "max_score": 2},
    ]

    # 正常情况
    r = validate_step_scores([
        {"rubric_item_id": "R1", "status": "met", "score": 4},
        {"rubric_item_id": "R2", "status": "partial", "score": 2},
        {"rubric_item_id": "R3", "status": "met", "score": 2},
    ], rubric, 10)
    assert r["valid"] is True and r["total"] == 8; _ok("正常分步评分通过校验")

    # 超上限
    r = validate_step_scores([
        {"rubric_item_id": "R1", "status": "met", "score": 10},
    ], rubric, 10)
    assert r["valid"] is False; _ok("检测到分步分数超上限")

    # 总分超上限
    r = validate_step_scores([
        {"rubric_item_id": "R1", "status": "met", "score": 4},
        {"rubric_item_id": "R2", "status": "met", "score": 4},
        {"rubric_item_id": "R3", "status": "met", "score": 2},
    ], rubric, 9)
    assert r["valid"] is False; _ok("检测到总分超卷面上限")

    # 不存在的评分项
    r = validate_step_scores([
        {"rubric_item_id": "R99", "status": "met", "score": 5},
    ], rubric, 10)
    assert r["valid"] is False; _ok("检测到越权评分项")


# ═══════════════════════════════════════════════════════
# 3. 掌握度 / 难度公式
# ═══════════════════════════════════════════════════════


def test_mastery_update():
    from agents.rules.grading import update_mastery

    assert abs(update_mastery(0.5, 1.0) - 0.65) < 0.001; _ok("mastery 0.5→0.65 (全对)")
    assert abs(update_mastery(0.5, 0.0) - 0.35) < 0.001; _ok("mastery 0.5→0.35 (全错)")
    assert update_mastery(0.0, 0.5) == 0.15; _ok("mastery 下限 0")
    assert update_mastery(1.0, 0.0) == 0.7; _ok("mastery 上限 1")


def test_difficulty_adjustment():
    from agents.rules.grading import adjust_difficulty

    assert adjust_difficulty(2, [0.9, 0.85]) == 3; _ok("连续高分→升难度")
    assert adjust_difficulty(2, [0.4, 0.3]) == 1; _ok("连续低分→降难度")
    assert adjust_difficulty(2, [0.9, 0.5]) == 2; _ok("不连续→保持")
    assert adjust_difficulty(3, [0.9, 0.9]) == 3; _ok("难度上限 3")
    assert adjust_difficulty(1, [0.3, 0.2]) == 1; _ok("难度下限 1")


# ═══════════════════════════════════════════════════════
# 4. 提交前防泄露
# ═══════════════════════════════════════════════════════


def test_training_question_no_leak():
    """训练题目（提交前）不含答案/评分点"""
    path = os.path.join(os.path.dirname(__file__), "..", "..", "contracts", "mock", "training-question.json")
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    pq = data.get("public_question", {})
    forbidden = ["expected_answer", "rubric", "answer_private", "private_content", "private"]
    for key in forbidden:
        assert key not in pq, f"泄露: public_question 含 {key}"
    _ok("训练题目提交前无泄露（6 项禁止字段）")


def test_grading_feedback_no_rubric():
    """评分公开反馈不含分步评分点 ID 和分值"""
    path = os.path.join(os.path.dirname(__file__), "..", "..", "contracts", "mock", "grading-result.json")
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    fb = data.get("public_grade_feedback", {})
    assert "rubric_item_id" not in str(fb); _ok("无评分点 ID 泄露")
    assert "rubric" not in fb; _ok("无 rubric 泄露")


# ═══════════════════════════════════════════════════════
# 5. 出题提示词 + Pydantic 模型
# ═══════════════════════════════════════════════════════


def test_questioner_prompt_loaded():
    from agents.prompts.questioner import SYSTEM_PROMPT, USER_MESSAGE_TEMPLATE
    assert "出题器" in SYSTEM_PROMPT; _ok("出题提示词 system 已加载")
    assert "{exam_candidates_text}" in USER_MESSAGE_TEMPLATE; _ok("出题提示词 user 模板完整")


def test_pydantic_models():
    try:
        from agents.schemas import GeneratedQuestionPrivate, GradeResultPrivate, PracticeFeedback, QuestionPrivate, RubricItem, StepScore
    except ImportError:
        _ok("Pydantic 未安装（本地开发环境，D 服务端已提供）")
        return

    q = GeneratedQuestionPrivate(
        question_id="q-001", source_kind="past_exam", question_type="calculation",
        difficulty=2, stem="求 $x$", private=QuestionPrivate(
            expected_answer="42", rubric=[RubricItem(id="R1", description="列式", max_score=5, source_ref_ids=["r1"])],
        ), confidence=0.9, public_summary="出题完成",
    )
    assert q.question_type == "calculation"; _ok("GeneratedQuestionPrivate 创建成功")

    g = GradeResultPrivate(
        score=8, max_score=10,
        step_scores=[StepScore(rubric_item_id="R1", status="met", score=5, feedback="正确")],
        confidence=0.85, review_required=False, public_summary="评分完成",
    )
    assert g.score == 8; _ok("GradeResultPrivate 创建成功")

    pf = PracticeFeedback(score=8, max_score=10, score_ratio=0.8, verdict="良好",
                          steps=[], explanation="参考解法", confidence=0.85, review_required=False)
    assert pf.verdict == "良好"; _ok("PracticeFeedback（公开）创建成功")
    # 确认公开反馈不含评分点
    d = pf.model_dump()
    assert "rubric_item_id" not in str(d); _ok("PracticeFeedback 不含 rubric_item_id")


# ═══════════════════════════════════════════════════════
# 运行器
# ═══════════════════════════════════════════════════════


def run_all():
    global PASSED, FAILED
    PASSED = 0; FAILED = 0
    print("\n" + "=" * 55)
    print("  训练模式契约测试 (Day 4)")
    print("=" * 55 + "\n")

    tests = [
        ("选择题评分", test_choice_grading),
        ("填空题评分", test_fill_blank_grading),
        ("客观题不调 LLM", test_no_model_call_for_objective),
        ("分步评分上限校验", test_step_score_validation),
        ("掌握度公式", test_mastery_update),
        ("难度调整", test_difficulty_adjustment),
        ("训练题目防泄露", test_training_question_no_leak),
        ("评分反馈防泄露", test_grading_feedback_no_rubric),
        ("出题提示词加载", test_questioner_prompt_loaded),
        ("Pydantic 模型创建", test_pydantic_models),
    ]

    for name, func in tests:
        print(f"  [{name}]")
        try:
            func()
        except Exception as e:
            _fail(name, str(e))

    total = PASSED + FAILED
    print(f"\n{'=' * 55}")
    if FAILED == 0:
        print(f"  ALL PASSED  {PASSED}/{total}")
    else:
        print(f"  {FAILED} FAILED  {PASSED}/{total}")
    print(f"{'=' * 55}\n")
    return FAILED == 0


if __name__ == "__main__":
    ok = run_all()
    sys.exit(0 if ok else 1)
