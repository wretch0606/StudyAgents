"""B–D 导入适配器 — D 只依赖稳定接口，不复制 B 的业务逻辑。

B 代码已合入 origin/main（PR #25）。
真实 import（B 使用 worker.xxx 前缀，D 侧对应 apps.worker.xxx）：

  from apps.worker.schemas import IngestionJob, IngestionStage, IngestionStatus
  from apps.worker.ingestion.job_manager import JobManager
  from apps.worker.ingestion.pipeline import IngestionPipeline

D 职责：文件接收、校验、去重、落盘、任务入队、REST API。
B 职责：解析、OCR、切块、向量化、索引、检索。
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from apps.worker.pipeline import WorkerResult, WorkerTask

# ---- 适配器协议 ----

class IngestionAdapter(Protocol):
    """D 侧依赖的导入适配器协议。Worker 通过此协议调用 B 的管线。"""

    async def run_pipeline(self, job) -> None:
        """执行完整导入管线。成功静默返回，失败 raise。"""
        ...

    async def create_job(self, document_id: str):
        """创建导入任务，返回 IngestionJob。"""
        ...

    async def claim_next(self):
        """获取下一个待处理任务（带租约），返回 IngestionJob | None。"""
        ...

    async def update_progress(
        self, job_id: str, stage, progress: float, error: str | None = None,
    ) -> None:
        """更新任务阶段和进度。"""
        ...

    async def complete_job(self, job_id: str) -> None:
        """标记任务成功。"""
        ...

    async def fail_job(self, job_id: str, error: str, retryable: bool = True) -> None:
        """标记任务失败。"""
        ...

    async def retry_job(self, job_id: str) -> bool:
        """重试失败任务。返回 True 表示可重试。"""
        ...

    async def recover_stale_jobs(self) -> int:
        """恢复过期任务。返回恢复数量。"""
        ...

    async def get_job(self, job_id: str):
        """查询单个任务，返回 IngestionJob | None。"""
        ...


class PipelineProgressRecorder:
    """让 B 管线复用 D 的任务生命周期，同时记录阶段内诊断信息。"""

    def __init__(self) -> None:
        self.events: list[dict] = []
        self.last_error: str | None = None

    async def update_progress(
        self, job_id: str, stage, progress: float, error: str | None = None,
    ) -> None:
        self.events.append({
            "job_id": job_id,
            "stage": stage.value if hasattr(stage, "value") else str(stage),
            "progress": progress,
            "detail": error,
        })

    async def complete_job(self, job_id: str) -> None:
        self.events.append({"job_id": job_id, "stage": "complete", "progress": 100.0})

    async def fail_job(self, job_id: str, error: str, retryable: bool = True) -> None:
        self.last_error = error
        self.events.append({
            "job_id": job_id,
            "stage": "failed",
            "progress": 0.0,
            "detail": error,
            "retryable": retryable,
        })


class IngestionPipelineHandler:
    """把 D 的 WorkerTask 转换为 B 的完整导入管线调用。"""

    def __init__(self, pipeline=None) -> None:
        if pipeline is None:
            from apps.worker.ingestion.pipeline import IngestionPipeline

            pipeline = IngestionPipeline(PipelineProgressRecorder())
        self.pipeline = pipeline

    async def handle(self, task: WorkerTask) -> WorkerResult:
        from apps.worker.schemas import IngestionJob, IngestionStage, IngestionStatus

        document_id = str(task.payload.get("document_id", ""))
        file_path = str(task.payload.get("file_path", ""))
        if not document_id:
            return WorkerResult(
                task_id=task.task_id,
                success=False,
                error_code="DOCUMENT_ID_MISSING",
                error_message="任务缺少 document_id",
                retryable=False,
            )
        if not file_path or not Path(file_path).is_file():
            return WorkerResult(
                task_id=task.task_id,
                success=False,
                error_code="SOURCE_FILE_NOT_FOUND",
                error_message=f"导入源文件不存在: {file_path or '<empty>'}",
                retryable=False,
            )
        if Path(file_path).suffix.lower() != ".pdf":
            return WorkerResult(
                task_id=task.task_id,
                success=False,
                error_code="PIPELINE_UNSUPPORTED_TYPE",
                error_message="当前一周冲刺版导入管线仅支持 PDF",
                retryable=False,
            )

        job = IngestionJob(
            job_id=task.task_id,
            document_id=document_id,
            stage=IngestionStage.VALIDATING,
            status=IngestionStatus.RUNNING,
        )
        try:
            await self.pipeline.run_to_completion(job, file_path)
        except (FileNotFoundError, ValueError) as exc:
            return WorkerResult(
                task_id=task.task_id,
                success=False,
                error_code=type(exc).__name__.upper(),
                error_message=str(exc),
                retryable=False,
            )
        except Exception as exc:
            return WorkerResult(
                task_id=task.task_id,
                success=False,
                error_code="INGESTION_FAILED",
                error_message=str(exc)[:500],
                retryable=True,
            )

        return WorkerResult(
            task_id=task.task_id,
            success=True,
            output={"document_id": document_id, "stage": "complete"},
        )


# ---- Fake 适配器（测试用） ----

class FakeIngestionAdapter:
    """测试用假适配器，不访问真实文件、模型和数据库。"""

    def __init__(self) -> None:
        self.jobs: dict[str, dict] = {}
        self._next_index = 0
        self._job_ids: list[str] = []

    def _job_dict(self, job_id: str, document_id: str, **overrides) -> dict:
        return {
            "job_id": job_id,
            "document_id": document_id,
            "stage": "validating",
            "status": "pending",
            "progress": 0.0,
            "attempts": 0,
            "max_attempts": 2,
            "error": None,
            **overrides,
        }

    async def run_pipeline(self, job) -> None:
        j = self.jobs.get(job.job_id, {})
        j["status"] = "succeeded"
        j["progress"] = 100.0

    async def create_job(self, document_id: str):
        from uuid import uuid4

        jid = str(uuid4())
        d = self._job_dict(jid, document_id)
        self.jobs[jid] = d
        self._job_ids.append(jid)
        # 返回类 dict 对象以模拟 B 的 dataclass
        return _FakeJob(d)

    async def claim_next(self):
        if self._next_index >= len(self._job_ids):
            return None
        jid = self._job_ids[self._next_index]
        self._next_index += 1
        d = self.jobs[jid]
        d["status"] = "running"
        return _FakeJob(d)

    async def update_progress(self, job_id: str, stage, progress: float, error: str | None = None):
        if job_id in self.jobs:
            self.jobs[job_id]["stage"] = stage.value if hasattr(stage, "value") else str(stage)
            self.jobs[job_id]["progress"] = progress
            if error:
                self.jobs[job_id]["error"] = error

    async def complete_job(self, job_id: str):
        if job_id in self.jobs:
            self.jobs[job_id]["status"] = "succeeded"
            self.jobs[job_id]["progress"] = 100.0

    async def fail_job(self, job_id: str, error: str, retryable: bool = True):
        if job_id in self.jobs:
            self.jobs[job_id]["status"] = "failed_retryable" if retryable else "failed_permanent"
            self.jobs[job_id]["error"] = error

    async def retry_job(self, job_id: str) -> bool:
        if job_id not in self.jobs:
            return False
        d = self.jobs[job_id]
        if d["attempts"] >= d["max_attempts"]:
            d["status"] = "failed_permanent"
            d["error"] = "超过最大重试次数"
            return False
        d["status"] = "pending"
        d["attempts"] += 1
        d["error"] = None
        return True

    async def recover_stale_jobs(self) -> int:
        count = 0
        for d in self.jobs.values():
            if d["status"] == "running":
                d["status"] = "pending"
                count += 1
        return count

    async def get_job(self, job_id: str):
        d = self.jobs.get(job_id)
        return _FakeJob(d) if d else None


class _FakeJob:
    """模拟 B 的 IngestionJob dataclass 的属性访问。"""

    def __init__(self, d: dict) -> None:
        self.__dict__.update(d)
