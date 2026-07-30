"""tests/ 目录共享配置 — 使 from worker.xxx 可导入 apps/worker/xxx。"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# 必须在任何 apps.api 导入前设置，确保 Settings 以 app_env="test" 初始化
os.environ["APP_ENV"] = "test"

_apps_dir = Path(__file__).resolve().parent.parent / "apps"
if str(_apps_dir) not in sys.path:
    sys.path.insert(0, str(_apps_dir))
