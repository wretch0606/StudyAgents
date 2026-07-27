"""管理接口 — Issue #8 最小只读管理端点。

用于权限验收：普通成员访问返回 403，管理员返回 200。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from apps.api.dependencies.auth import require_admin

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/health")
async def admin_health(
    user_id: str = Depends(require_admin),
) -> dict[str, str]:
    """管理接口健康检查 — 仅管理员可访问。"""
    return {"status": "ok", "message": "admin access granted"}
