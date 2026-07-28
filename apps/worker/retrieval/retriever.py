"""
混合检索引擎 — RRF 融合 + SourceRef 构建 + 缓存

检索流程：
  用户查询
    ├─ 向量化查询
    ├─ 向量检索 Top 20  (语义)
    ├─ 关键词检索 Top 20 (jieba BM25)
    └─ RRF(k=60) 融合 → Top 8
         └─ 构建 SourceRef[]
              └─ 充足性判断
"""

import hashlib
import logging
import time
from typing import Optional

from worker.config import (
    RETRIEVAL_FINAL_K,
    RETRIEVAL_KEYWORD_K,
    RETRIEVAL_VECTOR_K,
    RRF_K,
)
from worker.retrieval.keyword_search import (
    InMemoryKeywordBackend,
    KeywordSearchBackend,
    SearchHit,
)
from worker.retrieval.sufficiency import SufficiencyResult, judge_sufficiency
from worker.retrieval.vector_search import (
    InMemoryVectorBackend,
    VectorSearchBackend,
)
from worker.schemas import RetrievalFilters, RetrievalResult, SourceRef

logger = logging.getLogger(__name__)


class HybridRetriever:
    """
    混合检索器。

    使用示例：
        retriever = HybridRetriever()
        await retriever.index_chunks(chunks, embeddings)
        result = await retriever.retrieve("光的干涉条件是什么？")
    """

    def __init__(
        self,
        vector_backend: Optional[VectorSearchBackend] = None,
        keyword_backend: Optional[KeywordSearchBackend] = None,
        vector_k: int = RETRIEVAL_VECTOR_K,
        keyword_k: int = RETRIEVAL_KEYWORD_K,
        final_k: int = RETRIEVAL_FINAL_K,
        rrf_k: int = RRF_K,
    ):
        self.vector = vector_backend or InMemoryVectorBackend()
        self.keyword = keyword_backend or InMemoryKeywordBackend()
        self.vector_k = vector_k
        self.keyword_k = keyword_k
        self.final_k = final_k
        self.rrf_k = rrf_k

        # 文档名缓存 (document_id → name)
        self._doc_names: dict[str, str] = {}

        # 查询缓存 (query_hash → RetrievalResult)
        self._cache: dict[str, RetrievalResult] = {}

    # ================================================================
    # 索引
    # ================================================================

    async def index_chunks(
        self,
        chunks: list,  # list[Chunk]
        embeddings: list[list[float]],
    ):
        """
        批量索引知识块。

        Args:
            chunks: Chunk 对象列表
            embeddings: 对应的向量列表（顺序一致）
        """
        if len(chunks) != len(embeddings):
            raise ValueError(
                f"chunks ({len(chunks)}) 和 embeddings ({len(embeddings)}) 数量不一致"
            )

        for chunk, embedding in zip(chunks, embeddings):
            metadata = {
                "chunk_id": chunk.chunk_id,
                "document_id": chunk.document_id,
                "page_from": chunk.page_from,
                "page_to": chunk.page_to,
                "question_no": chunk.question_no,
                "section_path": " > ".join(chunk.section_path) if chunk.section_path else "",
                "visibility": chunk.visibility.value if hasattr(chunk.visibility, 'value') else str(chunk.visibility),
                "material_type": chunk.material_type.value if hasattr(chunk.material_type, 'value') else str(chunk.material_type),
                "year": chunk.year,
            }

            await self.vector.add(
                chunk_id=chunk.chunk_id,
                embedding=embedding,
                content=chunk.content,
                metadata=metadata,
            )
            await self.keyword.add(
                chunk_id=chunk.chunk_id,
                content=chunk.content,
                metadata=metadata,
            )

        logger.info(f"索引完成: {len(chunks)} 块")

    async def set_doc_names(self, names: dict[str, str]):
        """设置文档名映射"""
        self._doc_names.update(names)

    # ================================================================
    # 检索
    # ================================================================

    async def retrieve(
        self,
        query: str,
        query_embedding: Optional[list[float]] = None,
        filters: Optional[RetrievalFilters] = None,
        user_role: str = "member",
    ) -> RetrievalResult:
        """
        混合检索主入口。

        Args:
            query: 用户查询文本
            query_embedding: 查询向量（可选，不传则用零向量降级）
            filters: 过滤条件
            user_role: 用户角色（member/admin），决定是否返回 staff_only 内容

        Returns:
            RetrievalResult 包含 SourceRef 列表和充足性判断
        """
        t0 = time.perf_counter()

        # 缓存检查
        cache_key = self._cache_key(query, filters)
        if cache_key in self._cache:
            logger.debug(f"缓存命中: {query[:30]}...")
            return self._cache[cache_key]

        # 1. 向量检索
        query_vec = query_embedding or _zero_vector(128)  # 默认 128 维零向量
        vector_task = self.vector.search(query_vec, self.vector_k, filters)

        # 2. 关键词检索
        keyword_task = self.keyword.search(query, self.keyword_k, filters)

        # 并行执行
        vector_hits = await vector_task
        keyword_hits = await keyword_task

        # 3. RRF 融合
        fused = self.rrf_fusion(vector_hits, keyword_hits)

        # 4. 权限过滤 + 构建 SourceRef
        source_refs = self._build_source_refs(fused, user_role)

        # 限制数量
        source_refs = source_refs[:self.final_k]

        # 5. 充足性判断
        sufficiency = judge_sufficiency(source_refs, query)

        elapsed = (time.perf_counter() - t0) * 1000

        result = RetrievalResult(
            source_refs=source_refs,
            sufficient=sufficiency.sufficient,
            reason=str(sufficiency.reason.value),
            requires_vision=sufficiency.requires_vision,
            elapsed_ms=round(elapsed, 1),
        )

        # 缓存
        self._cache[cache_key] = result

        logger.info(
            f"检索完成: '{query[:30]}...' → "
            f"向量{len(vector_hits)}+关键词{len(keyword_hits)} "
            f"→ RRF融合{len(fused)} → Top{len(source_refs)} "
            f"({elapsed:.0f}ms)"
        )
        return result

    # ================================================================
    # RRF 融合
    # ================================================================

    def rrf_fusion(
        self,
        vector_hits: list[SearchHit],
        keyword_hits: list[SearchHit],
    ) -> list[SearchHit]:
        """
        Reciprocal Rank Fusion。

        score(d) = Σ 1 / (k + rank_i(d))

        Args:
            vector_hits: 向量搜索结果（已排序）
            keyword_hits: 关键词搜索结果（已排序）

        Returns:
            按 RRF 分数降序排列的 SearchHit 列表
        """
        scores: dict[str, float] = {}
        metadata: dict[str, dict] = {}
        contents: dict[str, str] = {}

        # 向量排名
        for rank, hit in enumerate(vector_hits):
            rrf_score = 1.0 / (self.rrf_k + rank + 1)
            scores[hit.chunk_id] = scores.get(hit.chunk_id, 0.0) + rrf_score
            metadata[hit.chunk_id] = hit.metadata
            contents[hit.chunk_id] = hit.content

        # 关键词排名
        for rank, hit in enumerate(keyword_hits):
            rrf_score = 1.0 / (self.rrf_k + rank + 1)
            scores[hit.chunk_id] = scores.get(hit.chunk_id, 0.0) + rrf_score
            metadata[hit.chunk_id] = hit.metadata
            contents[hit.chunk_id] = hit.content

        # 排序
        sorted_ids = sorted(scores, key=lambda cid: scores[cid], reverse=True)

        return [
            SearchHit(
                chunk_id=cid,
                score=scores[cid],
                content=contents.get(cid, ""),
                metadata=metadata.get(cid, {}),
            )
            for cid in sorted_ids
        ]

    # ================================================================
    # SourceRef 构建
    # ================================================================

    def _build_source_refs(
        self, hits: list[SearchHit], user_role: str
    ) -> list[SourceRef]:
        """从 SearchHit 构建 SourceRef，过滤私有内容"""
        refs = []
        for hit in hits:
            meta = hit.metadata

            # 权限过滤
            visibility = meta.get("visibility", "public")
            if visibility == "staff_only" and user_role != "admin":
                continue

            doc_id = meta.get("document_id", "")
            doc_name = self._doc_names.get(doc_id, doc_id[:8] if doc_id else "未知")

            # 摘录（截取 ≤ 300 字）
            excerpt = hit.content[:300]
            if len(hit.content) > 300:
                excerpt += "..."

            ref = SourceRef(
                document_id=doc_id,
                document_name=doc_name,
                page_number=meta.get("page_from", 0),
                question_no=meta.get("question_no"),
                chunk_id=hit.chunk_id,
                excerpt=excerpt,
                page_image_url=self._page_image_url(doc_id, meta.get("page_from", 0)),
                score=hit.score,
            )
            refs.append(ref)

        return refs

    def _page_image_url(self, doc_id: str, page_no: int) -> Optional[str]:
        """构造页图 URL"""
        if not doc_id or not page_no:
            return None
        return f"/api/documents/{doc_id}/pages/{page_no}/image"

    # ================================================================
    # 缓存
    # ================================================================

    def _cache_key(self, query: str, filters: Optional[RetrievalFilters]) -> str:
        """生成缓存键"""
        raw = query.strip().lower()
        if filters:
            raw += str(filters)
        return hashlib.md5(raw.encode()).hexdigest()

    def clear_cache(self):
        """清空缓存"""
        self._cache.clear()

    @property
    def cache_size(self) -> int:
        return len(self._cache)


# ================================================================
# 工具函数
# ================================================================

def _zero_vector(dim: int = 128) -> list[float]:
    """零向量（无 embedding 时的降级）"""
    return [0.0] * dim
