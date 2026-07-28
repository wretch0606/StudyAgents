"""
答辩演示预缓存脚本

生成 5 个预设问答的检索缓存，供答辩当天网络故障时使用。

用法：python src/tests/fixtures/demo_queries.py
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from worker.ingestion.parsers.pdf import PDFParser
from worker.ingestion.parsers.ocr import MockOCRAdapter
from worker.ingestion.chunker import Chunker
from worker.retrieval.retriever import HybridRetriever


DEMO_QUESTIONS = [
    {
        "id": "demo-01",
        "query": "光的干涉条件是什么？",
        "type": "事实问答",
        "expected": "应返回第1页相干条件相关内容，sufficient=true",
    },
    {
        "id": "demo-02",
        "query": "杨氏双缝干涉实验中，相邻明条纹间距公式是什么？",
        "type": "公式问答",
        "expected": "应返回Δx=λD/d公式，sufficient=true",
    },
    {
        "id": "demo-03",
        "query": "比较等倾干涉和等厚干涉的区别",
        "type": "综合问答",
        "expected": "应返回第4页薄膜干涉相关内容",
    },
    {
        "id": "demo-04",
        "query": "什么是麦克斯韦方程组？",
        "type": "应拒答",
        "expected": "知识库无此内容，sufficient=false，reason=no_results",
    },
    {
        "id": "demo-05",
        "query": "四种典型干涉实验对比",
        "type": "表格问答",
        "expected": "应返回第3页表格内容",
    },
]


def generate_demo_cache():
    """生成演示缓存"""
    sample_pdf = Path(__file__).resolve().parent / "sample_lecture.pdf"
    if not sample_pdf.exists():
        print("❌ 样例 PDF 不存在，先运行 generate_sample_pdf.py")
        return

    # 1. 解析
    parser = PDFParser(ocr_engine=MockOCRAdapter())
    pages = parser.parse(str(sample_pdf), "demo-doc")

    # 2. 切块
    chunker = Chunker()
    chunks = chunker.chunk_document("demo-doc", pages)

    # 3. 索引
    import hashlib
    import struct
    import random
    retriever = HybridRetriever()

    class FakeChunk:
        def __init__(self, c):
            self.chunk_id = c.chunk_id
            self.content = c.content
            self.document_id = c.document_id
            self.content_hash = hashlib.sha256(c.content.encode()).hexdigest()
            self.page_from = c.page_from
            self.page_to = c.page_to
            self.question_no = c.question_no
            self.section_path = c.section_path
            self.year = c.year
            self.visibility = type("FakeEnum", (), {"value": c.visibility.value})
            self.material_type = type("FakeEnum", (), {"value": c.material_type.value})

    def pseudo_embed(text):
        digest = hashlib.sha256(text.encode()).digest()
        seeds = struct.unpack(">" + "I" * (len(digest) // 4), digest)
        rng = random.Random(seeds[0])
        vec = [rng.gauss(0, 1) for _ in range(768)]
        norm = (sum(x * x for x in vec)) ** 0.5
        return [x / norm for x in vec]

    embeddings = [pseudo_embed(c.content) for c in chunks]
    fake_chunks = [FakeChunk(c) for c in chunks]

    import asyncio
    asyncio.run(retriever.index_chunks(fake_chunks, embeddings))
    asyncio.run(retriever.set_doc_names({"demo-doc": "光学讲义（演示用）.pdf"}))

    # 4. 预检索并缓存
    cache_file = Path(__file__).resolve().parent / "demo_cache.json"
    results = []

    for dq in DEMO_QUESTIONS:
        result = asyncio.run(retriever.retrieve(
            dq["query"],
            query_embedding=pseudo_embed(dq["query"]),
        ))
        entry = {
            "id": dq["id"],
            "query": dq["query"],
            "type": dq["type"],
            "expected": dq["expected"],
            "sufficient": result.sufficient,
            "reason": result.reason,
            "source_count": len(result.source_refs),
            "sources": [
                {
                    "doc": ref.document_name,
                    "page": ref.page_number,
                    "excerpt": ref.excerpt[:150] + "..." if len(ref.excerpt) > 150 else ref.excerpt,
                    "score": round(ref.score, 4),
                }
                for ref in result.source_refs
            ],
            "elapsed_ms": result.elapsed_ms,
        }
        results.append(entry)
        status = "✅" if result.sufficient else "⬜"
        print(f"  {status} {dq['id']}: {dq['query']} → {len(result.source_refs)} 条证据 ({result.elapsed_ms:.0f}ms)")

    # 5. 保存
    output = {
        "generated_at": __import__("datetime").datetime.now().isoformat(),
        "document": "光学讲义（演示用）",
        "total_chunks": len(chunks),
        "total_pages": len(pages),
        "queries": results,
    }

    cache_file.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n✅ 演示缓存已生成: {cache_file}")
    print(f"   包含 {len(results)} 个预设问答")


if __name__ == "__main__":
    generate_demo_cache()
