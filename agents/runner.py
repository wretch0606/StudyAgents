"""
CAgentRunner — 实现 D 的 AgentRunnerProtocol，连接 LangGraph 状态图。

用法（D 在 main.py 中调用）:
    from agents.runner import CAgentRunner
    from apps.api.services.agent_runner import init_agent_runner
    init_agent_runner(runner=CAgentRunner(), model_gateway=..., event_sink=...)

D 的 AgentRunnerService._execute_run() 会调用:
    result = await self._runner.run(
        run_id=..., trace_id=..., user_input=..., mode=...,
        model_gateway=..., event_sink=...,
    )

Day 6 增强:
  - 记录提示词版本和模型版本（manifest）
  - 追踪主要失败类型
  - 输出 RunManifest 供评测框架使用
"""
from __future__ import annotations

import datetime
from typing import Any

from .graph import build_qa_graph
from .graph_practice import build_practice_graph
from .schemas import PROMPT_VERSIONS
from .state import AgentState


class CAgentRunner:
    """C 的 Agent 状态图适配器——实现 D 的 AgentRunnerProtocol。

    D 注入 model_gateway 和 event_sink，C 负责图编译和执行。

    Day 6: 每次 run() 结束后可通过 runner.last_manifest 获取运行快照。
    """

    def __init__(self):
        self.last_manifest: dict | None = None
        self.failure_type_counts: dict[str, int] = {}

    async def run(
        self,
        *,
        run_id: str,
        trace_id: str,
        user_input: str,
        mode: str,
        model_gateway,     # ModelGateway (D 注入)
        event_sink,        # AgentEventSinkProtocol (D 注入)
        last_successful_node: str | None = None,
        checkpoint_ref: str | None = None,
    ) -> Any:  # -> AgentRunResult
        """执行一次 Agent Run。"""
        from apps.api.services.agent_runner import AgentRunResult
        from apps.api.services.checkpointer import get_checkpointer

        # 1. 构建初始状态
        initial_state: AgentState = {
            "run_id": run_id,
            "trace_id": trace_id,
            "thread_id": run_id,  # QA 模式以 run_id 为 thread_id
            "user_id": "system",  # D 侧负责权限校验
            "mode": mode,
            "user_input": user_input,
            "filters": {},
            "model_calls": 0,
            "node_hops": 0,
            "retry_count": 0,
        }

        # 2. 选择状态图
        if mode == "qa":
            builder = build_qa_graph()
        elif mode == "practice":
            builder = build_practice_graph()
        else:
            return AgentRunResult(
                status="failed",
                error_code="INVALID_MODE",
                error_message=f"不支持的模式: {mode}",
                retryable=False,
            )

        # 3. 编译并执行
        graph = builder.compile(checkpointer=get_checkpointer())
        result = await graph.ainvoke(
            initial_state,
            config={
                "configurable": {
                    "thread_id": run_id,
                    "model": model_gateway,
                    "event_sink": event_sink,
                    "retriever": None,  # B 的 HybridRetriever 由 D 注入或从 config 获取
                    "db_session": getattr(event_sink, "_last_db_session", None),
                }
            },
        )

        # 4. 记录 manifest（Day 6）
        error = result.get("error")
        failure_type = error.get("code") if error else None
        self._record_manifest(
            run_id=run_id,
            trace_id=trace_id,
            mode=mode,
            model_calls=result.get("model_calls", 0),
            node_hops=result.get("node_hops", 0),
            failure_type=failure_type,
        )

        # 5. 映射结果
        if error:
            return AgentRunResult(
                status="failed",
                error_code=error.get("code", "AGENT_ERROR"),
                error_message=error.get("message", "Agent 执行失败"),
                retryable=error.get("retryable", False),
                last_successful_node=result.get("last_successful_node"),
                model_calls=result.get("model_calls", 0),
                node_hops=result.get("node_hops", 0),
            )

        return AgentRunResult(
            status="succeeded",
            public_response=result.get("public_response", ""),
            last_successful_node="run.completed",
            model_calls=result.get("model_calls", 0),
            node_hops=result.get("node_hops", 0),
        )

    # ── Day 6: Manifest 与失败类型 ──

    def _record_manifest(
        self,
        run_id: str,
        trace_id: str,
        mode: str,
        model_calls: int,
        node_hops: int,
        failure_type: str | None,
    ) -> None:
        """记录每次运行的快照（prompt 版本、模型版本、失败类型）。"""
        manifest = {
            "run_id": run_id,
            "trace_id": trace_id,
            "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "mode": mode,
            "prompt_versions": dict(PROMPT_VERSIONS),
            "model_calls": model_calls,
            "node_hops": node_hops,
            "failure_type": failure_type,
        }
        self.last_manifest = manifest

        # 追踪失败类型
        if failure_type:
            self.failure_type_counts[failure_type] = (
                self.failure_type_counts.get(failure_type, 0) + 1
            )

    def get_evaluation_manifest(self, code_commit: str = "", material_commit: str = "") -> dict:
        """
        生成供评测框架使用的运行快照。

        格式与 tests/evaluation/run-manifest.schema.json 对齐。
        """
        import hashlib
        import json

        manifest = {
            "run_id": self.last_manifest.get("run_id", "") if self.last_manifest else "",
            "created_at": self.last_manifest.get("created_at", "") if self.last_manifest else "",
            "code_commit": code_commit,
            "material_commit": material_commit,
            "material_manifest_sha256": "",
            "dataset_sha256": "",
            "policy_sha256": "",
            "models": {"default": "see-d-model-gateway"},
            "prompt_versions": self.last_manifest.get("prompt_versions", {}) if self.last_manifest else {},
            "retrieval_parameters": {},
            "environment": "integration",
        }
        return manifest

    def get_failure_summary(self) -> dict[str, int]:
        """返回主要失败类型及频次。"""
        return dict(self.failure_type_counts)
