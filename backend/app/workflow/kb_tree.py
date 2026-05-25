"""
KB Tree Module - Hierarchical Knowledge Tree with Agentic Retrieval

Inspired by VectifyAI PageIndex: instead of flat embedding vectors + similarity,
build a hierarchical tree index and let the LLM reason over the structure.

Architecture:
  entries (flat KB) → build_tree() → tree (hierarchical by category/topic)
  → KB Agent (LLM reasoning) → retrieve relevant content

Tree Node Schema:
  {
    "id": "node_xxx",
    "type": "root" | "category" | "section" | "leaf",
    "title": "节点标题",
    "summary": "一句话描述本节点内容（用于 LLM 推理导航）",
    "tokens": 1200,  # 本节点内容的 token 估算
    "children": [child_node_ids],  # 仅 category/section 有
    "entry_ids": ["entry_xxx"],    # 映射到的 KB 条目
    "start_index": 0,              # 原始内容起始位置（用于追溯）
    "end_index": 500,
  }

Leaf Node (content node):
  {
    "id": "node_xxx",
    "type": "leaf",
    "title": "KBEntry.title",
    "summary": "从 entry.content 提取的一句话摘要",
    "tokens": 800,
    "children": [],  # 无子节点
    "entry_ids": ["entry_xxx"],
    "start_index": 0,
    "end_index": len(content),
    "content_preview": "...",  # 前200字，用于快速预览
  }

Usage:
  tree = KnowledgeTree.from_kb(kb)
  tree.build()

  # Agentic retrieval (LLM reasons over structure)
  agent = KBToolsAgent(tree)
  results = agent.retrieve("SUS304材质报价")

  # Fallback: keyword search over entries
  results = tree.keyword_search("SUS304")
"""

from __future__ import annotations

import uuid
import re
import math
from dataclasses import dataclass, field
from typing import Optional, Any
from collections import Counter


# ── Data Classes ────────────────────────────────────────────────────────────────

@dataclass
class TreeNode:
    """A node in the knowledge tree."""
    id: str
    type: str  # "root" | "category" | "section" | "leaf"
    title: str
    summary: str = ""        # One-sentence description for LLM navigation
    tokens: int = 0          # Estimated token count of this node's content
    children: list[str] = field(default_factory=list)   # Child node IDs
    entry_ids: list[str] = field(default_factory=list)   # Mapped KB entries
    start_index: int = 0
    end_index: int = 0
    content_preview: str = ""  # First 200 chars for quick preview

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "type": self.type,
            "title": self.title,
            "summary": self.summary,
            "tokens": self.tokens,
            "children": self.children,
            "entry_ids": self.entry_ids,
            "start_index": self.start_index,
            "end_index": self.end_index,
            "content_preview": self.content_preview,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "TreeNode":
        return cls(
            id=d["id"],
            type=d["type"],
            title=d["title"],
            summary=d.get("summary", ""),
            tokens=d.get("tokens", 0),
            children=d.get("children", []),
            entry_ids=d.get("entry_ids", []),
            start_index=d.get("start_index", 0),
            end_index=d.get("end_index", 0),
            content_preview=d.get("content_preview", ""),
        )


@dataclass
class SearchResult:
    """A retrieved result from the knowledge tree."""
    entry_id: str
    title: str
    content: str
    score: float
    match_reason: str = ""  # Why this result matched (for transparency)
    source: str = ""


# ── Token Counter ────────────────────────────────────────────────────────────────

def estimate_tokens(text: str) -> int:
    """
    Rough token estimation.
    Chinese/ Japanese: ~1.5 chars/token
    English: ~4 chars/token
    Mixed: use average.
    """
    if not text:
        return 0
    cjk_chars = len(re.findall(r'[\u4e00-\u9fff\u3040-\u30ff]', text))
    total_chars = len(text)
    non_cjk = total_chars - cjk_chars
    return math.ceil(cjk_chars / 1.5) + math.ceil(non_cjk / 4)


# ── Knowledge Tree ───────────────────────────────────────────────────────────────

class KnowledgeTree:
    """
    Hierarchical knowledge tree built from flat KB entries.

    Tree structure:
      root
        ├── category: material
        │     ├── section: 不锈钢
        │     │     └── leaf: SUS304规格
        │     └── section: 铝合金
        │           └── leaf: AL5052规格
        ├── category: process
        │     ├── leaf: CNC铣削工艺
        │     └── leaf: 钣金加工工艺
        └── ...

    Retrieval is two-mode:
      1. Agentic (default): LLM reasons over tree structure
      2. Keyword fallback: regex match over entries (for when LLM is unavailable)
    """

    def __init__(self):
        self.root_id: str = "root"
        self.nodes: dict[str, TreeNode] = {}
        self.entries: dict[str, dict] = {}   # entry_id → KBEntry dict
        self.built: bool = False

    # ── Build Tree ──────────────────────────────────────────────────────────────

    def build(self, entries: list[dict]) -> None:
        """
        Build the hierarchical tree from flat KB entries.

        Structure rules:
          - root
          - category: by KBEntry.category field
          - section: by topic/keyword clustering within a category
          - leaf: individual KBEntry
        """
        self.entries = {e["id"]: e for e in entries}
        self.nodes = {}

        # Create root
        self.nodes[self.root_id] = TreeNode(
            id=self.root_id,
            type="root",
            title="制造业知识库",
            summary="包含材质、工艺、表面处理、公差、产品质量等制造业知识",
        )

        # Group entries by category
        by_category: dict[str, list[dict]] = {}
        for e in entries:
            cat = e.get("category", "other")
            by_category.setdefault(cat, []).append(e)

        # Build category nodes
        for cat, cat_entries in by_category.items():
            cat_node = self._build_category_node(cat, cat_entries)
            self.nodes[cat_node.id] = cat_node
            self.nodes[self.root_id].children.append(cat_node.id)

        self.built = True

    def _build_category_node(self, category: str, entries: list[dict]) -> TreeNode:
        """Build a category node with section/leaf children."""
        cat_label = {
            "material": "材质规格",
            "process": "加工工艺",
            "surface": "表面处理",
            "tolerance": "公差质量",
            "product": "产品规格",
            "other": "其他",
        }.get(category, category)

        cat_node_id = f"cat_{category}"
        cat_children = []

        # Cluster entries into sections by keyword similarity
        sections = self._cluster_into_sections(entries)

        for section_entries in sections:
            section_node = self._build_section_node(section_entries)
            self.nodes[section_node.id] = section_node
            cat_children.append(section_node.id)

        total_tokens = sum(self._estimate_entry_tokens(e) for e in entries)
        summaries = [e.get("title", "") for e in entries[:3]]

        return TreeNode(
            id=cat_node_id,
            type="category",
            title=cat_label,
            summary=f"包含 {len(entries)} 个{cat_label}知识条目：{', '.join(summaries)}",
            tokens=total_tokens,
            children=cat_children,
            entry_ids=[e["id"] for e in entries],
        )

    def _build_section_node(self, entries: list[dict]) -> TreeNode:
        """Build a section node containing leaf children."""
        section_id = f"sec_{uuid.uuid4().hex[:8]}"
        leaf_ids = []
        total_tokens = 0

        for e in entries:
            leaf_node = self._build_leaf_node(e)
            self.nodes[leaf_node.id] = leaf_node
            leaf_ids.append(leaf_node.id)
            total_tokens += leaf_node.tokens

        first_title = entries[0].get("title", "") if entries else ""
        keywords = self._extract_section_keywords(entries)

        return TreeNode(
            id=section_id,
            type="section",
            title=keywords[0] if keywords else first_title,
            summary=f"包含 {len(entries)} 个相关条目：{', '.join(e.get('title', '')[:20] for e in entries[:2])}",
            tokens=total_tokens,
            children=leaf_ids,
            entry_ids=[e["id"] for e in entries],
        )

    def _build_leaf_node(self, entry: dict) -> TreeNode:
        """Build a leaf node from a single KB entry."""
        content = entry.get("content", "")
        preview = content[:200] if content else ""

        return TreeNode(
            id=f"leaf_{entry['id']}",
            type="leaf",
            title=entry.get("title", ""),
            summary=self._summarize_entry(entry),
            tokens=self._estimate_entry_tokens(entry),
            children=[],
            entry_ids=[entry["id"]],
            start_index=0,
            end_index=len(content),
            content_preview=preview,
        )

    def _cluster_into_sections(self, entries: list[dict]) -> list[list[dict]]:
        """
        Cluster entries into sections by keyword similarity.
        Simple implementation: group by first meaningful keyword.
        """
        if len(entries) <= 3:
            return [entries]

        # Group by first keyword or category sub-tag
        groups: dict[str, list[dict]] = {}
        for e in entries:
            keywords = e.get("keywords", [])
            if keywords:
                # Use first 2 keywords as cluster key
                key = "|".join(sorted(keywords[:2]))
            else:
                key = "default"
            groups.setdefault(key, []).append(e)

        return list(groups.values())

    def _extract_section_keywords(self, entries: list[dict]) -> list[str]:
        """Extract representative keywords for a section."""
        all_kw = []
        for e in entries:
            all_kw.extend(e.get("keywords", []))
        counter = Counter(all_kw)
        return [kw for kw, _ in counter.most_common(3)]

    def _estimate_entry_tokens(self, entry: dict) -> int:
        text = f"{entry.get('title', '')} {entry.get('content', '')}"
        return estimate_tokens(text)

    def _summarize_entry(self, entry: dict) -> str:
        """Generate a one-sentence summary from entry content."""
        content = entry.get("content", "")
        if not content:
            return entry.get("title", "")

        # Take first sentence or first 100 chars
        sentences = re.split(r'[。\n]', content)
        first = sentences[0].strip() if sentences else ""
        if len(first) > 100:
            first = first[:100] + "..."
        return first if first else entry.get("title", "")

    # ── Agentic Retrieval ────────────────────────────────────────────────────────

    def get_tree_structure(self) -> dict:
        """
        Return the full tree structure (without entry content).
        Used by KB Agent to navigate and reason.
        """
        def serialize_node(node_id: str) -> dict:
            node = self.nodes.get(node_id)
            if not node:
                return {}
            return {
                "id": node.id,
                "type": node.type,
                "title": node.title,
                "summary": node.summary,
                "tokens": node.tokens,
                "child_count": len(node.children),
                "children": node.children if node.type != "leaf" else [],
            }
        return serialize_node(self.root_id)

    def get_category_map(self) -> dict[str, list[dict]]:
        """Return all categories and their entry IDs — lightweight overview."""
        result = {}
        for node_id, node in self.nodes.items():
            if node.type == "category":
                result[node.title] = [
                    {"id": eid, "title": self.entries.get(eid, {}).get("title", "")}
                    for eid in node.entry_ids
                ]
        return result

    def get_entry_content(self, entry_id: str) -> Optional[dict]:
        """Get full content of a specific entry by ID."""
        return self.entries.get(entry_id)

    def get_entries_by_ids(self, entry_ids: list[str]) -> list[dict]:
        """Batch get entries by IDs."""
        return [self.entries[eid] for eid in entry_ids if eid in self.entries]

    def get_node_children(self, node_id: str) -> list[dict]:
        """Get direct children of a node (for agent navigation)."""
        node = self.nodes.get(node_id)
        if not node:
            return []
        return [self.nodes[cid].to_dict() for cid in node.children if cid in self.nodes]

    # ── Keyword Search Fallback ──────────────────────────────────────────────────

    def keyword_search(self, query: str, top_k: int = 5) -> list[SearchResult]:
        """
        Fallback keyword search over all entries.
        Used when LLM reasoning is unavailable or as baseline comparison.
        """
        query_lower = query.lower().strip()
        clean_pattern = re.compile(r'[^\w\u4e00-\u9fff]+')
        query_clean = clean_pattern.sub('', query_lower)

        scored = []
        for entry_id, entry in self.entries.items():
            score = self._keyword_score(query_lower, query_clean, entry)
            if score > 0:
                scored.append(SearchResult(
                    entry_id=entry_id,
                    title=entry.get("title", ""),
                    content=entry.get("content", ""),
                    score=score,
                    match_reason=self._match_reason(query_lower, entry),
                    source=entry.get("source", ""),
                ))

        scored.sort(key=lambda x: x.score, reverse=True)
        return scored[:top_k]

    def _keyword_score(self, query_lower: str, query_clean: str, entry: dict) -> float:
        score = 0.0
        title_lower = entry.get("title", "").lower()
        content_lower = entry.get("content", "").lower()
        keywords = entry.get("keywords", [])

        if query_lower in title_lower:
            score += 30
        if query_lower in content_lower:
            score += 15
        for kw in keywords:
            if kw.lower() in query_lower:
                score += 10
            elif query_lower in kw.lower():
                score += 8

        q_chars = set(query_clean)
        title_chars = set(re.sub(r'[^\w\u4e00-\u9fff]', '', title_lower))
        char_overlap = len(q_chars & title_chars) / max(len(q_chars), 1)
        score += char_overlap * 5

        return score

    def _match_reason(self, query: str, entry: dict) -> str:
        title = entry.get("title", "")
        if query.lower() in title.lower():
            return f"关键词命中标题：{title}"
        keywords = entry.get("keywords", [])
        matched = [kw for kw in keywords if kw.lower() in query.lower()]
        if matched:
            return f"关键词匹配：{', '.join(matched[:3])}"
        return "内容相关性"

    # ── Tree Stats ─────────────────────────────────────────────────────────────

    def stats(self) -> dict:
        """Return tree statistics."""
        by_type = Counter(n.type for n in self.nodes.values())
        return {
            "total_nodes": len(self.nodes),
            "total_entries": len(self.entries),
            "by_type": dict(by_type),
            "built": self.built,
        }

    # ── Serialization ──────────────────────────────────────────────────────────

    def to_dict(self) -> dict:
        return {
            "root_id": self.root_id,
            "nodes": {nid: n.to_dict() for nid, n in self.nodes.items()},
            "entries": self.entries,
            "built": self.built,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "KnowledgeTree":
        tree = cls()
        tree.root_id = d.get("root_id", "root")
        tree.nodes = {nid: TreeNode.from_dict(nd) for nid, nd in d.get("nodes", {}).items()}
        tree.entries = d.get("entries", {})
        tree.built = d.get("built", False)
        return tree

    # ── Factory ─────────────────────────────────────────────────────────────────

    @classmethod
    def from_kb(cls, kb_instance) -> "KnowledgeTree":
        """
        Build a KnowledgeTree from a KnowledgeBase instance.

        Args:
            kb_instance: KnowledgeBase with ._entries dict of KBEntry objects
        """
        tree = cls()
        entries = []
        for eid, entry in kb_instance._entries.items():
            entries.append({
                "id": eid,
                "title": entry.title,
                "content": entry.content,
                "category": entry.category,
                "keywords": entry.keywords,
                "source": entry.source,
            })
        tree.build(entries)
        return tree