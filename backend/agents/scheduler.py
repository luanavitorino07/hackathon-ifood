"""Agendamento da compra de mercado: regra do orquestrador (sem IA), não um agente da esteira.

O horário precisa ter pelo menos 30 min de folga e no máximo 4 meses. O agendamento só vale depois que o
cliente confirma; ele fica no nosso sistema (o iFood não recebe agendamento: o MCP liberado só busca). Na
data, os agentes refazem a cesta com os preços do dia e pedem confirmação.
"""
from __future__ import annotations

from datetime import datetime, timezone

from .events import EventEmitter
from .grocery import describe_when, iso, schedule_problem
from .models import WorkingState

SCHEDULE_NOTE = "Na data eu refaço a cesta com os preços do dia e peço sua confirmação antes de comprar"


def plan_schedule(state: WorkingState, events: EventEmitter) -> None:
    """Confere o horário pedido para a cesta aprovada e anota em `state.schedule_plan`.

    Horário inválido tira a aprovação das cestas: o cliente escolhe outro horário antes de ver a proposta.
    """
    request = state.schedule
    if request is None or request.when is None or not state.approved_ids or state.schedule_plan is not None:
        return
    now = state.now or datetime.now(timezone.utc)
    problem = schedule_problem(request.when, now)
    if problem:
        state.schedule_plan = {"problem": problem}
        state.approved_ids = []
        events.decision(None, f"Agendamento recusado: {problem}", [], ["data e horário válidos para o agendamento"])
        return
    label = describe_when(request.when, request.recurrence)
    state.schedule_plan = {"when": iso(request.when), "recurrence": request.recurrence, "label": label}
    for rec in state.recommendations:
        if rec["recommendation_id"] in state.approved_ids:
            rec["reasons"].append(f"Compra agendada para {label}")
            rec["warnings"].append(SCHEDULE_NOTE)
