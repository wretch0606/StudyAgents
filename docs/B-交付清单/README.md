# B 交付清单

> 成员 B — 知识库与 RAG  
> 更新：2026-07-23  
> 状态：✅ 核心模块全部完成，172 测试通过

---

## 一、代码交付（`src/worker/`）

### 解析管线（ingestion/）

| 文件 | 行数 | 功能 | 测试 |
|---|---|---|---|
| `parsers/pdf.py` | 479 | PyMuPDF 数字文本提取+页图渲染+扫描件OCR+公式/表格/标题检测 | 18 |
| `parsers/ocr.py` | 261 | OCR 抽象接口+PaddleOCR适配器+Mock降级 | — |
| `parsers/docx.py` | 10 | 骨架（有余力补） | — |
| `parsers/pptx.py` | 10 | 骨架 | — |
| `parsers/image.py` | 10 | 骨架 | — |
| `validator.py` | 113 | 扩展名→MIME→SHA-256→去重 | 22 |
| `structurer.py` | 133 | 标题层级+公式绑定+表格标注 | 12 |
| `exam_extractor.py` | 195 | 题号检测(11模式)+题型判断(4类)+选项/答案/分值/子题提取 | 18 |
| `chunker.py` | 338 | 500字目标切分+80字重叠+短块合并+真题保护 | 20 |
| `vectorizer.py` | 113 | Embedding API+降级确定性伪向量+内容缓存 | 9 |
| `keyword_indexer.py` | 52 | jieba分词+内存倒排索引 | — |
| `pipeline.py` | 157 | 8阶段全串(校验→解析→OCR→结构化→切块→向量化→索引→完成) | 12 |
| `job_manager.py` | 208 | Skip-Locked任务获取+租约+心跳+恢复+重试 | 20 |
| `review.py` | 172 | OCR/答案低置信度复核+resolve/dismiss+统计 | 9 |

### 检索管线（retrieval/）

| 文件 | 行数 | 功能 | 测试 |
|---|---|---|---|
| `vector_search.py` | 170 | 抽象后端+内存余弦相似度+pgvector骨架 | 含在retriever |
| `keyword_search.py` | 222 | 抽象后端+BM25+jieba+tsvector骨架 | 含在retriever |
| `retriever.py` | 254 | RRF(k=60)融合+SourceRef构建+查询缓存+权限过滤 | 34 |
| `sufficiency.py` | 132 | 7规则充足性判断(无结果/私有/低分/缺数值/无图/冲突/充足) | 含上 |

### 数据库（db/）

| 文件 | 行数 | 功能 |
|---|---|---|
| `models.py` | 198 | 8表完整ORM(documents/document_pages/knowledge_chunks/knowledge_points/chunk_knowledge_points/exam_questions/ingestion_jobs/review_items) |
| `session.py` | 29 | asyncpg连接池+会话工厂 |

### 配置

| 文件 | 行数 |
|---|---|
| `schemas.py` | 263 |
| `config.py` | 56 |
| `main.py` | 70 |

---

## 二、测试（172 用例）

| 文件 | 用例数 |
|---|---|
| `test_pdf_parser.py` | 18 |
| `test_validator.py` | 22 |
| `test_chunker.py` | 20 |
| `test_structurer.py` | 12 |
| `test_exam_extractor.py` | 18 |
| `test_review.py` | 9 |
| `test_vectorizer.py` | 9 |
| `test_retriever.py` | 34 |
| `test_job_manager.py` | 20 |
| `test_pipeline.py` | 12 |
| **合计** | **172** |

---

## 三、对外交付

| 给谁 | 文件 | 位置 |
|---|---|---|
| C | schemas + 接口契约 + README | `c/` |
| D | 数据库部署清单 | `docs/成员D_数据库部署清单.md` |

---

## 四、技术指标

| 指标 | 数值 |
|---|---|
| 总代码行数 | ~5000 |
| Python 文件 | 28 |
| 测试文件 | 10 |
| 测试用例 | 172 |
| 测试通过率 | 100% |
| 核心依赖 | PyMuPDF / jieba / numpy / SQLAlchemy / asyncpg / pytest-asyncio |
| Python 版本 | 3.12+ |
