# 成员 D �?数据库部署清�?

> �?B 提供，D 负责实施
> 日期�?026-07-23

---

## 一、环境要�?

| 组件 | 版本 | 说明 |
|---|---|---|
| PostgreSQL | 15+ | 需支持 pgvector 扩展 |
| pgvector | 0.5+ | `CREATE EXTENSION vector` |
| Python | 3.12+ | asyncpg + SQLAlchemy 2.0 |

## 二、Docker Compose 配置（参考）

```yaml
postgres:
  image: pgvector/pgvector:pg16
  environment:
    POSTGRES_DB: studyagents
    POSTGRES_USER: postgres
    POSTGRES_PASSWORD: <secure-password>
  ports:
    - "5432:5432"
  volumes:
    - pgdata:/var/lib/postgresql/data
```

## 三、数据库初始�?

### 3.1 启用扩展

```sql
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
```

### 3.2 Alembic 迁移

B 已写�?ORM 模型（`src/worker/db/models.py`），D 需执行�?

```bash
alembic revision --autogenerate -m "init knowledge base tables"
alembic upgrade head
```

### 3.3 手动添加的列（ORM 未覆盖）

两个列需要手�?SQL（Pydantic/SQLAlchemy 不原生支持）�?

```sql
-- pgvector 向量列（维度�?embedding 模型决定，默�?768�?
ALTER TABLE knowledge_chunks ADD COLUMN IF NOT EXISTS vector vector(768);

-- 全文检索列
ALTER TABLE knowledge_chunks ADD COLUMN IF NOT EXISTS search_vector tsvector;

-- HNSW 向量索引
CREATE INDEX IF NOT EXISTS ix_knowledge_chunks_vector
  ON knowledge_chunks USING hnsw (vector vector_cosine_ops)
  WITH (m = 16, ef_construction = 200);

-- GIN 全文检索索�?
CREATE INDEX IF NOT EXISTS ix_knowledge_chunks_search_vector
  ON knowledge_chunks USING gin (search_vector);
```

> ⚠️ 向量维度 768 是默认值。如果换�?embedding 模型，需要对应修改�?

## 四、B 负责�?8 张表

| �?| 主键 | 关键索引 |
|---|---|---|
| `documents` | UUID | `sha256 + active` 条件唯一 |
| `document_pages` | UUID | `(document_id, page_no)` 唯一 |
| `knowledge_chunks` | UUID | HNSW(vector) + GIN(search_vector) |
| `knowledge_points` | UUID | `code` 唯一，`parent_id` 自引�?|
| `chunk_knowledge_points` | 复合 | `(chunk_id, knowledge_point_id)` |
| `exam_questions` | UUID | `(document_id, question_no, version)` 唯一 |
| `ingestion_jobs` | UUID | `status` |
| `review_items` | UUID | `(status, kind)` |

## 五、B 需要的 API 端点

| 方法 | 路径 | B 的底层函�?|
|---|---|---|
| POST | `/api/documents` | `validator.validate_upload()` + `job_manager.create_job()` |
| GET | `/api/documents` | 资料列表查询 |
| GET | `/api/documents/{id}` | 文档详情 + 页数 + 索引状�?|
| DELETE | `/api/documents/{id}` | 软删�?|
| POST | `/api/documents/{id}/reindex` | 重建索引 |
| GET | `/api/documents/{id}/pages/{n}/image` | 页图（直接返�?PNG�?|
| GET | `/api/ingestion-jobs/{id}` | 导入进度 |
| POST | `/api/ingestion-jobs/{id}/retry` | 重试失败任务 |
| POST | `/api/retrieve` | `retriever.retrieve()` |
| GET | `/api/review-items` | 复核项列�?|
| PATCH | `/api/review-items/{id}` | 处理复核 |

## 六、Worker 运行方式

```bash
# 开发环�?
uv run --directory src python -m worker.main

# Docker
docker compose up worker -d
```

Worker 通过轮询 `ingestion_jobs` 表（`SELECT ... FOR UPDATE SKIP LOCKED`）获取任务；
每个阶段�?5 分钟租约，心�?60 秒续租；
崩溃后重启自动恢复过期任务�?

## 七、文件存�?

```
{项目根}/data/files/          �?FILES_ROOT
├── pages/                    �?PAGE_IMAGES_DIR
�?  └── {doc_uuid}/
�?      └── page_0001.png
�?      └── page_0002.png
�?      └── ...
└── {doc_uuid[:2]}/{doc_uuid[2:4]}/{doc_uuid}  �?原文�?
```

> 数据库只存相对路径，不存绝对路径�?

## 八、环境变�?

| 变量 | 必填 | 默认�?|
|---|---|---|
| `DATABASE_URL` | �?| `postgresql+psycopg://postgres:postgres@localhost:5432/studyagents` |
| `ASYNC_DATABASE_URL` | �?| `postgresql+asyncpg://...` |
| `FILES_ROOT` | | `./data/files` |
| `EMBEDDING_API_BASE` | | 空（�?降级伪向量） |
| `EMBEDDING_API_KEY` | | �?|
| `EMBEDDING_MODEL` | | `text-embedding-3-small` |

## 九、确认事�?

- [ ] PostgreSQL + pgvector 容器能启动？
- [ ] Alembic 迁移能跑�? 张表 + vector/search_vector 列都能建�?
- [ ] Worker 能连接数据库并轮�?`ingestion_jobs`�?
- [ ] 文件�?`FILES_ROOT` �?Docker 中能正常读写�?
- [ ] API 端点至少 `/api/documents` (POST) �?`/api/retrieve` (POST) 能调通？
