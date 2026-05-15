"""
Embedding 模块 - 文字 → 向量

功能：
- 调用远程 Embedding API 生成文字向量
- 支持多 provider：MiniMax（默认）、Ollama、OpenAI、火山引擎

依赖：
- requests（用于 HTTP 调用）
- numpy

配置（环境变量）：
- EMBEDDING_PROVIDER: MiniMax/Ollama/OpenAI/Volcengine（默认：MiniMax）
- AI_API_KEY: MiniMax API Key（包含 GroupId，格式：API_Key-GroupId）
- EMBEDDING_GROUP_ID: MiniMax GroupId（从 AI_API_KEY 解析则不需要）
- OLLAMA_BASE_URL: Ollama 服务地址（默认：http://localhost:11434）
- OPENAI_API_KEY: OpenAI API Key
- OPENAI_EMBEDDING_MODEL: OpenAI embedding 模型（默认：text-embedding-3-small）
- VOLCENGINE_API_KEY: 火山引擎 API Key
- VOLCENGINE_EMBEDDING_ENDPOINT: 火山引擎 endpoint
"""

import os
import re
import numpy as np
from typing import List, Optional


# ── Provider 配置 ─────────────────────────────────────────────

PROVIDER = os.environ.get("EMBEDDING_PROVIDER", "MiniMax").lower()

# MiniMax 配置
AI_API_KEY = os.environ.get("AI_API_KEY", "")
# AI_API_KEY 格式可能是 "API_Key-GroupId" 或只有 API Key
# 从中提取 GroupId
def _parse_minimax_group_id():
    if "-" in AI_API_KEY:
        parts = AI_API_KEY.split("-")
        # 格式：API_Key-GroupId，GroupId 通常在最后
        if len(parts) >= 2:
            return parts[-1]
    return os.environ.get("EMBEDDING_GROUP_ID", "")

MINIMAX_GROUP_ID = os.environ.get("EMBEDDING_GROUP_ID") or _parse_minimax_group_id()
MINIMAX_API_KEY = AI_API_KEY.split("-")[0] if AI_API_KEY else ""  # 只取 API Key 部分
MINIMAX_EMBEDDING_MODEL = os.environ.get("MINIMAX_EMBEDDING_MODEL", "embo-01")

# Ollama 配置
OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")

# OpenAI 配置
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
OPENAI_EMBEDDING_MODEL = os.environ.get("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")

# 火山引擎配置
VOLCENGINE_API_KEY = os.environ.get("VOLCENGINE_API_KEY", "")
VOLCENGINE_EMBEDDING_ENDPOINT = os.environ.get(
    "VOLCENGINE_EMBEDDING_ENDPOINT",
    "https://ark.cn-beijing.volces.com/api/v3/embeddings/text_embedding"
)


def _get_provider():
    """获取当前配置的 provider"""
    return PROVIDER


# ── MiniMax Provider ─────────────────────────────────────────────

def _minimax_embed_texts(texts: List[str]) -> np.ndarray:
    """调用 MiniMax embed-text API 生成 embedding"""
    import requests

    if not MINIMAX_API_KEY:
        raise ValueError("AI_API_KEY not set")
    if not MINIMAX_GROUP_ID:
        raise ValueError("GroupId not set. Set EMBEDDING_GROUP_ID or use format: API_KEY-GroupId in AI_API_KEY")

    embeddings = []
    url = "https://api.minimax.chat/v1/embeddings"
    headers = {
        "Authorization": f"Bearer {MINIMAX_API_KEY}",
        "Content-Type": "application/json",
        "GroupId": MINIMAX_GROUP_ID
    }

    for text in texts:
        resp = requests.post(
            url,
            headers=headers,
            json={
                "type": "embedding",
                "model": MINIMAX_EMBEDDING_MODEL,
                "texts": [text]
            },
            timeout=30
        )
        resp.raise_for_status()
        data = resp.json()
        embeddings.append(data["vectors"][0]["embedding"])

    return np.array(embeddings)


# ── Ollama Provider ─────────────────────────────────────────────

def _ollama_embed_texts(texts: List[str], model: str = "multilingual-e5-small") -> np.ndarray:
    """调用 Ollama 生成 embedding"""
    import requests

    embeddings = []
    url = f"{OLLAMA_BASE_URL}/api/embeddings"

    for text in texts:
        resp = requests.post(
            url,
            json={"model": model, "prompt": text},
            timeout=30
        )
        resp.raise_for_status()
        data = resp.json()
        embeddings.append(data["embedding"])

    return np.array(embeddings)


# ── OpenAI Provider ─────────────────────────────────────────────

def _openai_embed_texts(texts: List[str]) -> np.ndarray:
    """调用 OpenAI API 生成 embedding"""
    import requests

    if not OPENAI_API_KEY:
        raise ValueError("OPENAI_API_KEY not set")

    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "Content-Type": "application/json"
    }
    embeddings = []

    for text in texts:
        resp = requests.post(
            "https://api.openai.com/v1/embeddings",
            headers=headers,
            json={
                "input": text,
                "model": OPENAI_EMBEDDING_MODEL,
                "encoding_format": "float"
            },
            timeout=30
        )
        resp.raise_for_status()
        data = resp.json()
        embeddings.append(data["data"][0]["embedding"])

    return np.array(embeddings)


# ── 火山引擎 Provider ─────────────────────────────────────────

def _volcengine_embed_texts(texts: List[str]) -> np.ndarray:
    """调用火山引擎 API 生成 embedding"""
    import requests

    if not VOLCENGINE_API_KEY:
        raise ValueError("VOLCENGINE_API_KEY not set")

    embeddings = []

    for text in texts:
        # 火山引擎请求体格式
        payload = {
            "input": text,
        }
        headers = {
            "Authorization": f"Bearer {VOLCENGINE_API_KEY}",
            "Content-Type": "application/json"
        }

        resp = requests.post(
            VOLCENGINE_EMBEDDING_ENDPOINT,
            headers=headers,
            json=payload,
            timeout=30
        )
        resp.raise_for_status()
        data = resp.json()
        embeddings.append(data["data"][0]["embedding"])

    return np.array(embeddings)


# ── 统一入口函数 ─────────────────────────────────────────────

def embed_texts(texts: List[str], normalize: bool = True) -> np.ndarray:
    """将文字列表转为向量

    Args:
        texts: 文字列表
        normalize: 是否L2归一化（相似度计算时通常需要）

    Returns:
        numpy array, shape (n, embedding_dim)
    """
    if not texts:
        return np.array([])

    provider = _get_provider()

    if provider == "minimax":
        embeddings = _minimax_embed_texts(texts)
    elif provider == "openai":
        embeddings = _openai_embed_texts(texts)
    elif provider == "volcengine":
        embeddings = _volcengine_embed_texts(texts)
    elif provider == "ollama":
        embeddings = _ollama_embed_texts(texts)
    else:
        # 默认 MiniMax
        embeddings = _minimax_embed_texts(texts)

    # 归一化
    if normalize:
        norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
        embeddings = embeddings / (norms + 1e-8)

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
    import requests

    print(f"Testing embedding module (provider: {PROVIDER})...")

    # 检查 MiniMax 配置
    if PROVIDER == "minimax":
        print(f"MiniMax GroupId: {MINIMAX_GROUP_ID}")
        if not MINIMAX_API_KEY or not MINIMAX_GROUP_ID:
            print("[ERROR] AI_API_KEY and EMBEDDING_GROUP_ID must be set")
            sys.exit(1)

    # 检查 Ollama 连接
    if PROVIDER == "ollama":
        print(f"Ollama URL: {OLLAMA_BASE_URL}")
        try:
            resp = requests.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=5)
            if resp.status_code == 200:
                models = resp.json().get("models", [])
                print(f"Available models: {[m.get('name') for m in models]}")
            else:
                print(f"[WARN] Ollama status: {resp.status_code}")
        except Exception as e:
            print(f"[WARN] Cannot connect to Ollama: {e}")
            print("Make sure Ollama is running: ollama serve")
            sys.exit(1)

    texts = [
        "SUS304不锈钢的抗拉强度是多少",
        "CNC加工的工艺流程是什么",
        "SECC镀锌钢板的规格参数",
    ]

    try:
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
    except Exception as e:
        print(f"[ERROR] {e}")
        sys.exit(1)