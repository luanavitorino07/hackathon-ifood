"""Orquestrador: seleciona agentes pelo registro, coordena a esteira e emite os eventos."""
from __future__ import annotations

from typing import Any

from .events import ORCHESTRATOR_ID, EventEmitter, new_id
from .intent import constraints_from_initial_context, extract_constraints, overlay
from .models import AgentResult, AgentsOutput, Constraints, SessionContext, WorkingState, tag_requirements
from .ports import AgentRuntimePort, EventSink, MemoryPort, RevisionConflict
from .registry import Agent, AgentContext, AgentRegistry

_ERROR_CODES = {"quota": ("LLM_QUOTA", True), "timeout": ("LLM_TIMEOUT", True),
                "invalid_output": ("LLM_INVALID_OUTPUT", True), "unavailable": ("LLM_UNAVAILABLE", True)}


def _brl(cents: int | None) -> str:
    return "valor indisponível" if cents is None else f"R$ {cents // 100},{cents % 100:02d}"


class Orchestrator:
    def __init__(self, registry: AgentRegistry, runtime: AgentRuntimePort,
                 memory: MemoryPort, sink: EventSink) -> None:
        self._registry, self._runtime, self._memory, self._sink = registry, runtime, memory, sink

    def catalog(self) -> list[dict[str, object]]:
        return self._registry.catalog()

    # ------------------------------------------------------------------
    def handle_message(self, session: SessionContext) -> AgentsOutput:
        events = EventEmitter(self._sink, session.session_id)
        constraints = self._build_constraints(session)
        state = WorkingState(constraints=constraints)
        self._persist(session.session_id, ORCHESTRATOR_ID, {"constraints": constraints.to_dict()})
        events.agent_status(ORCHESTRATOR_ID, "running", None, "Planejando atendimento")

        ran: set[str] = set()
        missing: list[str] = []
        limitations: list[str] = []
        while True:  # a esteira é reavaliada a cada estágio concluído
            pending = [a for a in self._registry.select(session, state)
                       if a.definition.agent_id not in ran]
            if not pending:
                break
            agent = pending[0]
            ran.add(agent.definition.agent_id)
            result = self._run_agent(agent, session, state, events)
            missing += result.missing_data
            limitations += result.limitations
            if result.status == "error":
                return self._fail(events, result)
            if result.status == "needs_info":
                break
        state.missing_data = missing
        return self._finish(state, events, limitations)

    def _build_constraints(self, session: SessionContext) -> Constraints:
        """memória < session.constraints < initial_context < mensagem atual (explícita)."""
        stored = Constraints.from_dict(self._memory.load(session.session_id).state.get("constraints"))
        merged = overlay(stored, session.constraints)
        merged = constraints_from_initial_context(session.initial_context, merged)
        return extract_constraints(session.message_text, merged)

    def _fail(self, events: EventEmitter, result: AgentResult) -> AgentsOutput:
        code, retryable = _ERROR_CODES.get(str(result.output.get("error")), ("AGENT_ERROR", False))
        events.error(code, result.justification, retryable)
        events.agent_status(ORCHESTRATOR_ID, "error", None, result.justification)
        text = ("No momento não consegui consultar as opções. Pode tentar novamente em instantes?"
                if retryable else "Tive um problema ao preparar sua recomendação. Pode reformular o pedido?")
        events.assistant_message(text)
        return AgentsOutput("error" if not retryable else "active", text, [])

    def _finish(self, state: WorkingState, events: EventEmitter, limitations: list[str]) -> AgentsOutput:
        approved = [r for r in state.recommendations if r["recommendation_id"] in state.approved_ids]
        for rid, problems in state.issues.items():
            if problems:
                cid = new_id("conf")
                events.conflict(cid, ["planner", "auditor"], f"Proposta {rid}: " + "; ".join(problems), "open")
                events.agent_message(ORCHESTRATOR_ID, "planner", cid, "resolution",
                                     f"Proposta {rid} descartada por reprovação na auditoria")
                events.conflict(cid, ["planner", "auditor"], f"Proposta {rid} descartada", "resolved")
        if not approved:
            unverifiable = tag_requirements(state.constraints, state.offers)
            if not state.offers:
                reason, ask = "Não encontrei ofertas disponíveis.", "Pode ajustar o pedido?"
            elif unverifiable:
                names = ", ".join(unverifiable)
                reason = f"Não consegui confirmar nas ofertas a restrição: {names}."
                ask = "Pode me dizer como prefere seguir, ou ajustar a restrição?"
            else:
                reason, ask = ("Nenhuma opção atende orçamento e restrições ao mesmo tempo.",
                               "Pode ajustar o orçamento ou as restrições?")
            text = f"{reason} {ask}"
            events.decision(None, reason, [], limitations or state.missing_data)
            events.agent_status(ORCHESTRATOR_ID, "waiting", None, "Aguardando cliente")
            events.assistant_message(text)
            return AgentsOutput("waiting_customer", text, [])
        best = approved[0]
        events.recommendations_ready(approved)
        events.decision(best["recommendation_id"],
                        f"Recomendação principal: {best['merchant_name']}",
                        best["reasons"], limitations + best["warnings"])
        events.agent_status(ORCHESTRATOR_ID, "done", None, "Recomendação pronta")
        text = self._reply_text(best, state.data_origin)
        events.assistant_message(text)
        return AgentsOutput("active", text, approved)

    @staticmethod
    def _reply_text(rec: dict[str, Any], origin: str) -> str:
        items = ", ".join(f"{i['quantity']}x {i['name']}" for i in rec["items"])
        total = _brl(rec["total_cents"] if rec["total_cents"] is not None else rec["subtotal_cents"])
        text = f"Sugiro {rec['merchant_name']}: {items}. Total {total}"
        if rec["total_cents"] is None:
            text += " (sem taxas, que ainda não foram informadas)"
        notes = [w for w in rec["warnings"] if "não comprovada" in w or w.startswith("Taxa de serviço")]
        if notes:
            text += ". Atenção: " + " ".join(notes)
        text += ". Deseja confirmar este pedido?"
        if origin == "demo":
            text += " [dados de demonstração]"
        return text

    # ------------------------------------------------------------------
    def _run_agent(self, agent: Agent, session: SessionContext, state: WorkingState,
                   events: EventEmitter) -> AgentResult:
        aid, task_id = agent.definition.agent_id, new_id("task")
        events.agent_message(ORCHESTRATOR_ID, aid, task_id, "request", f"Executar {agent.definition.role}")
        events.agent_status(aid, "running", task_id, agent.definition.role)
        try:
            result = agent.run(AgentContext(session, state, self._runtime, events, task_id))
        except Exception as exc:  # falha de um agente não derruba o atendimento
            result = AgentResult(aid, "error", {"error": type(exc).__name__},
                                 "Falha interna do agente.", limitations=["exceção interna"])
        events.agent_status(aid, "error" if result.status == "error" else "done", task_id, result.justification)
        channel = "review" if aid == "auditor" else "proposal"
        events.agent_message(aid, ORCHESTRATOR_ID, task_id, channel, result.justification)
        self._persist(session.session_id, aid, {
            "candidates": [o.__dict__ | {"tags": list(o.tags)} for o in state.offers],
            "data_origin": state.data_origin, "proposals": state.recommendations,
            "audit": {"approved": state.approved_ids, "issues": state.issues}})
        return result

    def _persist(self, session_id: str, author: str, patch: dict[str, Any]) -> None:
        for _ in range(2):
            snapshot = self._memory.load(session_id)
            try:
                self._memory.save_patch(session_id, patch, snapshot.revision, author)
                return
            except RevisionConflict:
                continue
        raise RevisionConflict(f"conflito persistente de revisão em {session_id}")
