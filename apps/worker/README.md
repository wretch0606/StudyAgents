# Worker

异步任务处理进程。

- **基础设施与生命周期**：D 成员负责
- **文档解析、切片、Embedding、知识库构建及 RAG 逻辑**：B 成员负责

## 职责边界

| D 负责 | B 负责 |
| --- | --- |
| Worker 进程入口与生命周期 | 资料解析（PyMuPDF/PaddleOCR） |
| 配置加载（共享 `apps.api.config`） | 文档切片与结构化 |
| 数据库连接与 Session 管理 | Embedding 生成 |
| 任务处理器注册表（`HandlerRegistry`） | 向量写入与索引 |
| 健康检查 | RAG 检索算法 |
| 结构化日志与异常处理 | Agent 和模型业务逻辑 |
| 优雅停止 | |

## 启动与停止

```powershell
# 启动 Worker（轮询模式）
uv run python -m apps.worker.main

# 健康检查（一次性，退出码 0=ready，非 0=degraded）
uv run python -m apps.worker.main --check

# 停止：Ctrl+C 或发送 SIGINT/SIGTERM
```

## 环境变量

Worker 与 API 共享同一套环境变量（`.env` / `.env.example`）。

| 变量 | 必填 | 说明 |
|------|------|------|
| `DATABASE_URL` | 是 | PostgreSQL 连接（`postgresql+psycopg://` 或 `postgresql+asyncpg://`） |
| `APP_ENV` | 否 | `development`（默认） |
| 其他 | 否 | 与 API 配置一致，见 `apps/api/config.py` |

## 健康检查

Worker 提供两种健康状态：

| 命令 | 用途 |
|------|------|
| `uv run python -m apps.worker.main --check` | 检查配置 + 数据库连通性，打印报告后退出 |
| Worker 运行日志 | 持续输出 `starting → ready → degraded → stopping` 状态 |

健康检查项目：
- **config**：DATABASE_URL 是否已配置
- **database**：能否连接 PostgreSQL 并执行 `SELECT 1`

## B Pipeline 接入方式

B 成员通过 `HandlerRegistry` 注册任务处理器：

```python
from apps.worker.pipeline import HandlerRegistry, PipelineHandler, WorkerTask, WorkerResult

class IngestionHandler:
    async def handle(self, task: WorkerTask) -> WorkerResult:
        # B 的文档处理逻辑
        return WorkerResult(task_id=task.task_id, success=True)

registry = HandlerRegistry()
registry.register("ingestion", IngestionHandler())
```

### 注册位置

在 `apps/worker/main.py` 的 `_run_main()` 函数中，`HandlerRegistry()` 创建后调用 `registry.register(...)`。

### 未注册处理器时的行为

- `Worker.execute_task()` 抛出 `HandlerNotConfiguredError`
- Worker 日志输出 `WARNING: no handlers registered — worker will reject all tasks`
- **绝不会**伪造成功或返回虚假知识库数据

## 当前阶段边界

本阶段（Issue #8）仅建立 Worker 基础骨架。

**已实现：**
- 进程入口与生命周期
- 配置加载与数据库连接
- 处理器注册表与适配接口
- 健康检查（`--check`）
- 优雅停止
- Worker 测试（13 个）

**属于后续 Issue #11，本阶段不实现：**
- 完整任务表与持久化任务系统
- 任务租约、指数退避重试
- 断点恢复、死信队列
- 调度平台（Celery/Redis/RabbitMQ/Kafka）

## 测试

```powershell
uv run pytest apps/worker/tests/ -v
```
