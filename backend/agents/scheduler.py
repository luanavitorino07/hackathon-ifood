"""Agendador: confere o horário pedido para a compra de mercado e prepara o agendamento.

Regras, sem IA: o horário precisa ter pelo menos 30 min de folga e no máximo 4 meses. O agendamento só
vale depois que o cliente confirma; ele fica no nosso sistema (o iFood não recebe agendamento: o MCP
liberado só busca). Na data, os agentes refazem a cesta com os preços do dia e pedem confirmação.
"""
from __future__ import annotations

from datetime import datetime, timezone

from .grocery import describe_when, iso, schedule_problem
from .models import AgentResult, SessionContext, WorkingState
from .registry import AgentContext, AgentDefinition

SCHEDULER_ID = "scheduler"
SCHEDULE_NOTE = "Na data eu refaço a cesta com os preços do dia e peço sua confirmação antes de comprar"


class Scheduler:
    definition = AgentDefinition(
        SCHEDULER_ID, "Agendador", "Agendamento de compras",
        "Confere o horário pedido e agenda a compra de mercado; na data, refaz a cesta e pede confirmação",
        ["purchase_scheduling"])
    order = 35  # depois do Auditor: só agenda cesta aprovada

    def should_activate(self, session: SessionContext, state: WorkingState) -> bool:
        return (state.schedule is not None and state.schedule.when is not None and bool(state.approved_ids)
                and state.schedule_plan is None)

    def run(self, ctx: AgentContext) -> AgentResult:
        st = ctx.state
        request = st.schedule
        now = st.now or datetime.now(timezone.utc)
        problem = schedule_problem(request.when, now)
        if problem:
            st.schedule_plan = {"problem": problem}
            st.approved_ids = []  # sem horário válido não apresenta a cesta como agendada
            return AgentResult(SCHEDULER_ID, "needs_info", {"scheduled": False}, f"Horário recusado: {problem}",
                               "high", [], ["data e horário válidos para o agendamento"])
        label = describe_when(request.when, request.recurrence)
        st.schedule_plan = {"when": iso(request.when), "recurrence": request.recurrence, "label": label}
        for rec in st.recommendations:
            if rec["recommendation_id"] in st.approved_ids:
                rec["reasons"].append(f"Compra agendada para {label}")
                rec["warnings"].append(SCHEDULE_NOTE)
        ctx.events.agent_message(SCHEDULER_ID, "orchestrator", ctx.task_id, "proposal",
                                 f"Horário ok: {label}. Aguardando confirmação do cliente para agendar")
        return AgentResult(SCHEDULER_ID, "done", {"scheduled": True}, f"Agendamento proposto: {label}.", "high")
