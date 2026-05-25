"""
KB Agent - Agentic Retrieval over Knowledge Tree

The KB Agent uses an LLM to reason over the knowledge tree structure,
navigate to relevant nodes, and retrieve the most appropriate content.

Usage:
  agent = KBToolsAgent(tree)
  results = await agent.retrieve("SUS304材质报价", top_k=3)
"""

import json
import re
import asyncio
from typing import Optional, Any, List
from dataclasses import dataclass

from app.modules.ai_module import AIManufacturing


# ── Agent Tools ─────────────────────────────────────────────────────────────────

@dataclass
class KBToolResult:
    """Result from calling a KB tool."""
    tool_name: str
    success: bool
    data: Any
    error: str = ""


class KBToolsAgent:
    """
    Agent that retrieves knowledge from a KnowledgeTree using LLM reasoning.

    Three tools:
      1. get_tree_structure()    → full tree (for LLM to navigate)
      2. get_category_overview() → category → entries mapping (lightweight)
      3. get_entries_content()    → full content of specific entry IDs
    """

    def __init__(self, tree, ai_client: Optional["AIManufacturing"] = None):
        self.tree = tree
        self.ai = ai_client or AIManufacturing()

    def get_tree_structure(self) -> KBToolResult:
        try:
            data = self.tree.get_tree_structure()
            return KBToolResult(tool_name="get_tree_structure", success=True, data=data)
        except Exception as e:
            return KBToolResult(tool_name="get_tree_structure", success=False, data=None, error=str(e))

    def get_category_overview(self) -> KBToolResult:
        try:
            data = self.tree.get_category_map()
            return KBToolResult(tool_name="get_category_overview", success=True, data=data)
        except Exception as e:
            return KBToolResult(tool_name="get_category_overview", success=False, data=None, error=str(e))

    def get_entries_content(self, entry_ids: list) -> KBToolResult:
        try:
            # Strip 'leaf_' prefix since tree.entries stores bare UUIDs
            normalized_ids = [eid.replace("leaf_", "") for eid in entry_ids]
            entries = [self.tree.entries[eid] for eid in normalized_ids if eid in self.tree.entries]
            return KBToolResult(tool_name="get_entries_content", success=True, data=entries)
        except Exception as e:
            return KBToolResult(tool_name="get_entries_content", success=False, data=None, error=str(e))

    async def retrieve(
        self,
        query: str,
        top_k: int = 3,
        blueprint_context: Optional[dict] = None,
    ) -> list:
        """
        Agentic retrieval: use LLM to reason over tree and find relevant entries.

        Args:
            query: User's natural language query
            top_k: Maximum number of entries to return
            blueprint_context: Optional blueprint features for context enrichment

        Returns:
            List of result dicts with entry content and match reasoning.
        """
        # Step 1: Get tree structure
        tree_result = self.get_tree_structure()
        if not tree_result.success:
            return self._fallback_keyword_search(query, top_k)

        tree_data = tree_result.data

        # Step 2: Build prompt and call LLM
        prompt = self._build_retrieval_prompt(query, tree_data, blueprint_context, top_k)

        llm_response = await self.ai.chat(prompt)

        # Step 3: Parse entry IDs from LLM response
        entry_ids = self._parse_entry_ids_from_response(llm_response)

        if not entry_ids:
            return self._fallback_keyword_search(query, top_k)

        # Step 4: Fetch content
        content_result = self.get_entries_content(entry_ids[:top_k])
        if not content_result.success:
            return self._fallback_keyword_search(query, top_k)

        # Step 5: Build results
        results = []
        for entry in content_result.data:
            results.append({
                "title": entry.get("title", ""),
                "content": entry.get("content", ""),
                "category": entry.get("category", ""),
                "source": entry.get("source", ""),
                "score": 1.0,
                "match_reason": "LLM reasoning: relevant to '" + query + "'",
            })
        return results

    def _build_retrieval_prompt(
        self,
        query: str,
        tree_data: dict,
        blueprint_context: Optional[dict],
        top_k: int,
    ) -> str:
        context_parts = []
        if blueprint_context:
            material = blueprint_context.get("material", "未知")
            quantity = blueprint_context.get("quantity", "未知")
            process = blueprint_context.get("process_type", "未知")
            context_parts.append(f"- 材质：{material}")
            context_parts.append(f"- 数量：{quantity}")
            context_parts.append(f"- 工艺：{process}")

        context_str = ""
        if context_parts:
            context_str = "当前图纸上下文：\n" + "\n".join(context_parts) + "\n"

        # Build flat list of all leaf nodes for LLM to reference
        leaf_nodes = self._collect_leaf_nodes(tree_data)

        leaf_list = "\n".join(
            f"  - {node['title']} (id: {node['id']})"
            for node in leaf_nodes
        )

        prompt = (
            "你是制造业知识库检索助手。请根据用户查询，从以下知识库条目中识别最相关的 ID。\n\n"
            + context_str
            + "用户查询：" + query + "\n\n"
            "知识库条目：\n" + leaf_list + "\n\n"
            "请按以下格式回复（只回复这一行，不要其他文字）：\n"
            "RETRIEVE: id1, id2, id3\n\n"
            "找到与查询最相关的条目，最多返回 " + str(top_k) + " 个，按相关性排序。"
        )
        return prompt

    def _collect_leaf_nodes(self, tree_node: dict) -> list:
        """Recursively collect all leaf nodes."""
        nodes = []
        if tree_node.get("type") == "leaf":
            nodes.append(tree_node)
        for child_id in tree_node.get("children", []):
            child = self._find_node_flat(child_id)
            if child:
                nodes.extend(self._collect_leaf_nodes(child))
        return nodes

    def _find_node_flat(self, node_id: str) -> Optional[dict]:
        """Find a node by ID in the flat node store."""
        node = self.tree.nodes.get(node_id)
        return node.to_dict() if node else None

    def _parse_entry_ids_from_response(self, response: str) -> list:
        """Parse entry IDs from LLM response."""
        match = re.search(r'RETRIEVE:\s*([\w\-,\s]+)', response, re.IGNORECASE)
        if match:
            ids_str = match.group(1)
            return [i.strip() for i in ids_str.split(",") if i.strip()]

        # Fallback: look for UUID-like patterns
        fallback_ids = re.findall(r'[\w]{8}-[\w]{4}', response)
        return fallback_ids[:5]

    def _fallback_keyword_search(self, query: str, top_k: int) -> list:
        """When LLM reasoning fails, fall back to keyword search."""
        from app.workflow.kb_tree import SearchResult
        results = self.tree.keyword_search(query, top_k)
        return [
            {
                "title": r.title,
                "content": r.content,
                "score": r.score,
                "match_reason": r.match_reason,
                "source": r.source,
                "category": self.tree.entries.get(r.entry_id, {}).get("category", ""),
            }
            for r in results
        ]


# ── Sync Wrapper for YAML Workflow ──────────────────────────────────────────────

def agentic_search(query: str, top_k: int = 3, **kwargs) -> list:
    """
    Synchronous wrapper for agentic KB search.
    Used by kb_wrapper.py as a drop-in replacement for vector_search.
    """
    from app.modules.kb_module import get_kb

    kb = get_kb()
    from app.workflow.kb_tree import KnowledgeTree
    tree = KnowledgeTree.from_kb(kb)
    agent = KBToolsAgent(tree)

    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    results = loop.run_until_complete(
        agent.retrieve(query, top_k, kwargs.get("blueprint_context"))
    )

    # Normalize to match existing interface
    return [
        {
            "title": r.get("title", ""),
            "content": r.get("content", ""),
            "category": r.get("category", ""),
            "score": r.get("score", 0.0),
            "source": r.get("source", ""),
            "match_reason": r.get("match_reason", ""),
        }
        for r in results
    ]


from app.workflow.kb_tree import KnowledgeTree, SearchResult

__all__ = [
    "KBToolsAgent",
    "KnowledgeTree",
    "SearchResult",
    "agentic_search",
]