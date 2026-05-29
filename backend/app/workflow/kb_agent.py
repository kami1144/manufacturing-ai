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

<<<<<<< Updated upstream
        llm_response = await self.ai.chat(prompt)
=======
        # Step 3: Run searches in parallel, merge results via RRF
        all_results = []
        try:
            tasks = [self._search_single(q, tree_data, blueprint_context, top_k) for q in all_searches]
            search_results = await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), timeout=60.0)
        except Exception:
            search_results = []
>>>>>>> Stashed changes

        # Step 3: Parse entry IDs from LLM response
        entry_ids = self._parse_entry_ids_from_response(llm_response)

        if not entry_ids:
            return self._fallback_keyword_search(query, top_k)

        # Step 4: Fetch content
        content_result = self.get_entries_content(entry_ids[:top_k])
        if not content_result.success:
            return self._fallback_keyword_search(query, top_k)

        # Step 5: Build results (Strategy A: trust LLM, no content verification)
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

<<<<<<< Updated upstream
=======
    async def _generate_query_variants(self, query: str) -> list[str]:
        """Generate semantically diverse query variants to improve recall."""
        prompt = (
            f"原始问题：{query}\n"
            "请生成3个语义等价但表达不同的查询变体，覆盖不同角度：\n"
            "1. 技术术语版（用专业缩写或日文术语）\n"
            "2. 描述现象版（描述具体现象而非抽象指标名）\n"
            "3. 中英混合版\n"
            "只输出3行，每行一个查询变体，不要编号或其他说明。"
        )
        try:
            response = await asyncio.wait_for(self.ai.chat(prompt), timeout=5.0)
            variants = [v.strip() for v in response.split('\n') if v.strip() and len(v.strip()) > 5]
            return variants[:3]
        except Exception:
            return []

    async def _search_single(
        self,
        query: str,
        tree_data: dict,
        blueprint_context: Optional[dict],
        top_k: int,
    ) -> list[tuple[str, str, str]]:
        """Run a single query variant through LLM retrieval."""
        prompt = self._build_retrieval_prompt(query, tree_data, blueprint_context, top_k)
        try:
            llm_response = await asyncio.wait_for(self.ai.chat(prompt), timeout=30.0)
        except Exception:
            return []
        entry_ids = self._parse_entry_ids_from_response(llm_response)
        if not entry_ids:
            return []
        content_result = self.get_entries_content(entry_ids[:top_k])
        if not content_result.success:
            return []
        return [
            (entry.get("id", ""), entry.get("content", ""), entry.get("title", ""))
            for entry in content_result.data
        ]

>>>>>>> Stashed changes
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

        # Pre-sort: entries with query keywords in title appear first (higher relevance)
        query_lower = query.lower()

        def title_relevance(node):
            title = node.get("title", "").lower()
            summary = node.get("summary", "").lower()
            score = 0
            # Exact query phrase in title
            if query_lower in title:
                score += 100
            # Individual query words in title
            for word in query_lower.split():
                if len(word) >= 2:
                    if word in title:
                        score += 10
                    if word in summary:
                        score += 5
            return score

        sorted_nodes = sorted(leaf_nodes, key=title_relevance, reverse=True)

        # Limit to top 40 entries to avoid token overflow (68 entries is too many for small models)
        display_nodes = sorted_nodes[:40]
        omitted = len(sorted_nodes) - len(display_nodes)

        leaf_list = "\n".join(
            f"  - [{node['id']}] {node['title']}: {node.get('summary', '')[:150]}"
            for node in display_nodes
        )

        if omitted > 0:
            entry_note = f"\n（共 {len(sorted_nodes)} 条记录，显示前 {len(display_nodes)} 条与查询最相关的条目）"
        else:
            entry_note = ""

        prompt = (
            "你是制造业知识库检索助手。请根据用户查询，从以下知识库条目中识别最相关的条目。\n"
            "每个条目格式：[node_id] 标题: 一句话摘要\n"
            + context_str
            + f"用户查询：{query}{entry_note}\n\n"
            "知识库条目：\n" + leaf_list + "\n\n"
            "请从上述条目中选择与查询最相关的 " + str(top_k) + " 个，回复格式如下（只回复这一行，不要其他文字）：\n"
            "RETRIEVE: id1, id2, id3"
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

    def _verify_content_match(self, entries: list, query: str) -> list:
        """
        Verify that a sufficient fraction of query keywords actually appear in content.
        LLM reasoning over titles+summaries can hallucinate relevance.

        Rules:
        - Extract meaningful keywords (>=2 chars, exclude particles)
        - Exclude company names (they appear in headers but don't mean content relevance)
        - Require >= 50% of core keywords to appear in content (strict majority)
        - Fallback to returning entries if no keywords extracted
        """
        import re
        query_lower = query.lower()

        # Company name patterns to exclude — these appear in doc headers, not body
        company_exclude = {
            "島津製作所", " Shimadzu", "岛津", "丰田", "トヨタ", "日本マシナリー",
            "山田製作所", "三菱", "横河", " Hitachi", "NEC", "Panasonic"
        }

        stop = {"の", "は", "が", "を", "に", "で", "と", "です", "ます", "か",
                 "実施", "された", "についての", "何", "どんな", "どの", "什么", "哪些",
                 "哪個", "哪个", "什麼", "什么"}
        sep = r'[\s\?。、，。！＼？（）()「」『』【】、,．.：:""''《》〈〉]'
        raw_keywords = [k for k in re.split(sep, query_lower) if k and len(k) >= 2 and k not in stop]

        # Filter out company names and very short matches
        core_keywords = [k for k in raw_keywords if k not in company_exclude and not any(
            c in k for c in company_exclude)]

        if not core_keywords:
            return entries  # Nothing to verify against

        # Require majority of core keywords to appear in content
        threshold = max(1, len(core_keywords) // 2)
        verified = []
        for entry in entries:
            content_lower = entry.get("content", "").lower()
            hits = sum(1 for kw in core_keywords if kw in content_lower)
            if hits >= threshold:
                verified.append(entry)

        return verified

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
        running_loop = asyncio.get_running_loop()
    except RuntimeError:
        # No running loop — create our own
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        results = loop.run_until_complete(
            agent.retrieve(query, top_k, kwargs.get("blueprint_context"))
        )
        loop.close()
    else:
        # Already inside async context — create a dedicated loop in a worker thread
        # to run the async coroutine without nesting event loops
        import threading
        result_holder = []

        def _run_async():
            new_loop = asyncio.new_event_loop()
            asyncio.set_event_loop(new_loop)
            try:
                result_holder.append(
                    new_loop.run_until_complete(
                        agent.retrieve(query, top_k, kwargs.get("blueprint_context"))
                    )
                )
            finally:
                new_loop.close()

        thread = threading.Thread(target=_run_async)
        thread.start()
        thread.join()
        results = result_holder[0] if result_holder else agent._fallback_keyword_search(query, top_k)

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