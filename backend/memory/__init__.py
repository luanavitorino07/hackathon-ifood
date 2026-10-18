"""Memória do projeto: RAG mínimo sobre documentos comerciais e persistência do estado por sessão."""
from __future__ import annotations

import os
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
    """Uma por processo (em memória): o histórico vale entre atendimentos enquanto a API estiver no ar.

    Já vem com os clientes fictícios da apresentação (`demo_seed`), salvo `APP_DEMO_CUSTOMERS=0`."""
    memory = SQLiteCustomerMemory()
    if os.getenv("APP_DEMO_CUSTOMERS", "1") != "0":
        from .demo_seed import seed_demo_customers
        seed_demo_customers(memory)
    return memory
