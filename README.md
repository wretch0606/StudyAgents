# StudyAgents

面向单门课程的多 Agent 可信知识问答与专项复习系统。

> 当前目标：由 5 人小组在 7 天内完成可答辩演示的 MVP。系统需要跑通“资料导入 → 可信问答 → 严格拒答 → 专项训练 → 评分讲解 → 错题沉淀”闭环。

本周的功能取舍、验收用例和质量门槛以 [docs/MVP_SCOPE.md](docs/MVP_SCOPE.md) 为准。
课程样例来源见 [docs/COURSE_MATERIALS.md](docs/COURSE_MATERIALS.md)，集成门结果统一记录在 [docs/ACCEPTANCE_TRACKER.md](docs/ACCEPTANCE_TRACKER.md)。
第 6 天使用的 50 条评测基线、双人标注流程和指标工具见 [tests/evaluation/README.md](tests/evaluation/README.md)。

## 快速启动（Docker Compose）

### 准备

```bash
# 1. 克隆仓库
git clone <repo-url> && cd StudyAgents

# 2. 创建环境文件
cp .env.example .env
# 编辑 .env，至少修改 SESSION_SECRET 和 INIT_DEFAULT_PASSWORD

# 3. 确保 Docker 已安装并运行
docker --version
docker compose version
```

### 启动全部服务

```bash
# 构建镜像并启动（首次约 3-5 分钟）
docker compose up -d --build

# 查看服务状态
docker compose ps
```

四个服务：`studyagents-postgres`、`studyagents-api`、`studyagents-worker`、`studyagents-frontend`

### 数据库迁移

```bash
# 在隔离环境中执行迁移
docker compose exec api alembic upgrade head

# 验证迁移版本
docker compose exec api alembic current
```

### 初始化账号

```bash
# 创建 1 admin + 4 member 共 5 个预置账号
docker compose exec -e INIT_DEFAULT_PASSWORD=<your-password> api python scripts/init_users.py
```

默认账号：`admin`（管理员）、`member_a`、`member_b`、`member_c`、`member_d`（普通成员）

### 健康检查

```bash
# API 健康检查
curl http://localhost:8080/api/health/live

# Worker 健康检查
docker compose exec worker python -m apps.worker.main --check

# 前端
curl http://localhost:3000
```

### 访问

| 服务 | 地址 |
|------|------|
| 前端 | http://localhost:3000 |
| API | http://localhost:8080 |
| API 文档（开发模式） | http://localhost:8080/api/docs |

### 查看日志

```bash
# 所有服务
docker compose logs -f

# 单个服务
docker compose logs -f api
docker compose logs -f worker
docker compose logs -f frontend
```

### 停止

```bash
# 停止所有服务，保留数据卷
docker compose down

# 停止并删除数据卷（重置数据库和文件）
docker compose down -v
```

### 故障定位

```bash
# 数据库连接
docker compose exec postgres pg_isready -U studyagents -d studyagents

# API 日志中搜索错误
docker compose logs api | grep -i error

# 查看迁移历史
docker compose exec api alembic history

# 进入容器调试
docker compose exec api bash
docker compose exec worker bash
```

### 实时模式 vs 演示缓存

- **实时模式**（默认）：设置 `.env` 中 `DEMO_CACHE_MODE=`（空）或直接不设置
- **演示缓存模式**：设置 `.env` 中 `DEMO_CACHE_MODE=1`。前端和 API 会明确标记 `demo/cached`，不伪装为实时结果

## 技术栈

- 前端：Vue 3、TypeScript、Vite、Pinia、Vue Router、Element Plus、KaTeX
- 后端：FastAPI、Pydantic、SQLAlchemy、Alembic
- Agent：LangGraph
- 数据：PostgreSQL、pgvector、全文检索
- 文档处理：PyMuPDF、PaddleOCR
- 测试：pytest、Vitest、Playwright
- 部署：Docker Compose

## 团队分工

| 成员 | 角色 | 主责 | 交付 |
| --- | --- | --- | --- |
| A | 组长 / 产品测试 | 范围、任务板、评测、验收、答辩 | 需求清单、50 条评测、指标报告、答辩材料 |
| B | 知识库 / RAG | PDF/OCR、切块、索引、混合检索、引用 | 导入检索模块、`SourceRef`、Recall@5 报告 |
| C | Agent / 提示词 | 状态图、契约、拒答、出题、评分 | Agent 流程、Schema、提示词和契约测试 |
| D | 后端 / 数据部署 | 认证、API、数据库、Worker、SSE、部署 | API、迁移、任务恢复、Compose、备份 |
| E | 前端 / E2E | 页面、SSE、公式、响应式、端到端测试 | 完整前端、E2E、演示界面 |

成员姓名和 GitHub 用户名由 A 在 [docs/TEAM.md](docs/TEAM.md) 中维护。

## 一周里程碑

| 日期 | 目标 | 集成验收 |
| --- | --- | --- |
| 第 1 天 | 定范围、定接口、搭骨架 | 公共契约合并，前后端、数据库和 Worker 可启动 |
| 第 2 天 | 资料可导入、可检索 | 返回带页码的 `SourceRef` |
| 第 3 天 | 可信问答闭环 | 可回答问题带引用，资料外问题正确拒答 |
| 第 4 天 | 训练评分闭环 | 至少完成 3 题并返回评分、讲解和错题 |
| 第 5 天 | 全链路集成 | 登录到错题主链路跑通 |
| 第 6 天 | 评测与集中修复 | 核心指标达标或形成明确缺陷清单 |
| 第 7 天 | 冻结与答辩 | 完整演示连续成功 3 次 |

## 仓库结构

```text
.
├─ apps/
│  ├─ frontend/          # E：Vue 前端
│  ├─ api/               # D：FastAPI 服务
│  └─ worker/            # B/D：导入与索引任务
├─ packages/
│  ├─ agents/            # C：LangGraph、提示词与 Agent 契约
│  └─ retrieval/         # B：解析、切块、索引与混合检索
├─ contracts/            # B/C/D/E 共用 JSON Schema 与 Mock
├─ docs/                 # A 维护的需求、评测、ADR 和答辩资料
├─ tests/
│  └─ evaluation/        # A 组织的 50 条评测集与指标脚本
└─ .github/              # Issue、PR 与协作模板
```

## 协作规则

1. 第 1 天先合并 `contracts/` 中的公共契约和 Mock，再并行开发。
2. 每项任务使用独立分支，通过 Pull Request 合并到 `main`。
3. 每个 PR 至少由一名非主责成员评审。
4. Schema 变更必须同步更新契约、示例响应和前端 Mock。
5. 当天可运行代码必须推送到远程仓库，禁止关键模块只留在个人电脑。
6. 密钥、真实课程资料、个人数据、标准答案和私有评分点不得提交。

## 完成标准

- 正常流程和错误流程都能运行。
- 单元测试、契约测试或对应自动化测试已通过。
- 权限和私有字段隔离已验证；提交答案前不返回答案或评分点。
- 错误响应和日志包含 `trace_id`。
- 接口契约、Mock 和必要说明同步更新。
- 至少一名非主责成员完成评审，并在集成环境运行成功。

## 安全与许可

- 复制 `.env.example` 创建本地环境文件；不要提交真实密钥。
- 课程资料与评测数据应遵守版权和隐私要求。
- 本仓库当前未指定开源许可证；公开可见不等于授权复制、修改或再分发。
