# C 成员接口文件

本目录包含成员 C（多 Agent 与提示词）需要的所有 B 侧接口定义。

## 文件说明

| 文件 | 用途 |
|---|---|
| `schemas.py` | Python 数据类，可直接 import 使用 |
| `接口契约文档.md` | 完整接口文档，含字段说明、调用示例、SSE 事件格式 |

## 快速开始

```python
# 1. 导入
from c.schemas import SourceRef, RetrievalResult, RetrievalFilters, EvidenceSufficiency

# 2. 调用检索
from worker.retrieval.retriever import HybridRetriever

retriever = HybridRetriever(...)
result = await retriever.retrieve(
    query="光的干涉条件是什么？",
    filters=RetrievalFilters(chapter_ids=["ch-03"]),
    user_role="member",
)

# 3. 判断是否拒答
if not result.sufficient:
    return refuse_response(reason=result.reason)

# 4. 组织回答 + 引用
for ref in result.source_refs:
    print(f"[{ref.document_name} 第{ref.page_number}页] {ref.excerpt}")
```

## 需要 C 确认的事项

- [x] **SourceRef 字段是否够用？** → 够用。出题用到的 knowledge_point_ids 等是 C 内部字段，不依赖 B 侧 SourceRef 扩展。
- [x] **excerpt 截断 300 字是否合适？** → 先按 300 字。后续若发现公式/表格上下文不足，可调大到 500 字——不阻塞当前开发。
- [x] **RetrievalFilters 维度是否覆盖出题需求？** → 覆盖了。chapter_ids + question_types + difficulty + exclude_chunk_ids + knowledge_point_ids + year 六个维度满足训练出题筛选。
- [x] **sufficient/reason 枚举是否覆盖所有拒答场景？** → 覆盖了。7 个枚举值与开发文档 5.7 节完全对应。
- [x] **页图 URL 格式是否正确？** → 格式 OK。

> 确认日期：2026-07-26 · 确认人：C · 结论：B 提供的接口无需改动，按 V1.0 执行
