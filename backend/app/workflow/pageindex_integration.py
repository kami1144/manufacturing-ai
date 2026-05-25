"""
PageIndex 集成模块 - PDF 蓝图解析 → KnowledgeTree 入库

使用 PageIndex 替代 blueprint_parser 的手动 regex 解析，
从 PDF 生成 hierarchical tree，再转为 KB 条目。

核心流程：
  PDF bytes → page_index(pdf) → structure (with start/end indices)
           → add_node_text() → fill text content
           → to_kb_entries() → KnowledgeTree.from_kb() 可消费的 entries

依赖：
  - pageindex 包（来自 /tmp/pageindex_repo，需安装 litellm 依赖）
  - kb_module.py 的 KnowledgeBase
"""

from __future__ import annotations

import sys
import os
from typing import Optional

# ── Hermes .env 加载（必须最先，在 pageindex import 之前）──────────────────────
# MiniMax API Key 在 ~/.hermes/.env，不在项目 .env
_hermes_env_path = os.path.expanduser("~/.hermes/.env")
if os.path.exists(_hermes_env_path):
    from dotenv import load_dotenv
    load_dotenv(_hermes_env_path)

# 确保 pageindex 能读到正确的 key（pageindex/utils.py 在 import 时就初始化了 _MINIMAX_API_KEY）
os.environ.setdefault(
    "MINIMAX_API_KEY",
    os.environ.get("MINIMAX_API_KEY") or os.environ.get("MINIMAX_CN_API_KEY") or ""
)

# ── PageIndex 路径注入（必须最先）────────────────────────────────────────────
_pageindex_path = "/tmp/pageindex_repo"
if os.path.isdir(_pageindex_path) and _pageindex_path not in sys.path:
    sys.path.insert(0, _pageindex_path)

# ── 验证 PageIndex 的 llm_completion 已 patched 为 MiniMax ──────────────────
# pageindex/utils.py 已被直接修改（见该文件的 # MINIMAX_PATCHED 标记）
# 确保 httpx 可用
try:
    import httpx  # noqa: F401
except ImportError:
    raise RuntimeError("httpx required for PageIndex MiniMax integration")


# ── 类型定义 ──────────────────────────────────────────────────────────────────

class PageIndexResult:
    """PageIndex 返回结果包装器"""
    def __init__(self, doc_name: str, structure: list, pdf_path: str):
        self.doc_name = doc_name
        self.structure = structure  # list of tree nodes
        self.pdf_path = pdf_path

    def to_kb_entries(self, category: str = "blueprint") -> list[dict]:
        """
        将 PageIndex tree 转换为 KB 条目格式。

        每 个 leaf node → 一个 KBEntry:
          {
            "id": str,
            "title": str,           # node title
            "content": str,          # text content (from add_node_text)
            "category": str,         # KB category
            "keywords": list[str],   # auto-extracted from title
            "source": str,            # PDF path
            "metadata": {
              "node_type": "leaf",
              "start_page": int,
              "end_page": int,
              "doc_name": str,
            }
          }
        """
        import uuid
        import re

        entries = []

        def extract_keywords(title: str) -> list[str]:
            """从标题提取关键词"""
            cleaned = re.sub(r'[^\w\s\u4e00-\u9fff\-]', ' ', title)
            words = [w.strip() for w in cleaned.split() if len(w.strip()) >= 2]
            return words[:5]

        def node_to_entry(node: dict, parent_category: str) -> Optional[dict]:
            """递归将 tree node 转为 KB entry（只处理 leaf）"""
            node_type = node.get("type", "")
            children = node.get("nodes", []) or node.get("children", [])

            # Leaf node → 生成 KB entry
            if node_type == "leaf" or (not children and node.get("text")):
                entry_id = f"pi_{uuid.uuid4().hex[:12]}"
                title = node.get("title", "")
                text = node.get("text", "") or node.get("content", "")

                if not text:
                    return None

                return {
                    "id": entry_id,
                    "title": title,
                    "content": text,
                    "category": parent_category,
                    "keywords": extract_keywords(title),
                    "source": self.doc_name,
                    "metadata": {
                        "node_type": "leaf",
                        "start_index": node.get("start_index", 0),
                        "end_index": node.get("end_index", 0),
                        "doc_name": self.doc_name,
                        "pdf_path": self.pdf_path,
                    }
                }

            # 非 leaf 节点：递归处理子节点
            if children:
                for child in children:
                    child_entry = node_to_entry(child, parent_category)
                    if child_entry:
                        entries.append(child_entry)

            return None

        for node in self.structure:
            node_to_entry(node, category)

        return entries

    def get_tree_summary(self) -> dict:
        """返回树结构摘要（不含文本，用于日志）"""
        def count_nodes(nodes: list) -> dict:
            counts = {"leaf": 0, "section": 0, "category": 0, "total": 0}
            for n in nodes:
                t = n.get("type", "unknown")
                if t in counts:
                    counts[t] += 1
                counts["total"] += 1
                children = n.get("nodes", []) or n.get("children", [])
                if children:
                    child_counts = count_nodes(children)
                    for k, v in child_counts.items():
                        counts[k] += v
            return counts

        return {
            "doc_name": self.doc_name,
            "pdf_path": self.pdf_path,
            "node_counts": count_nodes(self.structure),
        }


# ── 核心函数 ──────────────────────────────────────────────────────────────────

async def index_pdf(
    pdf_path: str,
    category: str = "blueprint",
    model: Optional[str] = None,
    if_add_node_text: str = "yes",
) -> PageIndexResult:
    """
    PDF 文件 → PageIndex tree → 填充文本 → KB entries 格式

    Args:
        pdf_path: PDF 文件路径（本地路径）
        category: KB category，默认为 "blueprint"
        model: LLM 模型（默认使用 PageIndex 内置配置，已 patch 为 MiniMax）
        if_add_node_text: 是否为每个 node 填充文本内容

    Returns:
        PageIndexResult: 包含 doc_name, structure, to_kb_entries() 方法
    """
    from pageindex.utils import get_page_tokens, add_node_text

    # 1. 用 PageIndex 解析 PDF 结构
    try:
        pdf_pages = get_page_tokens(pdf_path, model=model, pdf_parser="PyMuPDF")
    except Exception as e:
        print(f"[WARN] PyMuPDF failed, falling back to PyPDF2: {e}")
        pdf_pages = get_page_tokens(pdf_path, model=model, pdf_parser="PyPDF2")

    # 2. 用 PageIndex 的无 TOC 流程处理已有页面文本
    try:
        from pageindex.page_index import process_no_toc
        import logging
        _logger = logging.getLogger("pageindex")
        structure = process_no_toc(pdf_pages, start_index=1, model=model, logger=_logger)
    except Exception as e:
        print(f"[WARN] process_no_toc failed: {e}")
        structure = []

    doc_name = os.path.basename(pdf_path)

    # 3. 填充文本内容（if_add_node_text="yes" 时才手动填充）
    # 注意：PageIndex 内置在 process_no_toc 内部会填充 text，这里是额外保险
    if if_add_node_text == "yes":
        try:
            add_node_text(structure, pdf_pages)
        except Exception as e:
            print(f"[WARN] Failed to add node text: {e}")

    return PageIndexResult(
        doc_name=doc_name,
        structure=structure,
        pdf_path=pdf_path,
    )


def index_pdf_sync(
    pdf_path: str,
    category: str = "blueprint",
    model: Optional[str] = None,
) -> PageIndexResult:
    """
    同步版本（用于非 async 上下文，如 blueprint_parser）
    内部用 asyncio.run 执行异步 page_index

    注意：model 参数传给 PageIndex，但 PageIndex 内置的 llm_completion
    已经 patch 为使用 MiniMax（见 pageindex/utils.py 的 # MINIMAX_PATCHED）。
    不需要额外配置。
    """
    import asyncio

    try:
        loop = asyncio.get_event_loop()
        is_new_loop = False
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        is_new_loop = False

    try:
        result = loop.run_until_complete(
            index_pdf(pdf_path, category, model)
        )
    finally:
        if is_new_loop:
            loop.close()

    return result


# ── 快捷入口 ──────────────────────────────────────────────────────────────────

def pdf_to_kb_entries(
    pdf_path: str,
    category: str = "blueprint",
    model: Optional[str] = None,
) -> list[dict]:
    """
    一行 API：PDF → KB entries
    用于直接替换 blueprint_parser 的 regex 逻辑
    """
    result = index_pdf_sync(pdf_path, category, model)
    return result.to_kb_entries(category)