"""
OCR 引擎 — 抽象接口 + 多实现

设计原则：
  - OCRInterface 定义统一契约，调用方不依赖具体实现
  - PaddleOCRAdapter 封装 PP-StructureV3 全管线
  - MockOCRAdapter 用于测试和降级
  - 通过 config.EMBEDDING_PROVIDER 或独立环境变量切换实现
"""

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from apps.worker.schemas import BlockType, LayoutBlock

logger = logging.getLogger(__name__)


# ============================================================
# OCR 结果类型
# ============================================================

@dataclass
class OCRResult:
    """OCR 完整结果"""
    text: str                                  # 全部纯文本（阅读顺序）
    blocks: list[LayoutBlock] = field(default_factory=list)
    page_confidence: float = 0.0
    language: str = "zh"


# ============================================================
# 抽象接口
# ============================================================

class OCRInterface(ABC):
    """OCR 引擎抽象基类"""

    @abstractmethod
    def recognize(self, image_path: str, page_no: int = 0) -> OCRResult:
        """
        对单张页图执行 OCR。

        Args:
            image_path: 图片文件路径
            page_no: 页码（用于日志）

        Returns:
            OCRResult 包含文本、版面块和置信度
        """
        ...

    @abstractmethod
    def recognize_bytes(self, image_bytes: bytes, page_no: int = 0) -> OCRResult:
        """对内存中的图片字节执行 OCR"""
        ...

    @property
    @abstractmethod
    def name(self) -> str:
        """引擎名称"""
        ...


# ============================================================
# PaddleOCR 适配器
# ============================================================

class PaddleOCRAdapter(OCRInterface):
    """
    PP-StructureV3 全管线适配器。

    通过 subprocess 调用 PaddleOCR CLI，或使用 Python API。
    首版使用 Python API 方式，在 Windows CPU 上运行。

    管线：文本检测 → 文本识别 → 版面分析 → 公式识别 → 表格识别
    """

    def __init__(
        self,
        lang: str = "ch",
        use_gpu: bool = False,
        use_angle_cls: bool = True,
        det_db_thresh: float = 0.3,
        rec_threshold: float = 0.5,
    ):
        self.lang = lang
        self.use_gpu = use_gpu
        self.use_angle_cls = use_angle_cls
        self.det_db_thresh = det_db_thresh
        self.rec_threshold = rec_threshold
        self._ocr = None  # 延迟初始化

    @property
    def name(self) -> str:
        return "paddleocr_v3"

    def _ensure_initialized(self):
        """延迟初始化 PaddleOCR 实例（避免导入时加载模型）"""
        if self._ocr is not None:
            return
        try:
            from paddleocr import PPStructureV3

            self._ocr = PPStructureV3(
                lang=self.lang,
                use_gpu=self.use_gpu,
                use_angle_cls=self.use_angle_cls,
                det_db_thresh=self.det_db_thresh,
            )
            logger.info("PP-StructureV3 初始化完成")
        except ImportError:
            logger.warning("PaddleOCR 未安装，使用降级文本提取模式")
            self._ocr = None
        except Exception as e:
            logger.error(f"PP-StructureV3 初始化失败: {e}")
            self._ocr = None

    # ---- 主入口 ----

    def recognize(self, image_path: str, page_no: int = 0) -> OCRResult:
        """对页图文件执行 OCR"""
        self._ensure_initialized()

        if self._ocr is None:
            return self._fallback_result(page_no, f"[PaddleOCR 不可用: {image_path}]")

        try:
            result = self._ocr(image_path)
            return self._parse_pp_result(result, page_no)
        except Exception as e:
            logger.error(f"OCR 失败 page={page_no}: {e}")
            return self._fallback_result(page_no, f"[OCR 错误: {e}]")

    def recognize_bytes(self, image_bytes: bytes, page_no: int = 0) -> OCRResult:
        """对内存中的图片执行 OCR"""
        self._ensure_initialized()

        if self._ocr is None:
            return self._fallback_result(page_no, "[PaddleOCR 不可用]")

        try:
            import tempfile
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
                f.write(image_bytes)
                tmp_path = f.name

            result = self._ocr(tmp_path)

            # 清理临时文件
            Path(tmp_path).unlink(missing_ok=True)

            return self._parse_pp_result(result, page_no)
        except Exception as e:
            logger.error(f"OCR bytes 失败 page={page_no}: {e}")
            return self._fallback_result(page_no, f"[OCR 错误: {e}]")

    # ---- 结果解析 ----

    def _parse_pp_result(self, raw: list, page_no: int) -> OCRResult:
        """
        将 PP-StructureV3 原始输出转为 OCRResult。

        输入格式（PP-StructureV3 返回的列表）：
        [
          {"type": "text",   "text": "...",    "bbox": [...], "confidence": 0.95},
          {"type": "formula","text": "$E=mc^2$","bbox": [...], "confidence": 0.82},
          {"type": "table",  "text": "<table>...","bbox": [...], "confidence": 0.90},
          ...
        ]
        """
        blocks: list[LayoutBlock] = []
        full_text_parts: list[str] = []
        confidences: list[float] = []

        for i, item in enumerate(raw):
            block_type_str = item.get("type", "text")
            content = item.get("text", "") or ""
            bbox_list = item.get("bbox", [0, 0, 0, 0])
            conf = float(item.get("confidence", 0.5))

            # bbox 统一为 4 元组
            if len(bbox_list) == 4:
                bbox = tuple(bbox_list)  # type: ignore[arg-type]
            elif len(bbox_list) == 8:
                # 四点坐标 → 取外接矩形
                xs = bbox_list[0::2]
                ys = bbox_list[1::2]
                bbox = (min(xs), min(ys), max(xs), max(ys))
            else:
                bbox = (0.0, 0.0, 0.0, 0.0)

            # 映射块类型
            block_type = self._map_block_type(block_type_str)

            # 表格 Markdown 提取（PP-StructureV3 可能返回 HTML）
            if block_type == BlockType.TABLE:
                content = self._extract_table_markdown(item)

            blocks.append(LayoutBlock(
                bbox=bbox,
                block_type=block_type,
                content=content,
                confidence=conf,
                reading_order=i,
            ))

            if content.strip():
                full_text_parts.append(content.strip())
            confidences.append(conf)

        text = "\n".join(full_text_parts)
        page_conf = sum(confidences) / len(confidences) if confidences else 0.0

        return OCRResult(
            text=text,
            blocks=blocks,
            page_confidence=round(page_conf, 4),
        )

    @staticmethod
    def _map_block_type(raw_type: str) -> BlockType:
        """映射原始类型到 BlockType"""
        mapping = {
            "text": BlockType.TEXT,
            "paragraph": BlockType.TEXT,
            "title": BlockType.TEXT,
            "formula": BlockType.FORMULA,
            "table": BlockType.TABLE,
            "figure": BlockType.FIGURE,
            "image": BlockType.FIGURE,
        }
        return mapping.get(raw_type, BlockType.TEXT)

    @staticmethod
    def _extract_table_markdown(item: dict) -> str:
        """
        从 PP-StructureV3 表格输出提取 Markdown。

        PP-StructureV3 表格结果可能包含：
        - "text": HTML <table>...</table>
        - "cell_boxes": 单元格坐标
        - "html": HTML 字符串

        这里做简化转换：HTML table → Markdown。
        """
        raw_text = item.get("text", "") or ""
        html = item.get("html", "") or ""

        source = html or raw_text

        if not source:
            return ""

        # 尝试 HTML → Markdown
        try:
            import re

            # 去掉 HTML 标签，保留结构
            md = source
            md = re.sub(r"</tr>", "\n", md, flags=re.IGNORECASE)
            md = re.sub(r"</td>", " | ", md, flags=re.IGNORECASE)
            md = re.sub(r"</th>", " | ", md, flags=re.IGNORECASE)
            md = re.sub(r"<[^>]+>", "", md)
            md = re.sub(r"\n\s*\n", "\n", md)
            md = re.sub(r"\| \|", "|", md)
            return md.strip()
        except Exception:
            return source

    # ---- 降级 ----

    @staticmethod
    def _fallback_result(page_no: int, message: str) -> OCRResult:
        """OCR 不可用时的降级结果"""
        return OCRResult(
            text=message,
            blocks=[
                LayoutBlock(
                    bbox=(0, 0, 0, 0),
                    block_type=BlockType.TEXT,
                    content=message,
                    confidence=0.0,
                    reading_order=0,
                )
            ],
            page_confidence=0.0,
        )


# ============================================================
# Mock OCR（测试用）
# ============================================================

class MockOCRAdapter(OCRInterface):
    """Mock OCR，用于单元测试和 CI"""

    def __init__(self, fixed_text: str = ""):
        self.fixed_text = fixed_text

    @property
    def name(self) -> str:
        return "mock"

    def recognize(self, image_path: str, page_no: int = 0) -> OCRResult:
        text = self.fixed_text or f"[Mock OCR page {page_no}: {image_path}]"
        return OCRResult(
            text=text,
            blocks=[
                LayoutBlock(
                    bbox=(0, 0, 100, 20),
                    block_type=BlockType.TEXT,
                    content=text,
                    confidence=0.99,
                    reading_order=0,
                )
            ],
            page_confidence=0.99,
        )

    def recognize_bytes(self, image_bytes: bytes, page_no: int = 0) -> OCRResult:
        return self.recognize("bytes_input", page_no)


# ============================================================
# 工厂函数
# ============================================================

def create_ocr_engine(provider: str = "paddle") -> OCRInterface:
    """
    根据配置创建 OCR 引擎。

    provider 可选：
      - "paddle"   → PaddleOCRAdapter（生产）
      - "mock"     → MockOCRAdapter（测试/降级）
      - "none"     → MockOCRAdapter(fixed_text="")
    """
    if provider == "mock":
        return MockOCRAdapter()
    if provider == "none":
        return MockOCRAdapter(fixed_text="[OCR disabled]")
    return PaddleOCRAdapter()
