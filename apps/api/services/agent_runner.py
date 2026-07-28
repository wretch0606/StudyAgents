"""Agent Runner — C 调用适配、后台执行、重试与恢复。

提供：
- AgentRunnerProtocol: C 必须实现的接口
- AgentRunResult: 运行结果（成功/失败/重试信息）
- FakeAgentRunner: 测试用内存模拟实现
- AgentRunnerService: D 侧编排（事务、后台执行、重试、恢复）

C 的真实 import 路径与调用示例：
    from apps.api.services.agent_runner import AgentRunnerProtocol, AgentRunResult

    class MyAgentRunner:
        async def run(self, *, run_id, trace_id, user_input, mode,
                      model_gateway, event_sink,
                      last_successful_node=None, checkpoint_ref=None):
            # 1. 发射事件：event_sink.emit(run_id, draft, db_session)
            # 2. 调用模型：model_gateway.invoke_structured(...)
            # 3. 持久化检查点：更新 agent_runs 表的 checkpoint_ref
            # 4. 返回结果
            return AgentRunResult(status="succeeded", public_response="答案...")
"""

from __future__ import annotations

import asyncio
import logging
import uuid as _uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal, Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.db.models.run_state import FAILED, QUEUED, RUNNING
from apps.api.schemas.agent import AgentEventDraft

logger = logging.getLogger(__name__)


# ============================================================
# AgentRunResult
# ============================================================


@dataclass
class AgentRunResult:
    """Agent 运行结果 — C 的 runner.run() 返回值。"""

    status: Literal["succeeded", "failed"]
    public_response: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    retryable: bool = False
    last_successful_node: str | None = None
    checkpoint_ref: str | None = None
    model_calls: int = 0
    node_hops: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    total_elapsed_ms: int = 0


# ============================================================
# AgentRunnerProtocol
# ============================================================


class AgentRunnerProtocol(Protocol):
    """C 的 Agent 状态图必须实现此接口。

    D 向 C 注入已配置的 ModelGateway 和 AgentEventSink 实例。
    C 负责：状态图执行、事件发射、检查点管理。
    D 负责：事务边界、属主隔离、重复运行防护、消息持久化。
    """

    async def run(
        self,
        *,
        run_id: str,
        trace_id: str,
        user_input: str,
        mode: str,
        model_gateway,  # ModelGateway
        event_sink,     # AgentEventSinkProtocol
        last_successful_node: str | None = None,
        checkpoint_ref: str | None = None,
    ) -> AgentRunResult:
        """执行一次 Agent Run。

        Args:
            run_id: AgentRun.id
            trace_id: 本次运行的 trace_id（唯一，已由 D 生成）
            user_input: 用户输入文本
            mode: "qa" | "practice"
            model_gateway: ModelGateway 实例（已注入）
            event_sink: AgentEventSink 实例（已注入）
            last_successful_node: 恢复时上次成功节点名
            checkpoint_ref: 恢复时检查点引用

        Returns:
            AgentRunResult — D 根据结果决定成功/失败/恢复路径
        """
        ...


class _SessionBoundEventSink:
    """将后台运行使用的数据库会话安全绑定到事件接收器。"""

    def __init__(self, sink, db_session: AsyncSession) -> None:
        self._sink = sink
        self._last_db_session = db_session

    async def emit(self, *, run_id: str, event: AgentEventDraft, db_session=None):
        return await self._sink.emit(
            run_id=run_id,
            event=event,
            db_session=self._last_db_session,
        )


# ============================================================
# FakeAgentRunner — 测试用内存模拟
# ============================================================


class FakeAgentRunner:
    """模拟 C 的 Agent 状态图行为，用于 D 侧测试。

    支持场景：
    - success: 正常问答，发射完整事件序列，返回答案
    - waiting: 需要用户输入（训练模式）
    - failure: 模拟失败并设置错误码
    - crash: 无事件直接返回（模拟崩溃，用于恢复测试）
    """

    def __init__(
        self,
        *,
        scenario: str = "success",
        answer: str = "这是模拟答案。",
        error_code: str = "MODEL_TIMEOUT",
        error_message: str = "模型调用超时",
        retryable: bool = True,
        delay_ms: int = 10,
    ) -> None:
        self._scenario = scenario
        self._answer = answer
        self._error_code = error_code
        self._error_message = error_message
        self._retryable = retryable
        self._delay_ms = delay_ms

    async def run(
        self,
        *,
        run_id: str,
        trace_id: str,
        user_input: str,
        mode: str,
        model_gateway,  # noqa: ARG002
        event_sink,     # AgentEventSinkProtocol
        last_successful_node: str | None = None,  # noqa: ARG002
        checkpoint_ref: str | None = None,  # noqa: ARG002
    ) -> AgentRunResult:
        """模拟执行，按场景发射事件并返回结果。"""
        if self._delay_ms:
            await asyncio.sleep(self._delay_ms / 1000.0)

        start = datetime.now(UTC)

        if self._scenario == "crash":
            # Simulate crash: no events, return failed result
            elapsed = int((datetime.now(UTC) - start).total_seconds() * 1000)
            return AgentRunResult(
                status="failed",
                error_code="WORKER_CRASH",
                error_message="Worker crashed mid-execution",
                retryable=True,
                total_elapsed_ms=elapsed,
            )

        db_session = getattr(event_sink, "_last_db_session", None)
        if db_session is None:
            # event_sink.emit() needs db_session — pass through
            pass

        # Emit standard event sequence
        events = [
            ("coordinator", "run.started", "running", f"Run started: {user_input[:50]}"),
            ("knowledge", "agent.started", "running", "Knowledge agent started"),
            ("knowledge", "agent.summary", "running", "检索完成，找到 3 条相关证据"),
        ]

        for agent, event_type, status, summary in events:
            draft = AgentEventDraft(
                agent=agent,
                event_type=event_type,  # type: ignore[arg-type]
                status=status,
                summary=summary,
            )
            await event_sink.emit(run_id=run_id, event=draft, db_session=db_session)  # type: ignore[arg-type]

        if self._scenario == "waiting":
            draft = AgentEventDraft(
                agent="coordinator",
                event_type="run.waiting_user",  # type: ignore[arg-type]
                status="running",
                summary="等待用户输入",
            )
            await event_sink.emit(run_id=run_id, event=draft, db_session=db_session)  # type: ignore[arg-type]
            return AgentRunResult(
                status="succeeded",
                public_response=None,
                last_successful_node="waiting_user",
                total_elapsed_ms=int(
                    (datetime.now(UTC) - start).total_seconds() * 1000,
                ),
            )

        if self._scenario == "failure":
            draft = AgentEventDraft(
                agent="coordinator",
                event_type="run.failed",  # type: ignore[arg-type]
                status="running",
                summary=f"Run failed: {self._error_message}",
            )
            await event_sink.emit(run_id=run_id, event=draft, db_session=db_session)  # type: ignore[arg-type]
            return AgentRunResult(
                status="failed",
                error_code=self._error_code,
                error_message=self._error_message,
                retryable=self._retryable,
                last_successful_node="agent.summary",
                total_elapsed_ms=int(
                    (datetime.now(UTC) - start).total_seconds() * 1000,
                ),
            )

        # Success scenario
        events_tail = [
            ("knowledge", "agent.completed", "running", "Knowledge agent completed"),
            ("coordinator", "run.completed", "running", "Run completed successfully"),
        ]
        for agent, event_type, status, summary in events_tail:
            draft = AgentEventDraft(
                agent=agent,
                event_type=event_type,  # type: ignore[arg-type]
                status=status,
                summary=summary,
            )
            await event_sink.emit(run_id=run_id, event=draft, db_session=db_session)  # type: ignore[arg-type]

        return AgentRunResult(
            status="succeeded",
            public_response=self._answer,
            last_successful_node="run.completed",
            model_calls=2,
            node_hops=4,
            input_tokens=500,
            output_tokens=200,
            total_elapsed_ms=int(
                (datetime.now(UTC) - start).total_seconds() * 1000,
            ),
        )


# ============================================================
# AgentRunnerService — D 侧编排
# ============================================================


class AgentRunnerService:
    """Agent Run 编排服务。

    职责：
    - 在事务中创建用户消息、AgentRun 和 run.started 事件
    - 启动后台 asyncio.Task 执行 Agent
    - 管理重试（状态校验、幂等键、属主隔离）
    - 管理运行中任务注册表，防止并发重复运行
    - 恢复崩溃后残留的 running 状态任务
    """

    def __init__(
        self,
        *,
        runner: AgentRunnerProtocol,
        model_gateway,  # ModelGateway
        event_sink,     # AgentEventSinkProtocol
    ) -> None:
        self._runner = runner
        self._gateway = model_gateway
        self._event_sink = event_sink
        self._running: dict[str, asyncio.Task[None]] = {}  # run_id → task

    # ---- Public API ----

    async def start_qa(
        self,
        *,
        session: AsyncSession,
        session_id: str,
        user_id: str,
        user_input: str,
        mode: str = "qa",
        thread_id: str | None = None,
    ) -> dict:
        """发起一次问答。

        在单个事务中：
        1. 插入用户消息
        2. 创建 AgentRun（status=queued）
        3. 发射 run.started 事件
        4. 提交事务
        5. 返回 {run_id, thread_id} 给调用方

        事务提交后启动后台执行。
        """
        from apps.api.db.models.agent_run import AgentRun as AgentRunModel
        from apps.api.repositories import chat as chat_repo

        tid = thread_id or str(_uuid.uuid4())
        rid = str(_uuid.uuid4())
        trace = f"trace-{_uuid.uuid4().hex[:16]}"

        # Step 1: 创建 AgentRun（必须先于 message，因 message.run_id FK）
        run = AgentRunModel(
            id=rid,
            thread_id=tid,
            user_id=user_id,
            mode=mode,
            trace_id=trace,
        )
        session.add(run)

        # Step 2: 插入用户消息
        await chat_repo.insert_message(
            session,
            session_id=session_id,
            user_id=user_id,
            role="user",
            content=user_input,
            run_id=rid,
        )

        # Step 3: 发射 run.started 事件
        draft = AgentEventDraft(
            agent="coordinator",
            event_type="run.started",  # type: ignore[arg-type]
            status="running",
            summary=f"Run started: {user_input[:50]}",
        )
        seq = 0
        from apps.api.db.models.agent_event import AgentEvent as AgentEventModel

        db_event = AgentEventModel(
            run_id=rid,
            sequence_no=seq,
            agent=draft.agent,
            event_type=draft.event_type,
            status=draft.status,
            summary=draft.summary,
            source_refs=draft.source_refs,
            duration_ms=draft.duration_ms,
        )
        session.add(db_event)

        # Step 4: 提交事务（后台任务需要独立 session 能读到 run）
        await session.commit()

        # Step 5: 启动后台执行
        task = asyncio.create_task(
            self._execute_run(
                run_id=rid,
                user_id=user_id,
                session_id=session_id,
                trace_id=trace,
                user_input=user_input,
                mode=mode,
            ),
        )
        self._running[rid] = task

        return {"run_id": rid, "thread_id": tid, "trace_id": trace}

    async def retry_run(
        self,
        *,
        run_id: str,
        user_id: str,
        session: AsyncSession,
    ) -> dict:
        """重试失败的 Agent Run。

        校验：
        - 属主隔离（user_id 必须匹配）
        - 状态必须在 {failed, cancelled}
        - retryable 必须为 True
        - 不在当前运行中（幂等键）
        """
        from apps.api.repositories import agent_run as run_repo

        run = await run_repo.get_run(session, run_id, user_id=user_id)
        if run is None:
            raise AgentRunnerError(
                code="RESOURCE_NOT_FOUND",
                message="Run 不存在。",
                retryable=False,
                status_code=404,
            )

        if run.status not in {FAILED, "cancelled"}:
            raise AgentRunnerError(
                code="AGENT_LIMIT_EXCEEDED",
                message=f"Run 状态为 {run.status}，不可重试。仅 failed/cancelled 状态可重试。",
                retryable=False,
                status_code=422,
            )

        if not run.retryable:
            raise AgentRunnerError(
                code="AGENT_LIMIT_EXCEEDED",
                message="此 Run 标记为不可重试。",
                retryable=False,
                status_code=422,
            )

        if run_id in self._running:
            raise AgentRunnerError(
                code="AGENT_LIMIT_EXCEEDED",
                message="此 Run 正在执行中，请等待完成后再重试。",
                retryable=True,
                status_code=409,
            )

        # 转换状态：failed → queued
        from apps.api.repositories.chat import transition_run_status

        await transition_run_status(
            session, run_id, QUEUED, user_id=user_id,
        )

        # 重新启动后台执行
        task = asyncio.create_task(
            self._execute_run(
                run_id=run_id,
                user_id=user_id,
                session_id=None,
                trace_id=run.trace_id or f"trace-{_uuid.uuid4().hex[:16]}",
                user_input="[retry]",
                mode=run.mode,
            ),
        )
        self._running[run_id] = task

        return {
            "run_id": run_id,
            "status": QUEUED,
            "event_url": f"/api/agent-runs/{run_id}/events",
        }

    async def recover_stale_runs(self, session: AsyncSession) -> int:
        """恢复崩溃后残留的 running 状态任务，并重新调度执行。

        1. 扫描 agent_runs 中 status='running' 的行
        2. 将它们重置为 queued（保留 last_successful_node/checkpoint_ref）
        3. 对每个恢复的 run 创建后台任务，传递恢复参数
        """
        from sqlalchemy import select

        from apps.api.db.models.agent_run import AgentRun as AgentRunModel

        # Step 1: 查找所有 stale running runs
        result = await session.execute(
            select(AgentRunModel).where(AgentRunModel.status == RUNNING),
        )
        stale_runs = list(result.scalars().all())

        if not stale_runs:
            return 0

        now = datetime.now(UTC).replace(tzinfo=None)
        recovered_ids = [r.id for r in stale_runs]

        # Step 2: 批量更新为 queued
        from sqlalchemy import update

        await session.execute(
            update(AgentRunModel)
            .where(AgentRunModel.id.in_(recovered_ids))
            .values(
                status=QUEUED,
                error_code="WORKER_RECOVERED",
                error="Worker 重启后自动恢复",
                updated_at=now,
            ),
        )
        await session.commit()

        # Step 3: 对每个恢复的 run 创建后台任务
        for run in stale_runs:
            task = asyncio.create_task(
                self._execute_run(
                    run_id=str(run.id),
                    user_id=str(run.user_id),
                    session_id=None,
                    trace_id=run.trace_id or f"trace-{_uuid.uuid4().hex[:16]}",
                    user_input="[recovered]",
                    mode=run.mode,
                    last_successful_node=run.last_successful_node,
                    checkpoint_ref=run.checkpoint_ref,
                ),
            )
            self._running[str(run.id)] = task

        return len(stale_runs)

    # ---- Internal ----

    async def _execute_run(
        self,
        *,
        run_id: str,
        user_id: str,
        session_id: str | None,
        trace_id: str,
        user_input: str,
        mode: str,
        last_successful_node: str | None = None,
        checkpoint_ref: str | None = None,
    ) -> None:
        """后台执行单个 Agent Run（asyncio.Task 入口）。"""
        from apps.api.db.session import _get_sessionmaker

        try:
            async with _get_sessionmaker()() as session:
                # 转换 queued → running
                from apps.api.repositories.chat import transition_run_status

                await transition_run_status(
                    session, run_id, RUNNING, user_id=user_id,
                    started_at=datetime.now(UTC).replace(tzinfo=None),
                )

                # 调用 C 的 runner（传递恢复参数）
                result = await self._runner.run(
                    run_id=run_id,
                    trace_id=trace_id,
                    user_input=user_input,
                    mode=mode,
                    model_gateway=self._gateway,
                    event_sink=_SessionBoundEventSink(self._event_sink, session),
                    last_successful_node=last_successful_node,
                    checkpoint_ref=checkpoint_ref,
                )

                if result.status == "succeeded":
                    await self._on_success(
                        session, run_id, user_id, session_id, result,
                    )
                else:
                    await self._on_failure(session, run_id, user_id, result)

        except Exception as exc:
            logger.exception("Agent run %s failed with exception", run_id)
            try:
                async with _get_sessionmaker()() as session:
                    await self._on_exception(session, run_id, user_id, exc)
            except Exception:
                logger.exception(
                    "Failed to persist failure for run %s", run_id,
                )
        finally:
            self._running.pop(run_id, None)

    async def _on_success(
        self,
        session: AsyncSession,
        run_id: str,
        user_id: str,
        session_id: str | None,
        result: AgentRunResult,
    ) -> None:
        """处理成功完成：写 assistant 消息 + 更新 run。"""
        from apps.api.repositories import agent_run as run_repo
        from apps.api.repositories.chat import (
            get_assistant_message,
            insert_message,
        )

        # 幂等写入 assistant 消息（只在 session_id 可用时）
        if session_id is not None:
            existing = await get_assistant_message(
                session, run_id, user_id=user_id,
            )
            if existing is None and result.public_response:
                await insert_message(
                    session,
                    session_id=session_id,
                    user_id=user_id,
                    role="assistant",
                    content=result.public_response,
                    run_id=run_id,
                )

        # 更新 Run 状态
        await run_repo.update_run_status(
            session, run_id, "completed", user_id=user_id,
            completed_at=datetime.now(UTC).replace(tzinfo=None),
            public_response=result.public_response,
            last_successful_node=result.last_successful_node,
            checkpoint_ref=result.checkpoint_ref,
            model_calls=result.model_calls,
            node_hops=result.node_hops,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
        )
        await session.commit()

        # SSE 通知
        from apps.api.services.sse_manager import sse_manager
        sse_manager.mark_completed(run_id)

    async def _on_failure(
        self,
        session: AsyncSession,
        run_id: str,
        user_id: str,
        result: AgentRunResult,
    ) -> None:
        """处理运行失败：记录错误 + 更新状态。"""
        from apps.api.repositories import agent_run as run_repo

        await run_repo.update_run_status(
            session, run_id, FAILED, user_id=user_id,
            error_code=result.error_code,
            error=result.error_message,
            retryable=result.retryable,
            last_successful_node=result.last_successful_node,
            checkpoint_ref=result.checkpoint_ref,
            completed_at=datetime.now(UTC).replace(tzinfo=None),
        )
        await session.commit()

        # SSE 通知 — 失败终止
        from apps.api.services.sse_manager import sse_manager
        sse_manager.mark_completed(run_id, event_type="run.failed")

    async def _on_exception(
        self,
        session: AsyncSession,
        run_id: str,
        user_id: str,
        exc: Exception,
    ) -> None:
        """处理未预期异常：统一映射为错误码。"""
        error_code = type(exc).__name__
        is_retryable = _is_retryable_exception(exc)

        from apps.api.repositories import agent_run as run_repo

        await run_repo.update_run_status(
            session, run_id, FAILED, user_id=user_id,
            error_code=error_code,
            error=str(exc)[:1000],
            retryable=is_retryable,
            completed_at=datetime.now(UTC).replace(tzinfo=None),
        )
        await session.commit()

        # SSE 通知 — 异常终止
        from apps.api.services.sse_manager import sse_manager
        sse_manager.mark_completed(run_id, event_type="run.failed")


# ============================================================
# Error helpers
# ============================================================


class AgentRunnerError(Exception):
    """Agent Runner 统一错误 — 映射为 ApiError 返回给客户端。"""

    def __init__(
        self,
        *,
        code: str,
        message: str,
        retryable: bool,
        status_code: int = 500,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable
        self.status_code = status_code


def _is_retryable_exception(exc: Exception) -> bool:
    """判断异常是否可重试。"""
    name = type(exc).__name__
    msg = str(exc).lower()
    permanent = {"ValueError", "TypeError", "AttributeError", "KeyError"}
    if name in permanent:
        return False
    if "validation" in msg or "invalid" in msg:
        return False
    return True


def _map_exception_to_error(exc: Exception, trace_id: str) -> dict:
    """将异常映射为统一错误格式。"""
    return {
        "code": type(exc).__name__,
        "message": str(exc)[:500],
        "retryable": _is_retryable_exception(exc),
        "trace_id": trace_id,
    }


# ============================================================
# 模块级单例 — 供路由和其他服务使用
# ============================================================

# 默认使用 FakeAgentRunner（测试/开发环境）
# 生产环境替换为 C 的真实 AgentRunner 实现
agent_runner_service: AgentRunnerService | None = None


def init_agent_runner(
    *,
    runner: AgentRunnerProtocol | None = None,
    model_gateway=None,  # ModelGateway
    event_sink=None,     # AgentEventSinkProtocol
) -> AgentRunnerService:
    """初始化 AgentRunnerService 单例。

    在应用启动时调用（如 main.py 的 lifespan 中）。
    如果未提供 runner，默认使用 FakeAgentRunner。
    """
    global agent_runner_service
    from apps.api.services.agent_event_sink import agent_event_sink as default_sink
    from apps.api.services.model_gateway import FakeAdapter

    agent_runner_service = AgentRunnerService(
        runner=runner or FakeAgentRunner(),
        model_gateway=model_gateway or FakeAdapter(),
        event_sink=event_sink or default_sink,
    )
    return agent_runner_service
