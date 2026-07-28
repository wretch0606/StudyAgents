# Contracts — 跨模块 JSON Schema 契约

> 维护人：成员 C
> 版本：V1.0
> 日期：2026-07-26

## 谁看什么

| 你负责的模块 | 重点看这几个文件 | 你要确认什么 |
|-------------|-----------------|-------------|
| **B**（知识库/RAG） | `source-ref.schema.json` | SourceRef 字段是否与 `c/schemas.py` 一致？excerpt 300 字、question_no 可空、page_image_url 格式对吗？ |
| **D**（后端/部署） | `agent-state.schema.json`、`error.schema.json`、`agent-event.schema.json` | AgentState 公私字段能否在 API 响应中剥离？17 个错误码能否映射？SSE 事件格式能否生成？ |
| **E**（前端） | `public-question.schema.json`、`agent-event.schema.json`、`mock/*.json` | PublicQuestion 结构能否渲染？AgentEvent 抽屉能消费吗？Mock 数据足够开发吗？ |

## 文件说明

### Schema 文件

| 文件 | 方向 | 用途 |
|------|------|------|
| `source-ref.schema.json` | B → C | 检索返回的可引用证据，含文档名、页码、题号、摘录、页图 URL |
| `agent-event.schema.json` | C → D → E (SSE) | Agent 步骤事件，前端抽屉展示。8 种事件类型，5 种状态 |
| `error.schema.json` | D → E | 统一错误响应，含 17 个标准错误码 |
| `public-question.schema.json` | C → D → E | 公开题目（不含答案和评分点） |
| `agent-state.schema.json` | C ↔ D | LangGraph 状态图内部结构，标注了公开/私有字段边界 |
| `generated-question-private.schema.json` | C 内部 | 出题 Agent 完整输出，含私有答案和评分点 |
| `grade-result-private.schema.json` | C 内部 | 评分 Agent 完整输出，含分步评分 |

### Mock 文件

| 文件 | 场景 | 用途 |
|------|------|------|
| `mock/qa-success.json` | 问答成功 | 带 2 条 SourceRef + 4 个事件 |
| `mock/qa-refusal.json` | 证据不足拒答 | topic_mismatch，含拒答模板 |
| `mock/training-question.json` | 训练题目（提交前） | **隐私检查关键场景**——不含答案/rubric |
| `mock/grading-result.json` | 评分反馈 | 分步反馈 + 讲解 + 引用 |
| `mock/failure-model-timeout.json` | 模型超时 | retryable=true + trace_id |

## 校验

```bash
# 无需安装任何依赖
python contracts/validate.py
```

校验内容：Schema 元信息完整性 → Mock 加载 → 隐私边界扫描 → 字段类型校验

## 隐私红线

提交答案前的公共对象**严格禁止**包含以下字段（自动化校验 + 人工 Review）：

- `expected_answer` / `answer_private`
- `rubric` / `rubric_private`
- `private_content` / `private_evidence`
- `step_scores`（完整评分点）
- 任何含 `visibility=staff_only` 的检索块

## 变更流程

1. C 修改 Schema → 更新对应 Mock → 重新运行 `validate.py`
2. 涉及跨模块字段时先群里 @ 对应成员
3. PR 合并后其他人才能基于新 Schema 开发
