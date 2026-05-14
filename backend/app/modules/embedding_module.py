"""
Embedding 模块 - 文字 → 向量

功能：
- 调用 Sentence-Transformers 生成文字向量
- 支持多语言（日语/中文/英语）
- 提供批量编码接口

依赖：sentence-transformers
"""

import numpy as np
from typing import List, Optional


# 全局模型实例（懒加载）
_model = None


def get_embedding_model():
    """获取或加载 Sentence-Transformers 模型"""
    global _model
    if _model is None:
        print("[INFO] Loading Sentence-Transformers model...")
        from sentence_transformers import SentenceTransformer
        # 多语言模型，支持中日英
        # paraphrase-multilingual-MiniLM-L12-v2: 384维，较小较快
        # intfloat/multilingual-e5-small: 384维，效果更好
        _model = SentenceTransformer("intfloat/multilingual-e5-small")
        print("[INFO] Model loaded.")
    return _model


def embed_texts(texts: List[str], normalize: bool = True) -> np.ndarray:
    """将文字列表转为向量

    Args:
        texts: 文字列表
        normalize: 是否L2归一化（相似度计算时通常需要）

    Returns:
        numpy array, shape (n, embedding_dim)
    """
    model = get_embedding_model()
    embeddings = model.encode(texts, normalize_embeddings=normalize)
    return embeddings


def embed_text(text: str, normalize: bool = True) -> np.ndarray:
    """单条文字转向量"""
    return embed_texts([text], normalize=normalize)[0]


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """计算两个向量的余弦相似度"""
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-8))


def search_by_similarity(
    query_text: str,
    corpus_texts: List[str],
    corpus_embeddings: np.ndarray,
    top_k: int = 5,
    score_threshold: float = 0.0,
) -> List[dict]:
    """向量相似度搜索

    Args:
        query_text: 查询文字
        corpus_texts: 语料库文字列表
        corpus_embeddings: 语料库对应的向量 (n, dim)
        top_k: 返回前k条
        score_threshold: 最低相似度阈值

    Returns:
        [{"text": ..., "score": ..., "index": ...}, ...]
    """
    query_emb = embed_text(query_text)
    scores = np.dot(corpus_embeddings, query_emb).tolist()

    results = []
    for i, score in enumerate(scores):
        if score >= score_threshold:
            results.append({
                "text": corpus_texts[i],
                "score": score,
                "index": i,
            })

    results.sort(key=lambda x: x["score"], reverse=True)
    return results[:top_k]


# ── CLI 入口 ─────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    print("Testing embedding module...")

    texts = [
        "SUS304不锈钢的抗拉强度是多少",
        "CNC加工的工艺流程是什么",
        "SECC镀锌钢板的规格参数",
    ]

    embeddings = embed_texts(texts)
    print(f"Generated {len(embeddings)} embeddings, shape: {embeddings[0].shape}")
    print(f"Sample vector (first 5 dims): {embeddings[0][:5]}")

    # 测试相似度
    q = "不锈钢材质的技术参数"
    q_emb = embed_text(q)
    scores = [cosine_similarity(q_emb, e) for e in embeddings]
    print(f"\nQuery: '{q}'")
    for i, score in enumerate(scores):
        print(f"  Score with '{texts[i]}': {score:.4f}")
