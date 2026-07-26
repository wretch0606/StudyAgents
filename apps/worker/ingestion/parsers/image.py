"""
图片解析器（骨架）

一周冲刺版优先 PDF，JPG/PNG 仅保留骨架。
"""

from worker.schemas import PageResult


class ImageParser:
    """单图解析器"""

    def parse(self, file_path: str) -> list[PageResult]:
        """直接 OCR，单图→单页"""
        # TODO Day 5（有余力时实现）
        return []
