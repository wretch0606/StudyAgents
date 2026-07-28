"""
DOCX 解析器（骨架）

一周冲刺版优先 PDF，DOCX 仅保留骨架。
"""

from apps.worker.schemas import PageResult


class DOCXParser:
    """Word 文档解析器"""

    def parse(self, file_path: str) -> list[PageResult]:
        """python-docx 提取：标题、段落、表格"""
        # TODO Day 5（有余力时实现）
        return []
