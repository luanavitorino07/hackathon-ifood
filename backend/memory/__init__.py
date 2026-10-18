"""Memória do projeto: RAG mínimo sobre documentos comerciais e persistência do estado por sessão."""
from __future__ import annotations

from functools import lru_cache

from .customer_memory import SQLiteCustomerMemory
from .knowledge import MarkdownKnowledgeBase
from .sqlite_memory import SQLiteMemory

__all__ = ["MarkdownKnowledgeBase", "SQLiteCustomerMemory", "SQLiteMemory", "default_customer_memory",
           "default_knowledge_base"]


@lru_cache(maxsize=1)
def default_knowledge_base() -> MarkdownKnowledgeBase:
    return MarkdownKnowledgeBase()


@lru_cache(maxsize=1)
def default_customer_memory() -> SQLiteCustomerMemory:
    """Uma por processo (em memória): o histórico vale entre atendimentos enquanto a API estiver no ar."""
    return SQLiteCustomerMemory()
