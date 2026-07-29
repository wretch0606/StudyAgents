"""pytest configuration for worker tests."""
from __future__ import annotations

import os

# 必须在任何 apps.api 导入前设置，确保 Settings 以 app_env="test" 初始化
os.environ["APP_ENV"] = "test"
