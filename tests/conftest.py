"""tests/ 目录共享配置 — 使 from worker.xxx 可导入 apps/worker/xxx。"""
from __future__ import annotations

import sys
from pathlib import Path

# 把 apps/ 加入 sys.path，使 main 分支的 from worker.xxx 能定位到 apps/worker/xxx
_apps_dir = Path(__file__).resolve().parent.parent / "apps"
if str(_apps_dir) not in sys.path:
    sys.path.insert(0, str(_apps_dir))
