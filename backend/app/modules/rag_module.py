"""
RAG 模块 - 独立可复用

功能：
- 文档分块（chunking）
- Embedding 生成
- 向量存储（Qdrant）
- 相似度检索

依赖：qdrant-client（可选）
"""

from typing import Optional, List
from dataclasses import dataclass
import uuid
import math
import hashlib


@dataclass
class Chunk:
    id: str
    text: str
    metadata: dict


@dataclass
class SearchResult:
    chunk: Chunk
    score: float


class RAGPipeline:
    def __init__(
        self,
        collection_name: str = "manufacturing_kb",
        vector_dim: int = 1024,  # BGE-m3 dim
        qdrant_url: str = "localhost",
        qdrant_port: int = 6333
    ):
        self.collection_name = collection_name
        self.vector_dim = vector_dim
        self.qdrant_url = qdrant_url
        self.qdrant_port = qdrant_port
        self._client = None

    @property
    def client(self):
        """懒加载 Qdrant 客户端"""
        if self._client is None:
            try:
                from qdrant_client import QdrantClient
                self._client = QdrantClient(self.qdrant_url, port=self.qdrant_port)
            except ImportError:
                raise RuntimeError(
                    "qdrant-client not installed. Install with: pip install qdrant-client"
                )
        return self._client

    def chunk_text(
        self,
        text: str,
        chunk_size: int = 500,
        overlap: int = 50
    ) -> List[Chunk]:
        """
        文本分块

        Args:
            text: 原始文本
            chunk_size: 每块字符数
            overlap: 块间重叠字符数

        Returns:
            list[Chunk]
        """
        chunks = []
        start = 0
        text_len = len(text)

        while start < text_len:
            end = start + chunk_size
            chunk_text = text[start:end]

            chunks.append(Chunk(
                id=str(uuid.uuid4()),
                text=chunk_text.strip(),
                metadata={"start": start, "end": end}
            ))

            start += chunk_size - overlap

        return chunks

    def create_collection(self, recreate: bool = False):
        """创建 Collection"""
        from qdrant_client.models import Distance, VectorParams

        if recreate:
            try:
                self.client.delete_collection(self.collection_name)
            except Exception:
                pass

        self.client.create_collection(
            collection_name=self.collection_name,
            vectors_config=VectorParams(
                size=self.vector_dim,
                distance=Distance.COSINE
            )
        )

    def add_chunks(self, chunks: List[Chunk], texts: List[str]):
        """
        将 chunks 的 text 转为 embedding 并存储

        Args:
            chunks: 分块结果
            texts: 对应的原始文本列表
        """
        from qdrant_client.models import PointStruct

        # 模拟 embedding（实际应用中用 sentence-transformers 或 API）
        def mock_embed(text: str) -> List[float]:
            h = hashlib.sha256(text.encode()).digest()
            # 归一化
            magnitude = math.sqrt(sum(x * x for x in h[:self.vector_dim]))
            return [b / magnitude if magnitude > 0 else 0 for b in h[:self.vector_dim]]

        points = []
        for chunk, text in zip(chunks, texts):
            embedding = mock_embed(text)
            points.append(PointStruct(
                id=chunk.id,
                vector=embedding,
                payload={"text": text, "chunk_id": chunk.id}
            ))

        self.client.upsert(
            collection_name=self.collection_name,
            points=points
        )

    def search(
        self,
        query: str,
        top_k: int = 5,
        filter_query: Optional[dict] = None
    ) -> List[SearchResult]:
        """
        检索相似文档

        Args:
            query: 查询文本
            top_k: 返回数量
            filter_query: 过滤条件

        Returns:
            list[SearchResult]
        """
        # 模拟 embedding
        h = hashlib.sha256(query.encode()).digest()
        magnitude = math.sqrt(sum(x * x for x in h[:self.vector_dim]))
        query_vector = [b / magnitude if magnitude > 0 else 0 for b in h[:self.vector_dim]]

        results = self.client.search(
            collection_name=self.collection_name,
            query_vector=query_vector,
            limit=top_k
        )

        search_results = []
        for r in results:
            chunk = Chunk(
                id=r.payload.get("chunk_id", ""),
                text=r.payload.get("text", ""),
                metadata={}
            )
            search_results.append(SearchResult(chunk=chunk, score=r.score))

        return search_results


# ── 工厂知识库预设 ──────────────────────────────────────

MANUFACTURING_TEMPLATES = {
    "cnc_machining": {
        "description": "CNC加工工艺知识库",
        "keywords": ["CNC", "铣削", "车削", "钻孔", "公差"],
        "sop": "1. 来料检验\n2. 编程\n3. 装夹\n4. 粗加工\n5. 精加工\n6. 检测\n7. 出货"
    },
    "sheet_metal": {
        "description": "钣金工艺知识库",
        "keywords": ["折弯", "冲压", "激光切割", "焊接", "表面处理"],
        "sop": "1. 来料检验\n2. 切割\n3. 折弯\n4. 冲孔\n5. 焊接\n6. 表面处理\n7. 检验"
    },
    "quality_control": {
        "description": "质量管理知识库",
        "keywords": ["检测", "SPC", "CPK", "不良率", "改善"],
        "sop": "1. IQC来料检验\n2. PQC过程检验\n3. OQC出货检验\n4. 异常处理\n5. 改善报告"
    }
}


def get_template_kb(template_name: str) -> dict:
    """获取预设知识库模板"""
    return MANUFACTURING_TEMPLATES.get(template_name, {})


# ── CLI 入口 ────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    # 测试用
    print("RAG Module - Manufacturing Knowledge Base")
    print("=" * 50)
    print("\nAvailable templates:")
    for name, template in MANUFACTURING_TEMPLATES.items():
        print(f"  - {name}: {template['description']}")

    print("\nUsage:")
    print("  from rag_module import RAGPipeline, get_template_kb")
    print("  pipeline = RAGPipeline(collection_name='my_kb')")
    print("  template = get_template_kb('cnc_machining')")
