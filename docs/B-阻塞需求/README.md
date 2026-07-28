# B 阻塞需求

> 哪些事卡住了我，需要谁做什么

---

## 🔴 阻塞 1：D — 数据库 + API

**我需要什么：**

1. **PostgreSQL + pgvector 能连上**
   - Docker Compose 里起 `pgvector/pgvector:pg16`
   - 执行 `CREATE EXTENSION vector`
   - 给我连接字符串

2. **Alembic 迁移能跑**
   - ORM 模型在 `src/worker/db/models.py`（8 张表）
   - 额外需要手动 SQL 的两列：
     ```sql
     ALTER TABLE knowledge_chunks ADD COLUMN vector vector(768);
     ALTER TABLE knowledge_chunks ADD COLUMN search_vector tsvector;
     ```
   - 详见 `docs/成员D_数据库部署清单.md`

3. **API 端点上线（至少这两个）**
   - `POST /api/documents` — 上传文件
   - `POST /api/retrieve` — 调用我的 `retriever.retrieve()`

**我现在怎么凑合：** 全部用内存后端跑，没有持久化

**阻塞的影响：**
- 不能真实入库资料
- 不能用 pgvector 做 ANN 搜索
- 不能联调全链路

---

## 🔴 阻塞 2：C — Agent 接口确认

**我需要什么：**

1. **确认 `SourceRef` 字段够不够用**
   - 现有字段：document_id / document_name / page_number / question_no / chunk_id / excerpt / page_image_url / score
   - 文件在 `c/schemas.py`

2. **确认拒答枚举**
   - no_results / topic_mismatch / missing_condition / conflicting / staff_only / image_unavailable
   - C 需要每种情况写对应的用户提示文案

3. **确认检索调用方式**
   - 直接 import 还是通过 D 的 API？
   - 训练模式下的过滤参数怎么填？

**我现在怎么凑合：** 接口已经定义好了，但 C 还没说 OK

**阻塞的影响：**
- C 写不了知识 Agent 的提示词
- 问答链路的证据→回答对接不上

---

## 🟡 阻塞 3：A — 评测集

**我需要什么：**

1. **50 条标注评测集**
   - 15 条事实问答 + 15 条计算/简答 + 10 条含图题 + 5 条应拒答 + 5 条跨知识点
   - 每条标注「正确答案」和「应该命中的证据页」

2. **评测标准确认**
   - Recall@5 ≥ 85% 怎么算？（Top 5 里至少一个命中就算通过？）

**我现在怎么凑合：** 用样例 PDF 手动构造了几个查询

**阻塞的影响：**
- 算不了 Recall@5
- 检索参数调优没有依据

---

## 🟢 不阻塞但要排：E — 前端联调

**时机：** D 的 API 上线后

**需要联调的内容：**
- 上传页面 + 进度条
- 页图点击预览
- Agent 协作抽屉的 SSE 事件

---

## 📋 我需要做的（不被阻塞的）

- [x] 子题号切分 `3.(1)/3.(2)`
- [x] Pipeline 错误恢复测试
- [x] 答辩演示预缓存
- [x] D 的部署文档
- [ ] 等 D 搭好环境 → 切换到 pgvector 后端
- [ ] 等 A 给评测集 → 跑 Recall@5
- [ ] 等 C 确认接口 → 联调问答链路
