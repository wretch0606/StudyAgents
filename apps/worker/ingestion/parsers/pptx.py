"""
PPTX 解析器（骨架）

一周冲刺版优先 PDF，PPTX 仅保留骨架。
"""

from worker.schemas import PageResult


class PPTXParser:
    """PowerPoint 解析器"""

    def parse(self, file_path: str) -> list[PageResult]:
        """python-pptx：每张幻灯片→一个页面单元"""
        # TODO Day 5（有余力时实现）
        return []
