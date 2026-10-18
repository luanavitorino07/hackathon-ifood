"""Contrato comum dos agentes e registro. Novos agentes entram só por `register`."""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from .events import EventEmitter
from .models import AgentResult, SessionContext, WorkingState
from .ports import AgentRuntimePort, KnowledgePort


class AgentDefinition:
    """Espelha `AgentDefinition` do contrato (§15.2)."""

    def __init__(self, agent_id: str, name: str, role: str, description: str,
                 capabilities: list[str], enabled: bool = True) -> None:
        self.agent_id, self.name, self.role = agent_id, name, role
        self.description, self.capabilities, self.enabled = description, capabilities, enabled

    def to_dict(self) -> dict[str, object]:
        return {"agent_id": self.agent_id, "name": self.name, "role": self.role,
                "description": self.description, "capabilities": list(self.capabilities),
                "enabled": self.enabled}


class AgentContext:
    """O que um agente enxerga ao executar."""

    def __init__(self, session: SessionContext, state: WorkingState, runtime: AgentRuntimePort,
                 events: EventEmitter, task_id: str, knowledge: KnowledgePort | None = None) -> None:
        self.session, self.state, self.runtime = session, state, runtime
        self.events, self.task_id, self.knowledge = events, task_id, knowledge


@runtime_checkable
class Agent(Protocol):
    definition: AgentDefinition
    order: int  # posição na esteira; menor roda primeiro

    def should_activate(self, session: SessionContext, state: WorkingState) -> bool: ...

    def run(self, ctx: AgentContext) -> AgentResult: ...


class AgentRegistry:
    def __init__(self) -> None:
        self._agents: dict[str, Agent] = {}

    def register(self, agent: Agent) -> None:
        agent_id = agent.definition.agent_id
        if agent_id in self._agents:
            raise ValueError(f"agente duplicado: {agent_id}")
        self._agents[agent_id] = agent

    def catalog(self) -> list[dict[str, object]]:
        return [a.definition.to_dict() for a in self._agents.values()]

    def select(self, session: SessionContext, state: WorkingState) -> list[Agent]:
        """Agentes habilitados que pedem ativação, na ordem da esteira."""
        chosen = [a for a in self._agents.values()
                  if a.definition.enabled and a.should_activate(session, state)]
        return sorted(chosen, key=lambda a: a.order)
