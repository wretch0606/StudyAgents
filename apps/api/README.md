# API

成员 D 负责的 FastAPI 服务。

首周范围：认证权限、资料/导入任务、会话、Agent Run、训练、错题、SSE 和统一错误。

## 本地开发环境

```powershell
# 1. 安装 Python 3.12（如未安装）
uv python install 3.12

# 2. 同步依赖（在仓库根目录执行）
uv sync

# 3. 确认版本
uv run python --version

# 4. 运行测试
uv run pytest

# 5. 代码检查
uv run ruff check .
```

## 启动开发服务器

```powershell
uv run uvicorn apps.api.main:app --reload --host 0.0.0.0 --port 8000
```

## Docker Compose 启动（全栈）

```powershell
# 启动全部服务（postgres + api）
docker compose up -d

# 查看运行状态
docker compose ps

# 查看日志
docker compose logs -f api

# 验证健康检查
curl http://localhost:8080/api/health/live
curl http://localhost:8080/api/health/ready

# 停止服务
docker compose down

# 停止并删除数据卷（谨慎）
docker compose down -v
```

## 验证 pgvector

```powershell
# 进入 postgres 容器
docker compose exec postgres psql -U studyagents -d studyagents

# 在 psql 中执行
SELECT extname, extversion FROM pg_extension WHERE extname = 'vector';
```
