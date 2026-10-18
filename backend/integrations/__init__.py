"""Integrações externas do backend.

O módulo de agentes depende apenas de ``AgentRuntimePort``. Os componentes
expostos aqui são detalhes usados pela futura implementação concreta desse
contrato e não constituem uma segunda API entre módulos.
"""

from .agent_runtime import OpenCodeAgentRuntime
from .config import IFOOD_MCP_URL, OpenCodeSettings, SandboxLocation
from .errors import (
    IntegrationError,
    InvalidOutputError,
    QuotaError,
    RuntimeTimeoutError,
    UnavailableError,
)
from .offer_search import DemoOfferSearch, ToolExecution
from .opencode_client import OpenCodeClient, OpenCodeHealth, OpenCodeRunResult

__all__ = [
    "IFOOD_MCP_URL",
    "DemoOfferSearch",
    "IntegrationError",
    "InvalidOutputError",
    "OpenCodeClient",
    "OpenCodeAgentRuntime",
    "OpenCodeHealth",
    "OpenCodeRunResult",
    "OpenCodeSettings",
    "QuotaError",
    "RuntimeTimeoutError",
    "SandboxLocation",
    "ToolExecution",
    "UnavailableError",
]
