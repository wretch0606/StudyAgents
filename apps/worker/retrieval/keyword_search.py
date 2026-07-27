"""
关键词检索 — jieba 分词 + 匹配

生产模式使用 PostgreSQL tsvector + GIN 索引；
测试/无数据库时使用内存 BM25 风格的词频匹配降级。
"""

import logging
import re
from abc import ABC, abstractmethod
from collections import defaultdict
from math import log
from typing import Optional

from worker.schemas import RetrievalFilters

logger = logging.getLogger(__name__)


# ============================================================
# 搜索结果类型（复用 vector_search）
# ============================================================

from worker.retrieval.vector_search import SearchHit


# ============================================================
# 抽象后端
# ============================================================

class KeywordSearchBackend(ABC):
    """关键词搜索后端抽象"""

    @abstractmethod
    async def search(
        self,
        query: str,
        top_k: int = 20,
        filters: Optional[RetrievalFilters] = None,
    ) -> list[SearchHit]:
        """执行关键词搜索"""
        ...

    @abstractmethod
    async def add(self, chunk_id: str, content: str, metadata: dict):
        """添加文档"""
        ...

    @abstractmethod
    async def remove(self, chunk_id: str):
        """移除文档"""
        ...


# ============================================================
# 分词工具
# ============================================================

def tokenize_chinese(text: str) -> list[str]:
    """
    中文分词，优先 jieba，降级为字粒度回退。

    返回过滤后的词条列表（去停用词、去标点）。
    """
    try:
        import jieba
        tokens = list(jieba.cut(text))
    except ImportError:
        # 降级：中文按 2-gram + 英文词切分
        tokens = _fallback_tokenize(text)

    # 过滤停用词和短词
    stop_words = _get_stop_words()
    return [
        t.strip().lower()
        for t in tokens
        if len(t.strip()) >= 2 and t.strip() not in stop_words
    ]


def _fallback_tokenize(text: str) -> list[str]:
    """无 jieba 时的降级分词：中文 2-gram + 英文词"""
    # 分离中文和非中文
    parts = re.findall(r"[一-鿿]{2,}|[a-zA-Z0-9]+|[一-鿿]", text)
    tokens = []
    for p in parts:
        if re.match(r"^[一-鿿]$", p):
            continue  # 单字跳过
        tokens.append(p)
    return tokens


_STOP_WORDS: Optional[set] = None


def _get_stop_words() -> set:
    """基础中文停用词表"""
    global _STOP_WORDS
    if _STOP_WORDS is None:
        _STOP_WORDS = {
            "的", "了", "在", "是", "我", "有", "和", "就", "不", "人", "都", "一",
            "一个", "上", "也", "很", "到", "说", "要", "去", "你", "会", "着",
            "没有", "看", "好", "自己", "这", "他", "她", "它", "们", "那", "些",
            "所", "被", "把", "让", "给", "从", "对", "与", "但", "而", "或",
            "且", "因", "为", "以", "及", "之", "其", "可", "能", "将", "已",
            "该", "此", "其", "中", "等", "各", "某", "另", "再", "又",
            "什么", "怎么", "哪", "吗", "呢", "吧", "啊", "哦", "嗯",
            "the", "a", "an", "is", "are", "was", "were", "be", "been",
            "of", "in", "to", "for", "with", "on", "at", "by", "from",
            "this", "that", "it", "and", "or", "but", "not",
        }
    return _STOP_WORDS


# ============================================================
# 内存后端
# ============================================================

class InMemoryKeywordBackend(KeywordSearchBackend):
    """
    基于 BM25 的内存关键词搜索。

    存储 document → token frequency，
    查询时计算 BM25 分数排序。
    """

    def __init__(self, k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b

        self._ids: list[str] = []
        self._contents: list[str] = []
        self._metadata: list[dict] = []
        self._tokens: list[list[str]] = []  # 每个文档的分词结果

        # 统计
        self._total_docs = 0
        self._doc_freq: dict[str, int] = defaultdict(int)  # 词 → 出现文档数
        self._avg_doc_len: float = 0.0

    # ---- 搜索 ----

    async def search(
        self,
        query: str,
        top_k: int = 20,
        filters: Optional[RetrievalFilters] = None,
    ) -> list[SearchHit]:
        """BM25 搜索"""
        if not self._contents:
            return []

        query_tokens = tokenize_chinese(query)
        if not query_tokens:
            return []

        scores = []
        for i, doc_tokens in enumerate(self._tokens):
            # 过滤
            if not self._match_filters(self._metadata[i], filters):
                continue

            score = self._bm25_score(query_tokens, doc_tokens)
            if score > 0:
                scores.append((i, score))

        # 排序
        scores.sort(key=lambda x: -x[1])
        return [
            SearchHit(
                chunk_id=self._ids[i],
                score=score,
                content=self._contents[i],
                metadata=dict(self._metadata[i]),
            )
            for i, score in scores[:top_k]
        ]

    # ---- 增删 ----

    async def add(self, chunk_id: str, content: str, metadata: dict):
        """添加文档并更新索引统计"""
        tokens = tokenize_chinese(content)

        self._ids.append(chunk_id)
        self._contents.append(content)
        self._metadata.append(metadata)
        self._tokens.append(tokens)

        # 更新文档频率
        unique_tokens = set(tokens)
        for t in unique_tokens:
            self._doc_freq[t] += 1

        self._total_docs += 1
        self._avg_doc_len = sum(len(t) for t in self._tokens) / self._total_docs

    async def remove(self, chunk_id: str):
        """移除文档"""
        try:
            idx = self._ids.index(chunk_id)
            # 更新文档频率
            for t in set(self._tokens[idx]):
                self._doc_freq[t] -= 1
                if self._doc_freq[t] <= 0:
                    del self._doc_freq[t]

            del self._ids[idx]
            del self._contents[idx]
            del self._metadata[idx]
            del self._tokens[idx]
            self._total_docs -= 1

            if self._total_docs > 0:
                self._avg_doc_len = sum(len(t) for t in self._tokens) / self._total_docs
        except ValueError:
            pass

    # ---- BM25 ----

    def _bm25_score(self, query_tokens: list[str], doc_tokens: list[str]) -> float:
        """计算 BM25 分数"""
        doc_len = len(doc_tokens)
        score = 0.0
        doc_tf = defaultdict(int)
        for t in doc_tokens:
            doc_tf[t] += 1

        for qt in query_tokens:
            tf = doc_tf.get(qt, 0)
            if tf == 0:
                continue

            df = self._doc_freq.get(qt, 0)
            if df == 0:
                continue

            # IDF
            idf = log((self._total_docs - df + 0.5) / (df + 0.5) + 1.0)

            # TF 归一化
            numerator = tf * (self.k1 + 1)
            denominator = tf + self.k1 * (1 - self.b + self.b * doc_len / max(self._avg_doc_len, 1))
            score += idf * numerator / denominator

        return score

    # ---- 过滤 ----

    @staticmethod
    def _match_filters(metadata: dict, filters: Optional[RetrievalFilters]) -> bool:
        if filters is None:
            return True
        if filters.chapter_ids:
            chunk_section = metadata.get("section_path", "")
            if not any(cid in chunk_section for cid in filters.chapter_ids):
                return False
        if filters.exclude_chunk_ids:
            if metadata.get("chunk_id", "") in filters.exclude_chunk_ids:
                return False
        if filters.year is not None:
            if metadata.get("year") and metadata["year"] != filters.year:
                return False
        return True

    def __len__(self):
        return len(self._ids)


# ============================================================
# PostgreSQL tsvector 后端（骨架）
# ============================================================

class PGKeywordBackend(KeywordSearchBackend):
    """
    PostgreSQL tsvector + GIN 后端（Day 2 实现）。
    """

    def __init__(self, connection_string: str):
        self._conn_string = connection_string

    async def search(
        self,
        query: str,
        top_k: int = 20,
        filters: Optional[RetrievalFilters] = None,
    ) -> list[SearchHit]:
        raise NotImplementedError("pg 关键词后端待 Day 2 实现")

    async def add(self, chunk_id: str, content: str, metadata: dict):
        raise NotImplementedError("pg 关键词后端待 Day 2 实现")

    async def remove(self, chunk_id: str):
        raise NotImplementedError("pg 关键词后端待 Day 2 实现")
