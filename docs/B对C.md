# B → C：source-ref.schema.json 校验反馈

> 版本：V1.0  
> 日期：2026-07-26  
> 来源：成员 B（知识库与 RAG）  
> 目标：成员 C（Agent 与提示词）

---

## 总体结论

Schema 对 B 的 `SourceRef` dataclass 理解基本正确，required 字段全部覆盖，类型映射准确。**仅有 2 处需要修正**，修完即可合入。

---

## 问题 1：字段名不一致 `page_no` → `page_number`

### 现状

| 位置 | 字段名 |
|---|---|
| B 的 `SourceRef` dataclass（`c/schemas.py`） | `page_number: int` |
| C 的 `source-ref.schema.json` | `"page_no": { "type": "integer" }` |
| 系统文档 §9.7 公开类型 | `page_number: number` |

### 影响

- 序列化时字段名不一致会导致 C 解析失败或需要额外映射
- 前端 E 如果直接消费 JSON，字段名不确定

### 建议

**C 改为 `page_number`**，理由：

1. `SourceRef` 是 B 定义的数据结构，schema 是它的序列化表示，源头统一
2. 系统开发文档 §9.7 用的是 `page_number`
3. 语义更明确：`page_no` 可能误解为 "第几页的编号索引" 而非 "页码"

```diff
"required": [
    "document_id",
    "document_name",
-   "page_no",
+   "page_number",
    "chunk_id",
    "excerpt"
],

"properties": {
-   "page_no": {
+   "page_number": {
        "type": "integer",
        "minimum": 1
    },
```

---

## 问题 2：缺少 `score` 字段

### 现状

| 位置 | 有 score？ |
|---|---|
| B 的 `SourceRef` dataclass | `score: float = 0.0  # RRF 融合分数` |
| C 的 `source-ref.schema.json` | ❌ 缺失 |

### `score` 是什么

RRF（Reciprocal Rank Fusion）融合分数。每条检索到的证据都有：

```python
score(d) = Σ 1 / (60 + rank_i(d))
```

- 两个来源（向量 + 关键词）各贡献一项，总分 ≤ 2/61 ≈ 0.033
- `score` 越高，证据与查询越相关

### 为什么 C 可能需要它

| 场景 | 用法 |
|---|---|
| **答案组织** | 按 score 降序排列引用，最重要的放前面 |
| **拒答判断** | `score` 过低（< 0.005）→ 证据不可靠 |
| **多轮对话** | 排除低分引用，减少上下文噪声 |
| **调试/评测** | 查看哪些查询返回了低分结果 |

### 建议

在 `properties` 中新增 `score`：

```diff
+   "score": {
+       "type": "number",
+       "minimum": 0,
+       "description": "RRF 融合分数，越高越相关。典型值 0.005–0.033"
+   }
```

`score` 不是必填字段——即使后续版本移除也不破坏兼容性。所以放在 required 之外即可。

---

## 字段校验完整表

| B dataclass | C schema | required | 类型一致 | 备注 |
|---|---|---|---|---|
| `document_id: str` | `document_id: string` | ✅ | ✅ | |
| `document_name: str` | `document_name: string` | ✅ | ✅ | |
| `page_number: int` | `page_no: integer` | ✅ | 🔴改名 | 统一为 `page_number` |
| `question_no: str\|None` | `question_no: str\|null` | — | ✅ | |
| `chunk_id: str` | `chunk_id: string` | ✅ | ✅ | |
| `excerpt: str` | `excerpt: string` | ✅ | ✅ | 实际 ≤300 字 |
| `page_image_url: str\|None` | `page_image_url: str\|null` | — | ✅ | |
| `score: float` | — | — | 🔴缺失 | 新增 |

---

## 修正后的完整 Schema

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://studyagents.local/schemas/source-ref.schema.json",
  "title": "SourceRef",
  "description": "B 提供：指向原始资料的可引用证据。由知识 Agent 检索后填充。",
  "type": "object",
  "additionalProperties": false,
  "required": [
    "document_id",
    "document_name",
    "page_number",
    "chunk_id",
    "excerpt"
  ],
  "properties": {
    "document_id": {
      "type": "string",
      "minLength": 1,
      "description": "文档 UUID"
    },
    "document_name": {
      "type": "string",
      "minLength": 1,
      "description": "文档展示名，如 '光学讲义.pdf'"
    },
    "page_number": {
      "type": "integer",
      "minimum": 1,
      "description": "页码，从 1 开始"
    },
    "question_no": {
      "type": ["string", "null"],
      "description": "题号，如 '3' 或 '二.1'，非真题为 null"
    },
    "chunk_id": {
      "type": "string",
      "minLength": 1,
      "description": "知识块 UUID"
    },
    "excerpt": {
      "type": "string",
      "minLength": 1,
      "description": "摘录文本（≤300 字）"
    },
    "page_image_url": {
      "type": ["string", "null"],
      "description": "页图 URL，格式 /api/documents/{id}/pages/{n}/image"
    },
    "score": {
      "type": "number",
      "minimum": 0,
      "description": "RRF 融合分数，越高越相关。典型值 0.005–0.033"
    }
  }
}
```

---

## 行动项

- [ ] C 将 `page_no` 改为 `page_number`
- [ ] C 新增 `score` 字段（非必填）
- [ ] C 更新后通知 B，B 确认即可合入

> 其他 Schema（`agent-event.schema.json`、`RetrievalResult` 等）本次未检查，如 C 已创建，下次一并校验。
