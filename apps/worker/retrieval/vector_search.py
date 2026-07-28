"""
向量检索 — pgvector ANN + 内存降级

生产模式使用 pgvector HNSW 索引做近似最近邻搜索；
测试/无数据库时使用内存余弦相似度降级。
"""

import logging
from abc import ABC, abstractmethod
from typing import Optional

import numpy as np

from apps.worker.schemas import RetrievalFilters

logger = logging.getLogger(__name__)


# ============================================================
# 搜索结果类型
# ============================================================

class SearchHit:
    """单条检索命中"""
    __slots__ = ("chunk_id", "score", "content", "metadata")

    def __init__(
        self,
        chunk_id: str,
        score: float,
        content: str = "",
        metadata: Optional[dict] = None,
    ):
        self.chunk_id = chunk_id
        self.score = score
        self.content = content
        self.metadata = metadata or {}

    def __repr__(self):
        return f"SearchHit(id={self.chunk_id[:8]}..., score={self.score:.4f})"


# ============================================================
# 抽象后端
# ============================================================

class VectorSearchBackend(ABC):
    """向量搜索后端抽象"""

    @abstractmethod
    async def search(
        self,
        query_embedding: list[float],
        top_k: int = 20,
        filters: Optional[RetrievalFilters] = None,
    ) -> list[SearchHit]:
        """执行向量相似度搜索"""
        ...

    @abstractmethod
    async def add(self, chunk_id: str, embedding: list[float], content: str, metadata: dict):
        """添加向量到索引"""
        ...

    @abstractmethod
    async def remove(self, chunk_id: str):
        """从索引中移除"""
        ...


# ============================================================
# 内存后端（测试 / 降级）
# ============================================================

class InMemoryVectorBackend(VectorSearchBackend):
    """
    基于 numpy 的内存向量搜索。

    使用余弦相似度（归一化后即为内积）。
    适用于开发测试和单机小规模场景。
    """

    def __init__(self):
        self._ids: list[str] = []
        self._vectors: list[np.ndarray] = []
        self._contents: list[str] = []
        self._metadata: list[dict] = []

    # ---- 搜索 ----

    async def search(
        self,
        query_embedding: list[float],
        top_k: int = 20,
        filters: Optional[RetrievalFilters] = None,
    ) -> list[SearchHit]:
        """余弦相似度搜索"""
        if not self._vectors:
            return []

        query_vec = np.array(query_embedding, dtype=np.float32)
        query_norm = np.linalg.norm(query_vec)
        if query_norm == 0:
            return []

        # 归一化查询向量
        query_vec = query_vec / query_norm

        # 批量计算余弦相似度
        matrix = np.stack(self._vectors)  # (N, D)
        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        norms = np.where(norms == 0, 1.0, norms)
        normalized = matrix / norms
        scores = np.dot(normalized, query_vec)  # (N,)

        # 排序
        indices = np.argsort(-scores)  # 降序

        hits = []
        for idx in indices:
            if len(hits) >= top_k:
                break

            # 过滤
            if not self._match_filters(self._metadata[idx], filters):
                continue

            hits.append(SearchHit(
                chunk_id=self._ids[idx],
                score=float(scores[idx]),
                content=self._contents[idx],
                metadata=dict(self._metadata[idx]),
            ))

        return hits

    # ---- 增删 ----

    async def add(self, chunk_id: str, embedding: list[float], content: str, metadata: dict):
        """添加向量"""
        vec = np.array(embedding, dtype=np.float32)
        self._ids.append(chunk_id)
        self._vectors.append(vec)
        self._contents.append(content)
        self._metadata.append(metadata)

    async def remove(self, chunk_id: str):
        """移除向量"""
        try:
            idx = self._ids.index(chunk_id)
            del self._ids[idx]
            del self._vectors[idx]
            del self._contents[idx]
            del self._metadata[idx]
        except ValueError:
            pass

    def __len__(self):
        return len(self._ids)

    # ---- 过滤 ----

    @staticmethod
    def _match_filters(metadata: dict, filters: Optional[RetrievalFilters]) -> bool:
        """检查元数据是否匹配过滤条件"""
        if filters is None:
            return True

        # 章节过滤
        if filters.chapter_ids:
            chunk_section = metadata.get("section_path", "")
            if not any(cid in chunk_section for cid in filters.chapter_ids):
                return False

        # 知识点过滤
        if filters.knowledge_point_ids:
            chunk_kps = set(metadata.get("knowledge_point_ids", []))
            if not chunk_kps.intersection(filters.knowledge_point_ids):
                return False

        # 题型过滤
        if filters.question_types:
            chunk_type = metadata.get("question_type", "")
            if chunk_type and chunk_type not in filters.question_types:
                return False

        # 年份过滤
        if filters.year is not None:
            chunk_year = metadata.get("year")
            if chunk_year is not None and chunk_year != filters.year:
                return False

        # 排除 ID
        if filters.exclude_chunk_ids:
            chunk_id = metadata.get("chunk_id", "")
            if chunk_id in filters.exclude_chunk_ids:
                return False

        return True


# ============================================================
# pgvector 后端（骨架）
# ============================================================

class PGVectorBackend(VectorSearchBackend):
    """
    pgvector HNSW 后端（Day 2 实现）。

    使用 asyncpg 或 SQLAlchemy 执行 ANN 查询：
      SELECT ... ORDER BY vector <=> :query_vec LIMIT :k
    """

    def __init__(self, connection_string: str):
        self._conn_string = connection_string

    async def search(
        self,
        query_embedding: list[float],
        top_k: int = 20,
        filters: Optional[RetrievalFilters] = None,
    ) -> list[SearchHit]:
        # TODO Day 2: 接入 pgvector
        raise NotImplementedError("pgvector 后端待 Day 2 实现")

    async def add(self, chunk_id: str, embedding: list[float], content: str, metadata: dict):
        raise NotImplementedError("pgvector 后端待 Day 2 实现")

    async def remove(self, chunk_id: str):
        raise NotImplementedError("pgvector 后端待 Day 2 实现")
