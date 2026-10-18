"""Memória do projeto: RAG mínimo sobre documentos comerciais e persistência do estado por sessão."""
from __future__ import annotations

from functools import lru_cache

from .knowledge import MarkdownKnowledgeBase
from .sqlite_memory import SQLiteMemory

__all__ = ["MarkdownKnowledgeBase", "SQLiteMemory", "default_knowledge_base"]


@lru_cache(maxsize=1)
def default_knowledge_base() -> MarkdownKnowledgeBase:
    return MarkdownKnowledgeBase()
