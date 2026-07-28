"""
生成样例 PDF 用于测试 PDF 解析器。

包含：
  1. 纯文本页（标题 + 段落）
  2. 含公式页（LaTeX 文本）
  3. 含表格页
  4. 模拟扫描页（仅图片）

用法：
  python tests/fixtures/generate_sample_pdf.py
"""

import fitz
from pathlib import Path

OUTPUT = Path(__file__).resolve().parent / "sample_lecture.pdf"


def create_sample_pdf():
    doc = fitz.open()

    # ========== 第 1 页：纯文本 ==========
    page1 = doc.new_page(width=595, height=842)  # A4
    y = 72  # 顶部边距
    margin_left = 72

    # 标题（使用内置 CJK 字体）
    page1.insert_text(
        fitz.Point(margin_left, y),
        "第三章 光的干涉",
        fontname="china-s", fontsize=18,
    )
    y += 40

    # 小节标题
    page1.insert_text(
        fitz.Point(margin_left, y),
        "3.1 相干光源与干涉条件",
        fontname="china-s", fontsize=14,
    )
    y += 30

    # 正文
    body_text = (
        "两列光波在空间相遇时，若满足相干条件，则会产生干涉现象。"
        "相干条件包括：两列光波具有相同的频率、相同的振动方向、"
        "以及固定的相位差。获得相干光的基本方法有两种：分波前法"
        "和分振幅法。杨氏双缝干涉实验是分波前法的典型代表。"
    )
    for line in _wrap_text(body_text, fontsize=11, max_width=450):
        page1.insert_text(fitz.Point(margin_left, y), line, fontname="china-ss", fontsize=11)
        y += 20

    y += 10
    body2 = (
        "在杨氏双缝实验中，设双缝间距为 d，缝到屏幕的距离为 D，"
        "波长为 λ，则相邻明条纹间距为 Δx = λD/d。当白光入射时，"
        "各级明条纹呈彩色分布。"
    )
    for line in _wrap_text(body2, fontsize=11, max_width=450):
        page1.insert_text(fitz.Point(margin_left, y), line, fontname="china-ss", fontsize=11)
        y += 20

    # ========== 第 2 页：含公式 ==========
    page2 = doc.new_page(width=595, height=842)
    y = 72

    page2.insert_text(
        fitz.Point(margin_left, y),
        "3.2 干涉条纹的特征",
        fontname="china-s", fontsize=14,
    )
    y += 30

    formula_text = (
        "光程差 δ 与相位差 Δφ 的关系为：$\\delta = r_2 - r_1$，"
        "相位差 $\\Delta\\varphi = \\frac{2\\pi}{\\lambda}\\delta$。"
    )
    for line in _wrap_text(formula_text, fontsize=11, max_width=450):
        page2.insert_text(fitz.Point(margin_left, y), line, fontname="china-ss", fontsize=11)
        y += 20

    y += 10
    formula2 = (
        "干涉极大条件：$\\delta = \\pm k\\lambda, k = 0,1,2,\\cdots$\n"
        "干涉极小条件：$\\delta = \\pm(2k+1)\\frac{\\lambda}{2}$"
    )
    for line in formula2.split("\n"):
        page2.insert_text(fitz.Point(margin_left, y), line, fontname="china-ss", fontsize=11)
        y += 22

    y += 15
    formula3 = (
        "相邻条纹间距：$$\\Delta x = \\frac{\\lambda D}{d}$$"
    )
    for line in formula3.split("\n"):
        page2.insert_text(fitz.Point(margin_left, y), line, fontname="china-ss", fontsize=11)
        y += 22

    # ========== 第 3 页：含表格 ==========
    page3 = doc.new_page(width=595, height=842)
    y = 72

    page3.insert_text(
        fitz.Point(margin_left, y),
        "3.3 典型干涉实验对比",
        fontname="china-s", fontsize=14,
    )
    y += 35

    # 画简单表格
    table_data = [
        ["实验名称", "光源", "条纹间距", "特点"],
        ["杨氏双缝", "单色光", "Δx=λD/d", "分波前法"],
        ["薄膜干涉", "单色光", "与厚度有关", "分振幅法"],
        ["牛顿环", "单色光", "r_k=√(kλR)", "等厚干涉"],
        ["迈克尔逊", "单色光", "Δd=λ/2", "精密测量"],
    ]

    col_widths = [100, 80, 110, 100]
    row_height = 25
    table_x = margin_left

    for row_idx, row in enumerate(table_data):
        x = table_x
        for col_idx, cell in enumerate(row):
            w = col_widths[col_idx]
            # 画单元格背景
            if row_idx == 0:
                page3.draw_rect(fitz.Rect(x, y, x + w, y + row_height), color=None, fill=(0.9, 0.9, 0.9))
            else:
                page3.draw_rect(fitz.Rect(x, y, x + w, y + row_height), color=(0, 0, 0), width=0.5)

            font = "hebo" if row_idx == 0 else "tiro"
            fontsize = 10 if row_idx == 0 else 9
            page3.insert_text(
                fitz.Point(x + 4, y + 17), str(cell),
                fontname=font, fontsize=fontsize,
            )
            x += w
        y += row_height

    # 表格下方说明
    y += 20
    note = "表 3-1  四种典型干涉实验比较"
    page3.insert_text(fitz.Point(margin_left, y), note, fontname="china-ss", fontsize=10)

    # ========== 第 4 页：混合（文本 + 插图区域）=========
    page4 = doc.new_page(width=595, height=842)
    y = 72

    page4.insert_text(
        fitz.Point(margin_left, y),
        "3.4 等倾干涉与等厚干涉",
        fontname="china-s", fontsize=14,
    )
    y += 30

    mixed_text = (
        "薄膜干涉是日常生活中最常见的干涉现象之一。"
        "如图所示，一束光在薄膜上下表面反射后相遇产生干涉。"
        "根据薄膜厚度是否均匀，可分为等倾干涉和等厚干涉。"
    )
    for line in _wrap_text(mixed_text, fontsize=11, max_width=450):
        page4.insert_text(fitz.Point(margin_left, y), line, fontname="china-ss", fontsize=11)
        y += 20

    # 插入一个占位图片矩形
    img_rect = fitz.Rect(72, y + 15, 400, y + 200)
    page4.draw_rect(img_rect, color=(0.3, 0.3, 0.3), width=1)
    page4.insert_text(
        fitz.Point(180, y + 100),
        "[图 3-4  薄膜干涉示意图]",
        fontname="china-ss", fontsize=10,
    )
    y += 230

    conclusion = (
        "等倾干涉：薄膜厚度均匀，干涉条纹定域于无穷远。"
        "等厚干涉：薄膜厚度变化，干涉条纹定域于薄膜表面附近。"
    )
    for line in _wrap_text(conclusion, fontsize=11, max_width=450):
        page4.insert_text(fitz.Point(margin_left, y), line, fontname="china-ss", fontsize=11)
        y += 20

    # ========== 保存 ==========
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(OUTPUT))
    doc.close()
    print(f"✅ 样例 PDF 已生成: {OUTPUT}")
    print(f"   共 4 页：文本页 / 公式页 / 表格页 / 混合页")


def _wrap_text(text: str, fontsize: int, max_width: float) -> list[str]:
    """
    简单中文文本换行。
    中文字符大约 = fontsize * 1.0 宽度。
    """
    chars_per_line = max(int(max_width / fontsize), 20)
    lines = []
    for para in text.split("\n"):
        para = para.strip()
        while len(para) > chars_per_line:
            # 找到最近的标点或空格断行
            break_at = chars_per_line
            for sep in "，、。；：,.;: ":
                pos = para.rfind(sep, 0, chars_per_line)
                if pos > chars_per_line // 2:
                    break_at = pos + 1
                    break
            lines.append(para[:break_at])
            para = para[break_at:].lstrip("，、。；：,.;: ")
        if para:
            lines.append(para)
    return lines


if __name__ == "__main__":
    create_sample_pdf()
