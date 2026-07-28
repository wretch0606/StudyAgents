"""D-01 最小环境测试 — 仅验证 Python 版本与基础依赖可导入。

不包含业务逻辑、数据库连接或 FastAPI 启动。
"""

import sys


def test_python_version() -> None:
    """验证 Python 版本在 3.12.x 范围内。"""
    major, minor, *_ = sys.version_info
    assert major == 3, f"期望 Python 3.x，当前为 {major}"
    assert minor == 12, f"期望 Python 3.12.x，当前为 3.{minor}"


def test_fastapi_import() -> None:
    """验证 FastAPI 基础依赖可导入。"""
    import fastapi  # noqa: F401


def test_pydantic_import() -> None:
    """验证 Pydantic 基础依赖可导入。"""
    import pydantic  # noqa: F401


def test_pydantic_settings_import() -> None:
    """验证 pydantic-settings 可导入。"""
    import pydantic_settings  # noqa: F401
