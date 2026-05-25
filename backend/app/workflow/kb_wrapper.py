"""KB wrapper for workflow runner (since vector_search is an instance method).

Provides two search modes:
  - vector_search()    — embedding-based semantic search (original)
  - agentic_search()    — LLM reasoning over knowledge tree (new)
"""

from app.modules.kb_module import get_kb
from app.workflow.kb_agent import agentic_search as _agentic_search


def vector_search(query: str, top_k: int = 3) -> list:
    """
    Module-level wrapper for KB vector_search (instance method).
    Used by workflow runner since YAML can't instantiate KB first.
    """
    kb = get_kb()
    return kb.vector_search(query, top_k=top_k)


def agentic_search(query: str, top_k: int = 3, **kwargs) -> list:
    """
    Module-level wrapper for KB agentic search (LLM reasoning over tree).

    Drop-in replacement for vector_search() in the YAML workflow.
    Falls back to keyword search if LLM is unavailable.

    Args:
        query: Search query string
        top_k: Number of results to return
        **kwargs: Passed to KBToolsAgent.retrieve() (e.g. blueprint_context)

    Returns:
        List of result dicts: {title, content, category, score, source}
    """
    return _agentic_search(query, top_k=top_k, **kwargs)