"""
导入管线编排

将各阶段串联成完整流程：
  校验 → 解析 → OCR → 结构化 → 切块 → 向量化 → 索引 → 完成

每个阶段持久化进度，支持断点续跑。
"""

import hashlib
import logging
import uuid
from pathlib import Path
from typing import Any

from apps.worker.ingestion.chunker import Chunker
from apps.worker.ingestion.job_manager import JobManager
from apps.worker.ingestion.keyword_indexer import KeywordIndexer
from apps.worker.ingestion.parsers.ocr import OCRInterface, create_ocr_engine
from apps.worker.ingestion.parsers.pdf import PDFParser
from apps.worker.ingestion.structurer import PageStructurer
from apps.worker.ingestion.vectorizer import Vectorizer
from apps.worker.retrieval.retriever import HybridRetriever
from apps.worker.schemas import (
    Chunk,
    IngestionJob,
    IngestionStage,
    PageResult,
)

logger = logging.getLogger(__name__)


class IngestionPipeline:
    """导入管线，串联解析→结构化→切块→向量化→索引→完成"""

    def __init__(
        self,
        job_manager: JobManager,
        retriever: HybridRetriever | None = None,
        ocr_engine: OCRInterface | None = None,
        db_session: Any | None = None,
    ):
        self.job_mgr = job_manager
        self.retriever = retriever or HybridRetriever()
        self.ocr = ocr_engine or create_ocr_engine("none")
        self.parser = PDFParser(ocr_engine=self.ocr)
        self.structurer = PageStructurer()
        self.chunker = Chunker()
        self.vectorizer = Vectorizer()
        self.keyword_indexer = KeywordIndexer()
        self.db_session = db_session
        self._stash: dict[str, dict] = {}  # 生产环境应替换为数据库读写

    def _get(self, job_id: str, key: str):
        return self._stash.get(job_id, {}).get(key)

    def _set(self, job_id: str, key: str, val):
        self._stash.setdefault(job_id, {})[key] = val

    def _clear(self, job_id: str):
        self._stash.pop(job_id, None)

    # ---- 主入口 ----

    async def run(
        self,
        job: IngestionJob,
        source_path: str | Path | None = None,
    ):
        """执行当前导入阶段，并将真实源文件路径保留到后续阶段。"""
        if source_path is not None:
            self._set(job.job_id, "source_path", str(Path(source_path).resolve()))
        logger.info(f"[{job.job_id}] 开始导入，阶段: {job.stage.value}")
        try:
            dispatch = {
                IngestionStage.VALIDATING: self._do_extract,
                IngestionStage.EXTRACTING: self._do_extract,
                IngestionStage.OCR: self._do_ocr,
                IngestionStage.STRUCTURING: self._do_structure,
                IngestionStage.CHUNKING: self._do_chunk,
                IngestionStage.VECTORIZING: self._do_vectorize,
                IngestionStage.INDEXING: self._do_index,
                IngestionStage.COMPLETING: self._do_complete,
            }
            handler = dispatch.get(job.stage)
            if handler:
                await handler(job)
            else:
                logger.warning(f"[{job.job_id}] 未知阶段: {job.stage.value}")
        except Exception as e:
            logger.error(f"[{job.job_id}] {job.stage.value} 失败: {e}")
            retryable = not isinstance(e, ValueError | FileNotFoundError)
            await self.job_mgr.fail_job(job.job_id, str(e), retryable=retryable)
            raise

    async def run_to_completion(
        self,
        job: IngestionJob,
        source_path: str | Path,
    ) -> None:
        """从当前阶段连续运行到完成，防止阶段未推进时无限循环。"""
        for _ in range(8):
            previous_stage = job.stage
            await self.run(job, source_path=source_path)
            if previous_stage == IngestionStage.COMPLETING:
                return
            if job.stage == previous_stage:
                failure = getattr(self.job_mgr, "last_error", None)
                raise RuntimeError(failure or f"导入阶段未推进: {job.stage.value}")
        raise RuntimeError("导入管线超过最大阶段数")

    # ---- 各阶段 ----

    async def _do_extract(self, job: IngestionJob):
        await self.job_mgr.update_progress(job.job_id, IngestionStage.EXTRACTING, 5.0)

        source_path = self._get(job.job_id, "source_path")
        pdf_path = Path(source_path) if source_path else _find_sample_pdf()
        if not pdf_path.is_file():
            raise FileNotFoundError(f"导入源文件不存在: {pdf_path}")
        pages = self.parser.parse(str(pdf_path), job.document_id)
        self._set(job.job_id, "pages", pages)

        await self._persist_pages(job.document_id, pages)

        await self.job_mgr.update_progress(
            job.job_id,
            IngestionStage.OCR,
            progress=30.0,
        )
        job.stage = IngestionStage.OCR

    async def _persist_pages(
        self,
        document_id: str,
        pages: list[PageResult],
    ) -> None:
        """在生产数据库会话可用时幂等写入页面；纯单元测试不连接数据库。"""
        if self.db_session is None:
            return

        from sqlalchemy import delete as sa_delete

        from apps.api.db.models.document import Document
        from apps.api.db.models.document_page import DocumentPage

        await self.db_session.execute(
            sa_delete(DocumentPage).where(
                DocumentPage.document_id == document_id,
            )
        )
        for page in pages:
            self.db_session.add(
                DocumentPage(
                    id=str(uuid.uuid4()),
                    document_id=document_id,
                    page_no=page.page_no,
                    raw_text=page.text,
                    image_path=page.image_path,
                    char_count=len(page.text),
                    page_type="digital" if page.is_digital else "scanned",
                    layout_json=[
                        {
                            "type": block.block_type.value,
                            "content": block.content,
                            "confidence": block.confidence,
                            "bbox": list(block.bbox),
                        }
                        for block in page.layout
                    ]
                    if page.layout
                    else None,
                    confidence=page.confidence,
                )
            )

        document = await self.db_session.get(Document, document_id)
        if document is not None:
            document.page_count = len(pages)
            document.status = "extracting"
        await self.db_session.flush()

    async def _do_ocr(self, job: IngestionJob):
        pages: list[PageResult] = self._get(job.job_id, "pages") or []
        scanned = sum(1 for p in pages if not p.is_digital)
        await self.job_mgr.update_progress(
            job.job_id,
            IngestionStage.STRUCTURING,
            progress=40.0,
            error=f"OCR 阶段: 扫描页 {scanned}/{len(pages)}",
        )
        job.stage = IngestionStage.STRUCTURING

    async def _do_structure(self, job: IngestionJob):
        pages: list[PageResult] = self._get(job.job_id, "pages") or []
        if not pages:
            return await self.job_mgr.fail_job(job.job_id, "无页面", retryable=False)

        self.structurer.reset()
        structured = [self.structurer.structure(p) for p in pages]
        self._set(job.job_id, "structured", structured)

        secs = sum(len(p.sections) for p in structured)
        tabs = sum(len(p.tables) for p in structured)
        await self.job_mgr.update_progress(
            job.job_id,
            IngestionStage.CHUNKING,
            progress=55.0,
            error=f"结构化: {secs} 节, {tabs} 表格",
        )
        job.stage = IngestionStage.CHUNKING

    async def _do_chunk(self, job: IngestionJob):
        structured = self._get(job.job_id, "structured") or []
        if not structured:
            return await self.job_mgr.fail_job(job.job_id, "无结构化数据", retryable=False)

        chunks: list[Chunk] = self.chunker.chunk_document(job.document_id, structured)
        self._set(job.job_id, "chunks", chunks)

        await self._persist_chunks(job.document_id, chunks)

        await self.job_mgr.update_progress(
            job.job_id, IngestionStage.VECTORIZING, progress=70.0, error=f"切块: {len(chunks)} 块"
        )
        job.stage = IngestionStage.VECTORIZING

    async def _persist_chunks(
        self,
        document_id: str,
        chunks: list[Chunk],
    ) -> None:
        """在生产数据库会话可用时幂等写入知识块。"""
        if self.db_session is None:
            return

        from sqlalchemy import delete as sa_delete

        from apps.api.db.models.knowledge_chunk import KnowledgeChunk

        await self.db_session.execute(
            sa_delete(KnowledgeChunk).where(
                KnowledgeChunk.document_id == document_id,
            )
        )
        for chunk in chunks:
            visibility = (
                chunk.visibility.value
                if hasattr(chunk.visibility, "value")
                else str(chunk.visibility)
            )
            material_type = (
                chunk.material_type.value
                if hasattr(chunk.material_type, "value")
                else str(chunk.material_type)
            )
            content_version = getattr(chunk, "content_version", None)
            content_hash = (
                getattr(chunk, "content_hash", None)
                or hashlib.sha256(chunk.content.encode("utf-8")).hexdigest()
            )
            self.db_session.add(
                KnowledgeChunk(
                    id=chunk.chunk_id,
                    document_id=chunk.document_id,
                    page_from=chunk.page_from,
                    page_to=chunk.page_to,
                    question_no=getattr(chunk, "question_no", None),
                    section_path=(" > ".join(chunk.section_path) if chunk.section_path else None),
                    content=chunk.content,
                    private_content=getattr(chunk, "private_content", None),
                    content_hash=content_hash,
                    visibility=visibility,
                    material_type=material_type,
                    year=getattr(chunk, "year", None),
                    image_refs=getattr(chunk, "image_refs", None),
                    embedding_version=(
                        str(content_version) if content_version is not None else None
                    ),
                )
            )
        await self.db_session.flush()

    async def _do_vectorize(self, job: IngestionJob):
        chunks: list[Chunk] = self._get(job.job_id, "chunks") or []
        if not chunks:
            return await self.job_mgr.fail_job(job.job_id, "无切块", retryable=False)

        embeddings = await self.vectorizer.embed_chunks(chunks)
        self._set(job.job_id, "embeddings", embeddings)

        await self.job_mgr.update_progress(
            job.job_id,
            IngestionStage.INDEXING,
            progress=85.0,
        )
        job.stage = IngestionStage.INDEXING

    async def _do_index(self, job: IngestionJob):
        chunks: list[Chunk] = self._get(job.job_id, "chunks") or []
        embeddings: list[list[float]] = self._get(job.job_id, "embeddings") or []

        if not chunks or not embeddings:
            return await self.job_mgr.fail_job(job.job_id, "无索引数据", retryable=False)

        await self.retriever.index_chunks(chunks, embeddings)
        await self.keyword_indexer.index_chunks(chunks)
        await self.retriever.set_doc_names({job.document_id: f"文档-{job.document_id[:8]}"})

        await self.job_mgr.update_progress(
            job.job_id, IngestionStage.COMPLETING, progress=95.0, error=f"索引: {len(chunks)} 块"
        )
        job.stage = IngestionStage.COMPLETING

    async def _do_complete(self, job: IngestionJob):
        await self.job_mgr.complete_job(job.job_id)
        self._clear(job.job_id)
        logger.info(f"[{job.job_id}] 导入完成")


def _find_sample_pdf() -> Path:
    """查找样例 PDF"""
    _root = Path(__file__).resolve().parent.parent.parent.parent
    candidates = [
        Path("tests/fixtures/sample_lecture.pdf"),
        _root / "tests" / "fixtures" / "sample_lecture.pdf",
    ]
    for p in candidates:
        if p.exists():
            return p.resolve()
    raise FileNotFoundError("样例 PDF 不存在，请先运行 generate_sample_pdf.py")
