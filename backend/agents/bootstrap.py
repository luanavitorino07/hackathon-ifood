"""Montagem do serviço de agentes. É o ponto de entrada que a API deve chamar."""
from __future__ import annotations

from .auditor import Auditor
from .orchestrator import Orchestrator
from .planner import Planner
from .ports import AgentRuntimePort, EventSink, MemoryPort
from .registry import AgentRegistry
from .researcher import Researcher


def build_registry() -> AgentRegistry:
    registry = AgentRegistry()
    for agent in (Researcher(), Planner(), Auditor()):
        registry.register(agent)
    return registry


def build_orchestrator(runtime: AgentRuntimePort, memory: MemoryPort, sink: EventSink,
                       registry: AgentRegistry | None = None) -> Orchestrator:
    return Orchestrator(registry or build_registry(), runtime, memory, sink)
