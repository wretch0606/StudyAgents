# StudyAgents API — 多阶段构建
# 使用 uv 管理依赖，最终镜像仅包含运行时必要文件
# builder 和 runtime 使用相同 WORKDIR /app 以保持 venv shebang 有效

FROM python:3.12-slim AS builder

# 安装 uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1

# 先复制依赖声明，利用 Docker 层缓存
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# 复制源码
COPY apps/ ./apps/
COPY agents/ ./agents/
COPY c/ ./c/
COPY contracts/ ./contracts/

# 安装项目自身
RUN uv sync --frozen --no-dev


FROM python:3.12-slim AS runtime

WORKDIR /app

# 仅复制虚拟环境
COPY --from=builder /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH"

# 复制应用代码
COPY apps/ ./apps/
COPY agents/ ./agents/
COPY c/ ./c/
COPY contracts/ ./contracts/

EXPOSE 8000

CMD ["uvicorn", "apps.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
