"""管理员资料与任务 REST API — Issue #11-4。

端点：
  POST   /api/documents              — 上传文件（multipart）
  GET    /api/documents              — 资料列表
  GET    /api/documents/{id}         — 资料详情
  DELETE /api/documents/{id}         — 软删除
  GET    /api/ingestion-jobs/{id}    — 任务详情
  POST   /api/ingestion-jobs/{id}/retry — 重试失败任务
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Query, Request, UploadFile
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.db.models.ingestion_job import IngestionJob
from apps.api.db.session import get_session as get_db_session
from apps.api.dependencies.auth import get_current_user, require_csrf
from apps.api.schemas.error import ApiError
from apps.api.services.file_storage import (
    FileValidationError,
    check_duplicate,
    save_file,
    validate_extension,
    validate_magic,
    validate_mime,
)

router = APIRouter(prefix="/documents", tags=["documents"])
job_router = APIRouter(prefix="/ingestion-jobs", tags=["ingestion-jobs"])


# ---- 辅助 ----

def _require_admin(user_id: str, session: AsyncSession) -> str:
    """验证管理员权限（简化版 require_admin，支持直接调用）。"""
    # 此处在路由中通过 Depends(get_current_user) 已有 user_id
    # 实际 admin 检查：需要查询用户角色
    return user_id  # 实际 admin 验证由路由 Depends(get_current_user) + 下游处理


async def _get_doc_or_404(session: AsyncSession, doc_id: str) -> dict:
    from sqlalchemy import select

    from apps.api.db.models.document import Document

    result = await session.execute(
        select(Document).where(Document.id == doc_id)
    )
    doc = result.scalar_one_or_none()
    if doc is None or doc.status == "deleted":
        raise ApiError("RESOURCE_NOT_FOUND", "文档不存在。", status_code=404, retryable=False)
    return doc


def _doc_to_dict(doc) -> dict:
    return {
        "id": str(doc.id), "name": doc.name, "sha256": doc.sha256,
        "mime": doc.mime, "status": doc.status, "version": doc.version,
        "page_count": doc.page_count, "year": doc.year,
        "metadata": doc.metadata_,
        "created_at": doc.created_at.isoformat() if doc.created_at else "",
        "updated_at": doc.updated_at.isoformat() if doc.updated_at else "",
    }


def _job_to_dict(job) -> dict:
    return {
        "id": str(job.id), "document_id": str(job.document_id),
        "stage": job.stage, "status": job.status,
        "progress": job.progress,
        "error_code": job.error_code, "error_summary": job.error_summary,
        "attempts": job.attempts, "retry_count": job.retry_count,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
        "created_at": job.created_at.isoformat() if job.created_at else "",
        "updated_at": job.updated_at.isoformat() if job.updated_at else "",
    }


# ============================================================
# POST /api/documents — 上传
# ============================================================

@router.post("")
async def upload_document(
    file: UploadFile,
    request: Request,
    user_id: str = Depends(get_current_user),
    _csrf: None = Depends(require_csrf),
    session: AsyncSession = Depends(get_db_session),
):
    # 管理员权限检查
    from apps.api.repositories.auth import find_user_by_id
    user = await find_user_by_id(session, user_id)
    if user is None or user.role != "admin":
        raise ApiError("AUTH_FORBIDDEN", "仅管理员可上传文件。", status_code=403, retryable=False)

    # 1. 校验扩展名
    filename = file.filename or "unnamed"
    try:
        ext = validate_extension(filename)
    except FileValidationError as e:
        raise ApiError(e.code, str(e), status_code=415, retryable=False)

    # 2. 校验 MIME
    content_type = file.content_type or ""
    try:
        validate_mime(content_type, ext)
    except FileValidationError as e:
        raise ApiError(e.code, str(e), status_code=415, retryable=False)

    # 3. 流式读取 + 保存
    try:
        file.file.seek(0)
        header = file.file.read(16)
        file.file.seek(0)
        validate_magic(header, ext)
        file.file.seek(0)
        file_path, sha256, size = save_file(file.file, filename=filename)
    except FileValidationError as e:
        raise ApiError(e.code, str(e), status_code=413, retryable=False)

    # 4. 去重
    existing = await check_duplicate(sha256, db_session=session)
    if existing:
        return JSONResponse(
            status_code=200,
            content={"state": "duplicate", "duplicate": existing},
        )

    # 5. 创建文档记录
    from apps.api.db.models.document import Document
    now = datetime.now(UTC).replace(tzinfo=None)
    doc = Document(
        name=filename, sha256=sha256, mime=content_type, status="pending",
        version=1, file_path=file_path, created_at=now, updated_at=now,
    )
    session.add(doc)
    await session.flush()

    # 6. 创建导入任务并入队
    job = IngestionJob(
        document_id=doc.id, stage="validate", status="pending",
        progress=0.0, attempts=0, created_at=now, updated_at=now,
    )
    session.add(job)
    await session.flush()
    await session.commit()

    return JSONResponse(
        status_code=201,
        content={
            "state": "accepted",
            "document": _doc_to_dict(doc),
            "ingestion_job": _job_to_dict(job),
        },
    )


# ============================================================
# GET /api/documents — 列表
# ============================================================

@router.get("")
async def list_documents(
    user_id: str = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: str | None = None,
):
    from apps.api.repositories.auth import find_user_by_id
    user = await find_user_by_id(session, user_id)
    if user is None or user.role != "admin":
        raise ApiError("AUTH_FORBIDDEN", "仅管理员可查看。", status_code=403, retryable=False)

    from sqlalchemy import func, select

    from apps.api.db.models.document import Document

    stmt = select(Document).where(Document.status != "deleted")
    if status:
        stmt = stmt.where(Document.status == status)
    count_stmt = select(func.count()).select_from(Document).where(Document.status != "deleted")
    if status:
        count_stmt = count_stmt.where(Document.status == status)

    total = (await session.execute(count_stmt)).scalar() or 0
    result = await session.execute(
        stmt.order_by(Document.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
    )
    docs = result.scalars().all()

    return {
        "items": [_doc_to_dict(d) for d in docs],
        "total": total, "page": page, "page_size": page_size,
        "total_pages": max(1, (total + page_size - 1) // page_size),
    }


# ============================================================
# GET /api/documents/{id} — 详情
# ============================================================

@router.get("/{doc_id}")
async def get_document(
    doc_id: str,
    user_id: str = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    from apps.api.repositories.auth import find_user_by_id
    user = await find_user_by_id(session, user_id)
    if user is None or user.role != "admin":
        raise ApiError("AUTH_FORBIDDEN", "仅管理员可查看。", status_code=403, retryable=False)

    doc = await _get_doc_or_404(session, doc_id)

    # 查询最近任务
    from sqlalchemy import select
    job_result = await session.execute(
        select(IngestionJob).where(
            IngestionJob.document_id == doc_id,
        ).order_by(IngestionJob.created_at.desc()).limit(1)
    )
    latest_job = job_result.scalar_one_or_none()

    return {
        "document": _doc_to_dict(doc),
        "latest_ingestion_job": _job_to_dict(latest_job) if latest_job else None,
    }


# ============================================================
# DELETE /api/documents/{id} — 软删除
# ============================================================

@router.delete("/{doc_id}")
async def delete_document(
    doc_id: str,
    request: Request,
    user_id: str = Depends(get_current_user),
    _csrf: None = Depends(require_csrf),
    session: AsyncSession = Depends(get_db_session),
):
    from apps.api.repositories.auth import find_user_by_id
    user = await find_user_by_id(session, user_id)
    if user is None or user.role != "admin":
        raise ApiError("AUTH_FORBIDDEN", "仅管理员可删除资料。", status_code=403, retryable=False)

    doc = await _get_doc_or_404(session, doc_id)
    doc.status = "deleted"
    doc.updated_at = datetime.now(UTC).replace(tzinfo=None)
    await session.flush()
    await session.commit()
    return JSONResponse(
        status_code=200,
        content={"document_id": str(doc.id), "accepted": True},
    )


# ============================================================
# GET /api/ingestion-jobs/{id} — 任务详情
# ============================================================

@job_router.get("/{job_id}")
async def get_ingestion_job(
    job_id: str,
    user_id: str = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    from apps.api.repositories.auth import find_user_by_id
    user = await find_user_by_id(session, user_id)
    if user is None or user.role != "admin":
        raise ApiError("AUTH_FORBIDDEN", "仅管理员可查看任务。", status_code=403, retryable=False)

    from sqlalchemy import select
    result = await session.execute(
        select(IngestionJob).where(IngestionJob.id == job_id)
    )
    job = result.scalar_one_or_none()
    if job is None:
        raise ApiError("RESOURCE_NOT_FOUND", "任务不存在。", status_code=404, retryable=False)
    return _job_to_dict(job)


# ============================================================
# POST /api/ingestion-jobs/{id}/retry — 重试
# ============================================================

@job_router.post("/{job_id}/retry")
async def retry_ingestion_job(
    job_id: str,
    request: Request,
    user_id: str = Depends(get_current_user),
    _csrf: None = Depends(require_csrf),
    session: AsyncSession = Depends(get_db_session),
):
    from apps.api.repositories.auth import find_user_by_id
    user = await find_user_by_id(session, user_id)
    if user is None or user.role != "admin":
        raise ApiError("AUTH_FORBIDDEN", "仅管理员可重试任务。", status_code=403, retryable=False)

    from sqlalchemy import select
    result = await session.execute(
        select(IngestionJob).where(IngestionJob.id == job_id)
    )
    job = result.scalar_one_or_none()
    if job is None:
        raise ApiError("RESOURCE_NOT_FOUND", "任务不存在。", status_code=404, retryable=False)

    if job.status not in ("failed_retryable",):
        raise ApiError(
            "AGENT_LIMIT_EXCEEDED",
            f"任务状态为 {job.status}，仅 failed_retryable 可重试。",
            status_code=422, retryable=False,
        )

    if job.max_retries_reached:
        raise ApiError(
            "AGENT_LIMIT_EXCEEDED",
            "任务已达到最大重试次数。",
            status_code=422, retryable=False,
        )

    # 重置为 pending
    job.status = "pending"
    job.lease_until = None
    job.error_code = None
    job.error_summary = None
    job.updated_at = datetime.now(UTC).replace(tzinfo=None)
    await session.flush()
    await session.commit()

    return _job_to_dict(job)
