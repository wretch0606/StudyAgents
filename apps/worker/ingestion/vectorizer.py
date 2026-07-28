"""
向量化模块 — Embedding API 封装

生产模式调用云端 API；测试模式使用随机向量降级。
"""

import hashlib
import logging
import math
from typing import Optional

from apps.worker.config import EMBEDDING_API_BASE, EMBEDDING_API_KEY, EMBEDDING_MODEL

logger = logging.getLogger(__name__)


class Vectorizer:
    """
    Embedding 向量化器。

    使用示例：
        v = Vectorizer()
        embeddings = await v.embed_chunks(chunks)
    """

    def __init__(
        self,
        model: str = EMBEDDING_MODEL,
        api_base: str = EMBEDDING_API_BASE,
        api_key: str = EMBEDDING_API_KEY,
        dim: int = 768,
    ):
        self.model = model
        self.api_base = api_base
        self.api_key = api_key
        self.dim = dim

        # 内容哈希 → 向量缓存（相同内容复用向量）
        self._cache: dict[str, list[float]] = {}

    # ---- 批量向量化 ----

    async def embed_chunks(self, chunks: list) -> list[list[float]]:
        """
        批量向量化知识块。

        相同 content 复用缓存中的向量。
        """
        embeddings: list[list[float]] = []
        new_texts: list[str] = []
        new_indices: list[int] = []

        # 1. 检查缓存
        for i, chunk in enumerate(chunks):
            content_hash = chunk.content_hash if hasattr(chunk, 'content_hash') else hashlib.sha256(chunk.content.encode()).hexdigest()

            if content_hash in self._cache:
                embeddings.append(self._cache[content_hash])
            else:
                embeddings.append([])  # 占位
                new_texts.append(chunk.content)
                new_indices.append(i)

        # 2. 批量调用 API
        if new_texts:
            new_vectors = await self._embed_batch(new_texts)

            for idx, vec in zip(new_indices, new_vectors):
                content_hash = hashlib.sha256(chunks[idx].content.encode()).hexdigest()
                self._cache[content_hash] = vec
                embeddings[idx] = vec

        return embeddings

    async def embed_query(self, query: str) -> list[float]:
        """单条查询向量化"""
        results = await self._embed_batch([query])
        return results[0]

    # ---- 底层调用 ----

    async def _embed_batch(self, texts: list[str]) -> list[list[float]]:
        """
        调用 Embedding API 或本地模型。

        降级策略：API 不可用时使用确定性伪向量。
        """
        # 尝试 API
        if self.api_base and self.api_key:
            try:
                return await self._call_api(texts)
            except Exception as e:
                logger.warning(f"Embedding API 调用失败，使用降级向量: {e}")

        # 降级：确定性伪向量（基于文本哈希，相同文本→相同向量）
        logger.info(f"使用降级向量 (dim={self.dim})，共 {len(texts)} 条")
        return [self._fallback_vector(t) for t in texts]

    async def _call_api(self, texts: list[str]) -> list[list[float]]:
        """调用兼容 OpenAI 格式的 Embedding API"""
        import httpx

        url = f"{self.api_base.rstrip('/')}/embeddings"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "input": texts,
        }

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()

        vectors = [
            item["embedding"]
            for item in sorted(data["data"], key=lambda x: x["index"])
        ]
        return vectors

    # ---- 降级向量 ----

    def _fallback_vector(self, text: str) -> list[float]:
        """
        基于文本哈希的确定性伪向量。

        使用 SHA-256 哈希种子生成归一化向量。
        相同文本始终产生相同向量，适合测试和降级。
        """
        import random
        import struct

        # SHA-256 → 64 个 32-bit 整数作为随机种子
        digest = hashlib.sha256(text.encode()).digest()
        seeds = struct.unpack(">" + "I" * (len(digest) // 4), digest)

        # 生成归一化向量
        rng = random.Random(seeds[0])
        vec = [rng.gauss(0, 1) for _ in range(self.dim)]

        # 归一化
        norm = math.sqrt(sum(x * x for x in vec))
        if norm > 0:
            vec = [x / norm for x in vec]

        return vec

    def clear_cache(self):
        """清空向量缓存"""
        self._cache.clear()

    @property
    def cache_size(self) -> int:
        return len(self._cache)
