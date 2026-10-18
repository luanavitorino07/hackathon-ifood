"""Montagem do serviço de agentes. É o ponto de entrada que a API deve chamar."""
from __future__ import annotations

from .auditor import Auditor
from .curator import Curator
from .customer_memory_agent import CustomerMemoryAgent
from .discount import DiscountSpecialist
from .orchestrator import Orchestrator
from .planner import Planner
from .ports import AgentRuntimePort, CustomerMemoryPort, EventSink, KnowledgePort, MemoryPort
from .registry import AgentRegistry
from .researcher import Researcher
from .strategist import SalesStrategist


def build_registry() -> AgentRegistry:
    registry = AgentRegistry()
    for agent in (Researcher(), Curator(), Planner(), Auditor(), SalesStrategist(), DiscountSpecialist(),
                  CustomerMemoryAgent()):
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


def default_customers() -> CustomerMemoryPort | None:
    """Memória do cliente padrão (backend/memory); None se o módulo não estiver disponível."""
    try:
        from backend.memory import default_customer_memory
    except ImportError:
        return None
    return default_customer_memory()


def build_orchestrator(runtime: AgentRuntimePort, memory: MemoryPort, sink: EventSink,
                       registry: AgentRegistry | None = None,
                       knowledge: KnowledgePort | None | object = _DEFAULT,
                       customers: CustomerMemoryPort | None | object = _DEFAULT) -> Orchestrator:
    kb = default_knowledge() if knowledge is _DEFAULT else knowledge
    cm = default_customers() if customers is _DEFAULT else customers
    return Orchestrator(registry or build_registry(), runtime, memory, sink, kb, cm)  # type: ignore[arg-type]
