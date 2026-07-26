"""
向量化器测试
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from worker.ingestion.vectorizer import Vectorizer


class FakeChunk:
    def __init__(self, content: str, content_hash: str = ""):
        self.content = content
        self.content_hash = content_hash


class TestVectorizer:
    """向量化器"""

    @pytest.mark.asyncio
    async def test_embed_chunks_basic(self):
        v = Vectorizer()
        chunks = [FakeChunk("测试文本"), FakeChunk("另一段文本")]
        embs = await v.embed_chunks(chunks)
        assert len(embs) == 2
        assert len(embs[0]) == v.dim
        assert len(embs[1]) == v.dim

    @pytest.mark.asyncio
    async def test_embed_query(self):
        v = Vectorizer()
        emb = await v.embed_query("光的干涉")
        assert len(emb) == v.dim

    @pytest.mark.asyncio
    async def test_cache_hit(self):
        v = Vectorizer()
        c = FakeChunk("缓存测试内容")
        embs1 = await v.embed_chunks([c])
        embs2 = await v.embed_chunks([c])
        # 相同内容应返回相同向量
        assert embs1[0] == embs2[0]
        # 第二次应命中缓存
        assert v.cache_size >= 1

    @pytest.mark.asyncio
    async def test_deterministic_vector(self):
        v = Vectorizer()
        text = "确定性测试"
        v1 = v._fallback_vector(text)
        v2 = v._fallback_vector(text)
        # 相同文本 → 相同向量
        assert v1 == pytest.approx(v2, abs=1e-6)

    @pytest.mark.asyncio
    async def test_different_texts_different_vectors(self):
        v = Vectorizer()
        v1 = v._fallback_vector("AAAA")
        v2 = v._fallback_vector("BBBB")
        # 不同文本 → 不同向量
        assert v1 != v2

    @pytest.mark.asyncio
    async def test_normalized_vector(self):
        v = Vectorizer()
        emb = v._fallback_vector("归一化测试")
        import math
        norm = math.sqrt(sum(x * x for x in emb))
        assert norm == pytest.approx(1.0, abs=1e-4)

    @pytest.mark.asyncio
    async def test_vector_dimension(self):
        v = Vectorizer(dim=256)
        emb = v._fallback_vector("维度测试")
        assert len(emb) == 256

    @pytest.mark.asyncio
    async def test_clear_cache(self):
        v = Vectorizer()
        chunks = [FakeChunk("清缓存")]
        await v.embed_chunks(chunks)
        assert v.cache_size > 0

        v.clear_cache()
        assert v.cache_size == 0

    @pytest.mark.asyncio
    async def test_partial_cache(self):
        """部分命中缓存、部分新文本"""
        v = Vectorizer()
        c1 = FakeChunk("已缓存")
        c2 = FakeChunk("新文本")

        await v.embed_chunks([c1])  # 先缓存 c1
        embs = await v.embed_chunks([c1, c2])  # c1 命中，c2 新计算
        assert len(embs) == 2
        assert v.cache_size >= 1
