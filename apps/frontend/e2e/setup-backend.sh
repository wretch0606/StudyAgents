#!/usr/bin/env bash
# ============================================================
# StudyAgents — E2E 测试后端初始化脚本
#
# 在 Playwright webServer 启动阶段执行：
#   1. 启动 postgres 并等待就绪
#   2. 运行 Alembic 数据库迁移
#   3. 创建预置测试账号（member_a 等）
#   4. 启动 api + worker 服务
#
# 用法（由 playwright.config.ts webServer 自动调用）：
#   bash apps/frontend/e2e/setup-backend.sh
#
# 环境变量：
#   INIT_DEFAULT_PASSWORD  — 测试账号默认密码（默认 change-me）
#   COMPOSE_FILE           — Docker Compose 文件路径（默认 compose.yml）
# ============================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MONOREPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
COMPOSE_FILE="${COMPOSE_FILE:-$MONOREPO_ROOT/compose.yml}"
COMPOSE_CMD="docker compose -f $COMPOSE_FILE"

echo "========================================"
echo " E2E Backend Setup"
echo "   MONOREPO_ROOT: $MONOREPO_ROOT"
echo "   COMPOSE_FILE:  $COMPOSE_FILE"
echo "========================================"

# ---- 1. 启动 postgres ----
echo ""
echo "[1/4] Starting postgres..."
$COMPOSE_CMD up -d postgres

# ---- 2. 等待 postgres 就绪 ----
echo "[2/4] Waiting for postgres to be ready..."
for i in $(seq 1 30); do
  if $COMPOSE_CMD exec -T postgres pg_isready -U studyagents -d studyagents 2>/dev/null; then
    echo "       postgres is ready."
    break
  fi
  if [ "$i" -eq 30 ]; then
    echo "ERROR: postgres did not become ready in 30 attempts."
    $COMPOSE_CMD logs postgres
    exit 1
  fi
  sleep 1
done

# ---- 3. 运行数据库迁移 ----
echo "[3/4] Running Alembic migrations..."
$COMPOSE_CMD run --rm \
  --no-deps \
  -e DATABASE_URL="postgresql+psycopg://studyagents:change-me@postgres:5432/studyagents" \
  api \
  python -m alembic upgrade head

# ---- 4. 创建测试账号 ----
echo "[4/4] Creating preset test users..."
INIT_PW="${INIT_DEFAULT_PASSWORD:-change-me}"
$COMPOSE_CMD run --rm \
  --no-deps \
  -e DATABASE_URL="postgresql+psycopg://studyagents:change-me@postgres:5432/studyagents" \
  -e INIT_DEFAULT_PASSWORD="$INIT_PW" \
  api \
  python scripts/init_users.py

echo ""
echo "========================================"
echo " E2E Backend Setup Complete"
echo "   Test accounts created:"
echo "     admin     / $INIT_PW  (role: admin)"
echo "     member_a  / $INIT_PW  (role: member)"
echo "     member_b  / $INIT_PW  (role: member)"
echo "     member_c  / $INIT_PW  (role: member)"
echo "     member_d  / $INIT_PW  (role: member)"
echo "========================================"
