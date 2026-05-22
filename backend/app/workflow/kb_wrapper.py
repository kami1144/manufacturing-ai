"""KB wrapper for workflow runner (since vector_search is an instance method)."""
from app.modules.kb_module import get_kb


def vector_search(query: str, top_k: int = 3) -> list:
    """
    Module-level wrapper for KB vector_search (instance method).
    Used by workflow runner since YAML can't instantiate KB first.
    """
    kb = get_kb()
    return kb.vector_search(query, top_k=top_k)
