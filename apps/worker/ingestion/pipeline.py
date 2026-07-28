"""
导入管线编排

将各阶段串联成完整流程：
  校验 → 解析 → OCR → 结构化 → 切块 → 向量化 → 索引 → 完成

每个阶段持久化进度，支持断点续跑。
"""

import logging
from pathlib import Path
from typing import Optional

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
        retriever: Optional[HybridRetriever] = None,
        ocr_engine: Optional[OCRInterface] = None,
    ):
        self.job_mgr = job_manager
        self.retriever = retriever or HybridRetriever()
        self.ocr = ocr_engine or create_ocr_engine("none")
        self.parser = PDFParser(ocr_engine=self.ocr)
        self.structurer = PageStructurer()
        self.chunker = Chunker()
        self.vectorizer = Vectorizer()
        self.keyword_indexer = KeywordIndexer()
        self._stash: dict[str, dict] = {}  # 生产环境应替换为数据库读写

    def _get(self, job_id: str, key: str):
        return self._stash.get(job_id, {}).get(key)

    def _set(self, job_id: str, key: str, val):
        self._stash.setdefault(job_id, {})[key] = val

    def _clear(self, job_id: str):
        self._stash.pop(job_id, None)

    # ---- 主入口 ----

    async def run(self, job: IngestionJob):
        """执行完整导入管线"""
        logger.info(f"[{job.job_id}] 开始导入，阶段: {job.stage.value}")
        try:
            dispatch = {
                IngestionStage.VALIDATING:    self._do_extract,
                IngestionStage.EXTRACTING:    self._do_extract,
                IngestionStage.OCR:           self._do_ocr,
                IngestionStage.STRUCTURING:   self._do_structure,
                IngestionStage.CHUNKING:      self._do_chunk,
                IngestionStage.VECTORIZING:   self._do_vectorize,
                IngestionStage.INDEXING:      self._do_index,
                IngestionStage.COMPLETING:    self._do_complete,
            }
            handler = dispatch.get(job.stage)
            if handler:
                await handler(job)
            else:
                logger.warning(f"[{job.job_id}] 未知阶段: {job.stage.value}")
        except Exception as e:
            logger.error(f"[{job.job_id}] {job.stage.value} 失败: {e}")
            retryable = not isinstance(e, (ValueError, FileNotFoundError))
            await self.job_mgr.fail_job(job.job_id, str(e), retryable=retryable)
            raise

    # ---- 各阶段 ----

    async def _do_extract(self, job: IngestionJob):
        await self.job_mgr.update_progress(job.job_id, IngestionStage.EXTRACTING, 5.0)

        file_path = self._get(job.job_id, "file_path") or _find_sample_pdf()
        pages = self.parser.parse(str(file_path), job.document_id)
        self._set(job.job_id, "pages", pages)

        await self.job_mgr.update_progress(
            job.job_id, IngestionStage.OCR,
            progress=30.0,
        )
        job.stage = IngestionStage.OCR

    async def _do_ocr(self, job: IngestionJob):
        pages: list[PageResult] = self._get(job.job_id, "pages") or []
        scanned = sum(1 for p in pages if not p.is_digital)
        await self.job_mgr.update_progress(
            job.job_id, IngestionStage.STRUCTURING,
            progress=40.0,
            error=f"OCR 阶段: 扫描页 {scanned}/{len(pages)}"
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
            job.job_id, IngestionStage.CHUNKING,
            progress=55.0,
            error=f"结构化: {secs} 节, {tabs} 表格"
        )
        job.stage = IngestionStage.CHUNKING

    async def _do_chunk(self, job: IngestionJob):
        structured = self._get(job.job_id, "structured") or []
        if not structured:
            return await self.job_mgr.fail_job(job.job_id, "无结构化数据", retryable=False)

        chunks: list[Chunk] = self.chunker.chunk_document(job.document_id, structured)
        self._set(job.job_id, "chunks", chunks)

        await self.job_mgr.update_progress(
            job.job_id, IngestionStage.VECTORIZING,
            progress=70.0,
            error=f"切块: {len(chunks)} 块"
        )
        job.stage = IngestionStage.VECTORIZING

    async def _do_vectorize(self, job: IngestionJob):
        chunks: list[Chunk] = self._get(job.job_id, "chunks") or []
        if not chunks:
            return await self.job_mgr.fail_job(job.job_id, "无切块", retryable=False)

        embeddings = await self.vectorizer.embed_chunks(chunks)
        self._set(job.job_id, "embeddings", embeddings)

        await self.job_mgr.update_progress(
            job.job_id, IngestionStage.INDEXING,
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
            job.job_id, IngestionStage.COMPLETING,
            progress=95.0,
            error=f"索引: {len(chunks)} 块"
        )
        job.stage = IngestionStage.COMPLETING

    async def _do_complete(self, job: IngestionJob):
        await self.job_mgr.complete_job(job.job_id)
        self._clear(job.job_id)
        logger.info(f"[{job.job_id}] 导入完成")


def _find_sample_pdf() -> Path:
    """查找样例 PDF"""
    candidates = [
        Path("src/tests/fixtures/sample_lecture.pdf"),
        Path(__file__).resolve().parent.parent.parent / "tests" / "fixtures" / "sample_lecture.pdf",
    ]
    for p in candidates:
        if p.exists():
            return p.resolve()
    raise FileNotFoundError("样例 PDF 不存在，请先运行 generate_sample_pdf.py")


class IngestionHandler:
    """Worker handler — 将 IngestionPipeline 适配为 PipelineHandler 协议。

    从 WorkerTask.payload 中提取 document_id，查询文件路径，驱动入库管线。
    """

    async def handle(self, task):
        from apps.worker.pipeline import WorkerResult
        from sqlalchemy import select
        from sqlalchemy.ext.asyncio import AsyncSession

        document_id = task.payload.get("document_id", "") if task.payload else ""
        if not document_id:
            return WorkerResult(
                task_id=task.task_id, success=False,
                error_code="MISSING_DOCUMENT_ID",
                error_message="task payload 缺少 document_id",
            )

        # 从数据库查询文件路径
        from apps.api.db.session import _get_sessionmaker
        from apps.api.db.models.document import Document as ApiDocument
        from apps.worker.ingestion.job_manager import JobManager

        file_path = None
        async with _get_sessionmaker()() as db_session:
            result = await db_session.execute(
                select(ApiDocument).where(ApiDocument.id == document_id),
            )
            doc = result.scalar_one_or_none()
            if doc is not None and doc.file_path:
                file_path = doc.file_path

        if not file_path:
            return WorkerResult(
                task_id=task.task_id, success=False,
                error_code="MISSING_FILE_PATH",
                error_message=f"文档 {document_id} 没有持久化文件路径",
            )

        # 驱动入库管线（每个阶段使用独立 DB 会话）
        async with _get_sessionmaker()() as db_session:
            job_mgr = JobManager(db_session)
            pipeline = IngestionPipeline(job_manager=job_mgr)
            pipeline._set(task.task_id, "file_path", file_path)

            from apps.worker.schemas import IngestionJob as BIngestionJob, IngestionStage
            b_job = BIngestionJob(
                job_id=task.task_id, document_id=document_id,
                stage=IngestionStage.EXTRACTING,
            )
            await pipeline.run(b_job)

        return WorkerResult(task_id=task.task_id, success=True, output={})
