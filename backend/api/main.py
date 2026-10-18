"""Composição executável do backend.

Uso local (APP_RUNTIME_MODE=demo por padrão; catálogo fictício, sem rede)::

    uvicorn backend.api.main:app --host 127.0.0.1 --port 8000

APP_RUNTIME_MODE=real seleciona OpenCode e exige seu servidor configurado.
APP_ALLOW_LOCAL_DEMO_ADMIN=1 libera explicitamente o gestor fictício no modo real,
somente em localhost. Não substitui autenticação de produção.

A memória operacional usa SQLite por padrão. Ela não persiste o cadastro HTTP,
as projeções, o histórico SSE nem a idempotência da API.
"""

from __future__ import annotations

import os
from importlib import import_module
from pathlib import Path
from typing import Any

from fastapi import FastAPI

from backend.integrations import OpenCodeAgentRuntime, OpenCodeSettings, SandboxLocation

from .app import create_app
from .models import Mode
from .services import (
    DemoIdentityResolver,
    IdentityResolver,
    build_agent_services,
)
from .state import InMemoryBackendState


def build_application(
    *,
    runtime: Any | None = None,
    memory: Any | None = None,
    state: InMemoryBackendState | None = None,
    runtime_mode: str | None = None,
    identity_resolver: IdentityResolver | None = None,
    memory_backend: str | None = None,
    allow_local_demo_admin: bool | None = None,
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
    selected_memory, owns_memory = _select_memory(memory, memory_backend)
    services = build_agent_services(
        runtime=agent_runtime,
        memory=selected_memory,
        state=backend_state,
    )
    catalog_lookup = getattr(agent_runtime, "recommendation_warnings", None)
    if callable(catalog_lookup):
        services.event_sink.catalog_warning_lookup = catalog_lookup
    application = create_app(
        state=backend_state,
        message_dispatcher=services.dispatcher,
        agent_catalog=services.catalog,
        memory=services.memory,
        session_mode=mode,
        identity_resolver=(
            identity_resolver
            if identity_resolver is not None
            else DemoIdentityResolver(
                mode=mode.value,
                allow_real_admin=(
                    allow_local_demo_admin
                    if allow_local_demo_admin is not None
                    else _env_flag("APP_ALLOW_LOCAL_DEMO_ADMIN", default=False)
                ),
            )
        ),
    )
    application.state.agent_services = services
    application.state.memory_backend = type(selected_memory).__name__
    if owns_memory and callable(getattr(selected_memory, "close", None)):
        application.router.add_event_handler("shutdown", selected_memory.close)
    return application


def _select_memory(memory: Any | None, memory_backend: str | None) -> tuple[Any, bool]:
    if memory is not None:
        return memory, False
    backend = (memory_backend or os.getenv("APP_MEMORY_BACKEND", "sqlite")).strip().casefold()
    if backend == "ephemeral":
        memory_module = import_module("backend.api.session_memory")
        return memory_module.EphemeralSessionMemory(), True
    if backend != "sqlite":
        raise ValueError("APP_MEMORY_BACKEND precisa ser 'sqlite' ou 'ephemeral'")
    sqlite_module = import_module("backend.memory")
    path = Path(
        os.getenv(
            "APP_MEMORY_PATH",
            str(Path(__file__).resolve().parent / ".local" / "session-memory.sqlite3"),
        )
    )
    if str(path) != ":memory:":
        path.parent.mkdir(parents=True, exist_ok=True)
    return sqlite_module.SQLiteMemory(path), True


def _env_flag(name: str, *, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    normalized = value.strip().casefold()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} precisa ser um booleano")


app = build_application()
