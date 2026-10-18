"""Raciocínio com IA para os agentes, com guarda-corpo.

Cada agente pergunta à IA pelo mesmo `AgentRuntimePort`, sem ferramentas (`allowed_tools=()`), pedindo
JSON num esquema. A resposta é validada; se a IA falhar, estourar cota ou responder fora do esquema, o
agente usa a regra de reserva. A IA nunca decide sozinha preço, total, restrição ou origem dos dados:
isso continua no código (planejador e auditor).
"""
from __future__ import annotations

from typing import Any

from .ports import RuntimeCall
from .registry import AgentContext

AI_TIMEOUT_S = 40.0


def _matches(value: Any, schema: dict[str, Any]) -> bool:
    kind = schema.get("type")
    kinds = kind if isinstance(kind, list) else [kind]
    checks = {"object": lambda v: isinstance(v, dict), "array": lambda v: isinstance(v, list),
              "string": lambda v: isinstance(v, str), "boolean": lambda v: isinstance(v, bool),
              "integer": lambda v: isinstance(v, int) and not isinstance(v, bool), "null": lambda v: v is None}
    if kind is not None and not any(checks.get(k, lambda v: True)(value) for k in kinds):
        return False
    if isinstance(value, dict):
        if any(k not in value for k in schema.get("required", [])):
            return False
        props = schema.get("properties", {})
        return all(_matches(value[k], props[k]) for k in props if k in value)
    if isinstance(value, list) and "items" in schema:
        return all(_matches(v, schema["items"]) for v in value)
    if "enum" in schema and value not in schema["enum"]:
        return False
    return True


def ask(ctx: AgentContext, agent_id: str, system: str, prompt: str, schema: dict[str, Any]) -> dict[str, Any] | None:
    """Pergunta à IA; devolve o JSON validado ou None (o agente usa a regra de reserva)."""
    outcome = ctx.runtime.run(RuntimeCall(
        agent_id=agent_id, task_id=ctx.task_id, session_id=ctx.session.session_id, system=system,
        prompt=prompt, output_schema=schema, allowed_tools=(), max_tool_calls=0, timeout_s=AI_TIMEOUT_S))
    ok = outcome.ok and isinstance(outcome.structured, dict) and _matches(outcome.structured, schema)
    provider = "demo" if any(t.provider == "demo" for t in outcome.tool_calls) else "internal"
    reason = {"quota": "cota da IA esgotada", "timeout": "IA demorou demais", "unavailable": "IA indisponível",
              "invalid_output": "resposta da IA fora do formato"}.get(outcome.error or "",
                                                                      "resposta da IA fora do formato")
    ctx.events.tool_activity(agent_id, f"ai_{ctx.task_id}", "raciocinio_ia", provider,
                             "succeeded" if ok else "failed", None,
                             "IA consultada" if ok else f"{reason}; regra de reserva usada")
    return outcome.structured if ok else None  # type: ignore[return-value]
