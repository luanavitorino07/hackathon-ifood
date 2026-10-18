"""Montagem do serviço de agentes. É o ponto de entrada que a API deve chamar."""
from __future__ import annotations

from .auditor import Auditor
from .discount import DiscountSpecialist
from .orchestrator import Orchestrator
from .planner import Planner
from .ports import AgentRuntimePort, EventSink, KnowledgePort, MemoryPort
from .registry import AgentRegistry
from .researcher import Researcher
from .strategist import SalesStrategist


def build_registry() -> AgentRegistry:
    registry = AgentRegistry()
    for agent in (Researcher(), Planner(), Auditor(), SalesStrategist(), DiscountSpecialist()):
        registry.register(agent)
    return registry


_DEFAULT = object()


def default_knowledge() -> KnowledgePort | None:
    """Base de conhecimento padrão (RAG de backend/memory); None se o módulo não estiver disponível."""
    try:
        from backend.memory import default_knowledge_base
    except ImportError:
        return None
    return default_knowledge_base()


def build_orchestrator(runtime: AgentRuntimePort, memory: MemoryPort, sink: EventSink,
                       registry: AgentRegistry | None = None,
                       knowledge: KnowledgePort | None | object = _DEFAULT) -> Orchestrator:
    kb = default_knowledge() if knowledge is _DEFAULT else knowledge
    return Orchestrator(registry or build_registry(), runtime, memory, sink, kb)  # type: ignore[arg-type]
