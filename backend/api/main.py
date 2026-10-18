"""Composição executável do backend.

Uso local, depois de iniciar o OpenCode Server configurado no projeto::

    uvicorn backend.api.main:app --reload

A memória padrão é deliberadamente a implementação efêmera de demonstração da
branch de agentes. Quando a memória persistente estiver disponível, o processo
de inicialização deve chamar ``build_application(memory=...)``.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI

from backend.integrations import OpenCodeAgentRuntime, OpenCodeSettings, SandboxLocation

from .app import create_app
from .services import build_agent_services, build_demo_agent_services
from .state import InMemoryBackendState


def build_application(
    *,
    runtime: Any | None = None,
    memory: Any | None = None,
    state: InMemoryBackendState | None = None,
) -> FastAPI:
    """Liga runtime, memória, agentes, eventos e endpoints HTTP/SSE."""

    backend_state = state or InMemoryBackendState()
    agent_runtime = runtime or OpenCodeAgentRuntime(
        OpenCodeSettings.from_env(),
        sandbox_location=SandboxLocation.from_env(),
    )
    if memory is None:
        services = build_demo_agent_services(
            runtime=agent_runtime,
            state=backend_state,
        )
    else:
        services = build_agent_services(
            runtime=agent_runtime,
            memory=memory,
            state=backend_state,
        )
    application = create_app(
        state=backend_state,
        message_dispatcher=services.dispatcher,
        agent_catalog=services.catalog,
    )
    application.state.agent_services = services
    return application


app = build_application()
