"""Montagem do serviço de agentes. É o ponto de entrada que a API deve chamar."""
from __future__ import annotations

from .auditor import Auditor
from .discount import DiscountSpecialist
from .orchestrator import Orchestrator
from .planner import Planner
from .ports import AgentRuntimePort, EventSink, MemoryPort
from .registry import AgentRegistry
from .researcher import Researcher
from .strategist import SalesStrategist


def build_registry() -> AgentRegistry:
    registry = AgentRegistry()
    for agent in (Researcher(), Planner(), Auditor(), SalesStrategist(), DiscountSpecialist()):
        registry.register(agent)
    return registry


def build_orchestrator(runtime: AgentRuntimePort, memory: MemoryPort, sink: EventSink,
                       registry: AgentRegistry | None = None) -> Orchestrator:
    return Orchestrator(registry or build_registry(), runtime, memory, sink)
