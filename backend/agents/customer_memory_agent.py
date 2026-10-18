"""Agente da Memória do cliente: responde quando outro agente pergunta sobre o cliente.

Não decide nada: devolve fatos do histórico autorizado (pedidos feitos ao bot) e das preferências
declaradas, com a origem. A conversa aparece no escritório como agent_message pedido/resposta.
"""
from __future__ import annotations

from typing import Any

from .commercial import DEMO_PURCHASE_HISTORY
from .models import AgentResult, SessionContext, WorkingState, restriction_label
from .registry import AgentContext, AgentDefinition

MEMORY_ID = "customer_memory"


def _brl(cents: int | None) -> str:
    return "?" if cents is None else f"R$ {cents // 100},{cents % 100:02d}"


def customer_facts(state: WorkingState, session: SessionContext | None = None) -> dict[str, Any]:
    p, c = state.customer_profile, state.constraints
    facts: dict[str, Any] = {"preferencias_declaradas": list(c.preferences), "restricoes": list(c.dietary)}
    if p is not None:
        facts.update({
            "atendimentos_anteriores": p.requests,
            "pratos_favoritos": [f"{d} ({n}x)" for d, n in p.favorite_dishes],
            "ultimo_pedido": " ".join(p.last_terms) or None,
            "orcamento_tipico_por_pessoa": _brl(p.typical_budget_per_person_cents)
            if p.typical_budget_per_person_cents else None,
        })
        if p.declared_restrictions:
            facts["restricoes_do_cadastro"] = [restriction_label(r) for r in p.declared_restrictions]
        if p.declared_preferences:
            facts["preferencias_do_cadastro"] = list(p.declared_preferences)
        if p.strategy_stats:
            facts["estrategias_com_este_cliente"] = "; ".join(
                f"{k}: aceitou {a} de {n}" for k, n, a in p.strategy_stats)
    if (session is not None and session.mode == "demo" and not (p and p.favorite_dishes)
            and DEMO_PURCHASE_HISTORY.get(session.client_id or "")):
        facts["historico_demo"] = DEMO_PURCHASE_HISTORY[session.client_id or ""]["description"]
    return facts


def summary(facts: dict[str, Any]) -> str:
    parts = []
    if facts.get("pratos_favoritos"):
        parts.append("favoritos: " + ", ".join(facts["pratos_favoritos"]))
    if facts.get("ultimo_pedido"):
        parts.append(f"último pedido: {facts['ultimo_pedido']}")
    if facts.get("orcamento_tipico_por_pessoa"):
        parts.append(f"costuma gastar {facts['orcamento_tipico_por_pessoa']} por pessoa")
    if facts.get("historico_demo"):
        parts.append(facts["historico_demo"])
    if facts.get("restricoes_do_cadastro"):
        parts.append("cadastro: " + ", ".join(facts["restricoes_do_cadastro"]))
    if facts.get("preferencias_do_cadastro"):
        parts.append("gosta de " + ", ".join(facts["preferencias_do_cadastro"]))
    if facts.get("estrategias_com_este_cliente"):
        parts.append("estratégias com ele: " + facts["estrategias_com_este_cliente"])
    if facts.get("preferencias_declaradas"):
        parts.append("preferências declaradas: " + ", ".join(facts["preferencias_declaradas"]))
    return "; ".join(parts) or "sem histórico nem preferências registradas"


def consult(ctx: AgentContext, asker: str, question: str) -> dict[str, Any]:
    """`asker` pergunta à Memória; a pergunta e a resposta vão para o escritório."""
    ctx.events.agent_message(asker, MEMORY_ID, ctx.task_id, "request", question)
    facts = customer_facts(ctx.state, ctx.session)
    ctx.events.agent_message(MEMORY_ID, asker, ctx.task_id, "proposal", "Cliente: " + summary(facts))
    return facts


class CustomerMemoryAgent:
    """Consultado sob demanda pelos outros agentes; não roda na esteira."""

    definition = AgentDefinition(
        MEMORY_ID, "Memória do cliente", "Histórico e preferências",
        "Responde aos outros agentes com o histórico autorizado e as preferências do cliente", ["customer_memory"])
    order = 0

    def should_activate(self, session: SessionContext, state: WorkingState) -> bool:
        return False

    def run(self, ctx: AgentContext) -> AgentResult:  # pragma: no cover - não roda na esteira
        return AgentResult(MEMORY_ID, "done", customer_facts(ctx.state), "Consultado sob demanda.")
