"""
关键词索引器 — jieba 分词 + 统计

生产模式写入 PostgreSQL tsvector 列；
测试/无数据库时使用内存倒排索引。
"""

import logging
from typing import Optional

from apps.worker.retrieval.keyword_search import tokenize_chinese, InMemoryKeywordBackend

logger = logging.getLogger(__name__)


class KeywordIndexer:
    """
    关键词索引器。

    负责：
      1. 对 Chunk 内容做 jieba 分词
      2. 写入搜索后端（内存 / pg tsvector）
      3. 支持增量添加和批量删除
    """

    def __init__(self, backend: Optional[InMemoryKeywordBackend] = None):
        self.backend = backend or InMemoryKeywordBackend()

    async def index_chunks(self, chunks: list) -> int:
        """
        批量索引知识块的关键词。

        Returns:
            成功索引的块数量
        """
        count = 0
        for chunk in chunks:
            metadata = {
                "chunk_id": chunk.chunk_id,
                "document_id": chunk.document_id,
                "page_from": chunk.page_from,
                "section_path": " > ".join(chunk.section_path) if chunk.section_path else "",
                "visibility": chunk.visibility.value if hasattr(chunk.visibility, 'value') else str(chunk.visibility),
                "material_type": chunk.material_type.value if hasattr(chunk.material_type, 'value') else str(chunk.material_type),
                "year": chunk.year if hasattr(chunk, 'year') and chunk.year else None,
            }
            await self.backend.add(chunk.chunk_id, chunk.content, metadata)
            count += 1

        logger.info(f"关键词索引完成: {count} 块")
        return count

    async def remove_document(self, chunk_ids: list[str]):
        """批量删除文档的关键词索引"""
        for cid in chunk_ids:
            await self.backend.remove(cid)
        logger.info(f"关键词索引删除: {len(chunk_ids)} 块")

    def build_search_query(self, query: str) -> str:
        """
        构建搜索用的分词串。
        pg 模式返回 `token1 & token2 & ...`，
        内存模式由后端自行处理。
        """
        tokens = tokenize_chinese(query)
        return " & ".join(tokens)

    @staticmethod
    def tokenize(text: str) -> list[str]:
        """分词便捷方法"""
        return tokenize_chinese(text)

    def __len__(self):
        return len(self.backend)
