"""Composição executável do backend.

Uso local (APP_RUNTIME_MODE=demo por padrão; catálogo fictício, sem rede)::

    uvicorn backend.api.main:app --host 127.0.0.1 --port 8000

APP_RUNTIME_MODE=real seleciona OpenCode e exige seu servidor configurado.
X-Demo-Role: admin só habilita o gestor no modo demo. O modo real ainda usa
identidade local de comprador, salvo injeção de um IdentityResolver autenticado.

A memória padrão é deliberadamente operacional e efêmera, implementada na API.
Quando a memória persistente estiver disponível, o processo
de inicialização deve chamar ``build_application(memory=...)``.
"""

from __future__ import annotations

import os
from importlib import import_module
from typing import Any

from fastapi import FastAPI

from backend.integrations import OpenCodeAgentRuntime, OpenCodeSettings, SandboxLocation

from .app import create_app
from .models import Mode
from .services import (
    DemoIdentityResolver,
    IdentityResolver,
    build_agent_services,
    build_demo_agent_services,
)
from .state import InMemoryBackendState


def build_application(
    *,
    runtime: Any | None = None,
    memory: Any | None = None,
    state: InMemoryBackendState | None = None,
    runtime_mode: str | None = None,
    identity_resolver: IdentityResolver | None = None,
) -> FastAPI:
    """Liga runtime, memória, agentes, eventos e endpoints HTTP/SSE."""

    mode = Mode(runtime_mode if runtime_mode is not None else os.getenv("APP_RUNTIME_MODE", "demo"))
    backend_state = state or InMemoryBackendState()
    if runtime is not None:
        agent_runtime = runtime
    elif mode == Mode.DEMO:
        agent_runtime = import_module("backend.agents.demo.runtime").DemoCatalogRuntime()
    else:
        agent_runtime = OpenCodeAgentRuntime(
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
        memory=services.memory,
        session_mode=mode,
        identity_resolver=(
            identity_resolver
            if identity_resolver is not None
            else DemoIdentityResolver()
            if mode == Mode.DEMO
            else None
        ),
    )
    application.state.agent_services = services
    return application


app = build_application()
