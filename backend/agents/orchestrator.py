"""Orquestrador: seleciona agentes pelo registro, coordena a esteira e emite os eventos."""
from __future__ import annotations

from typing import Any

from .chat import classify, reply_for
from .events import ORCHESTRATOR_ID, EventEmitter, new_id
from .intent import constraints_from_initial_context, extract_constraints, overlay, wants_cheaper
from .models import AgentResult, AgentsOutput, Constraints, SessionContext, WorkingState, tag_requirements
from .ports import AgentRuntimePort, EventSink, KnowledgePort, MemoryPort, RevisionConflict
from .failures import classify_failure
from .registry import Agent, AgentContext, AgentDefinition, AgentRegistry

ORCHESTRATOR_DEFINITION = AgentDefinition(
    ORCHESTRATOR_ID, "Orquestrador", "Coordenação do atendimento",
    "Conversa com o cliente, decide quais especialistas acionar e resolve conflitos", ["orchestration"])


PRESENTED_RECOMMENDATIONS = 3


def _brl(cents: int | None) -> str:
    return "valor indisponível" if cents is None else f"R$ {cents // 100},{cents % 100:02d}"


class Orchestrator:
    def __init__(self, registry: AgentRegistry, runtime: AgentRuntimePort,
                 memory: MemoryPort, sink: EventSink, knowledge: KnowledgePort | None = None) -> None:
        self._registry, self._runtime, self._memory, self._sink = registry, runtime, memory, sink
        self._knowledge = knowledge

    def catalog(self) -> list[dict[str, object]]:
        return [ORCHESTRATOR_DEFINITION.to_dict()] + self._registry.catalog()

    # ------------------------------------------------------------------
    def handle_message(self, session: SessionContext) -> AgentsOutput:
        events = EventEmitter(self._sink, session.session_id)
        constraints, in_order, shown_total = self._build_constraints(session)
        state = WorkingState(constraints=constraints)
        if wants_cheaper(session.message_text) and shown_total is not None:
            state.price_ceiling_cents = shown_total
        intent = classify(session.message_text, in_order)
        if intent != "order":  # papo: responde direto, sem agentes e sem gastar cota
            return self._chat_only(session, events, constraints, intent)
        self._persist(session.session_id, ORCHESTRATOR_ID,
                      {"constraints": constraints.to_dict(), "conversation": {"stage": "ordering"}})
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
        return self._finish(session.session_id, state, events, limitations)

    def _build_constraints(self, session: SessionContext) -> tuple[Constraints, bool, int | None]:
        """initial_context < constraints persistidas < session.constraints < mensagem atual.

        O `initial_context` só preenche a base na PRIMEIRA vez: depois que `constraints` existe
        na memória ele já foi absorvido, e reaplicá-lo desfaria correções do cliente.

        Devolve também se já há um pedido em andamento (`conversation.stage == "ordering"`).
        """
        state = self._memory.load(session.session_id).state
        stored_raw = state.get("constraints")
        if isinstance(stored_raw, dict):
            base = Constraints.from_dict(stored_raw)
        else:
            base = constraints_from_initial_context(session.initial_context, Constraints())
        merged = overlay(base, session.constraints)
        conversation = state.get("conversation")
        in_order = isinstance(conversation, dict) and conversation.get("stage") == "ordering"
        shown = state.get("shown")
        shown_total = shown.get("total_cents") if isinstance(shown, dict) else None
        if not isinstance(shown_total, int) or isinstance(shown_total, bool):
            shown_total = None
        return extract_constraints(session.message_text, merged), in_order, shown_total

    def _chat_only(self, session: SessionContext, events: EventEmitter, constraints: Constraints,
                   intent: str) -> AgentsOutput:
        self._persist(session.session_id, ORCHESTRATOR_ID, {"constraints": constraints.to_dict()})
        text = reply_for(intent, session.message_text)
        events.agent_status(ORCHESTRATOR_ID, "waiting", None, f"Conversa ({intent}); aguardando o cliente")
        events.assistant_message(text)
        return AgentsOutput("waiting_customer", text, [])

    def _fail(self, events: EventEmitter, result: AgentResult) -> AgentsOutput:
        f = classify_failure(result.output.get("error"), result.output.get("detail"),
                             result.output.get("retry_after_s"))
        events.error(f.code, f.admin_text, f.retryable)
        events.agent_status(ORCHESTRATOR_ID, "error" if f.session_status == "error" else "waiting",
                            None, f.admin_text)
        events.assistant_message(f.customer_text)
        return AgentsOutput(f.session_status, f.customer_text, [])

    def _finish(self, session_id: str, state: WorkingState, events: EventEmitter,
                limitations: list[str]) -> AgentsOutput:
        approved = [r for r in state.recommendations
                    if r["recommendation_id"] in state.approved_ids][:PRESENTED_RECOMMENDATIONS]
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
            elif state.price_ceiling_cents is not None:
                reason = ("Essa já é a opção mais barata que encontrei com o que você pediu "
                          f"({_brl(state.price_ceiling_cents)}).")
                ask = "Quer ajustar algo, como o orçamento ou as restrições?"
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
        shown = best["total_cents"] if best["total_cents"] is not None else best["subtotal_cents"]
        self._persist(session_id, ORCHESTRATOR_ID,
                      {"shown": {"recommendation_id": best["recommendation_id"], "total_cents": shown}})
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
        liked = next((r for r in rec["reasons"] if r.startswith("Combina com sua preferência")), None)
        if liked:
            text += f". {liked}"
        notes = [w for w in rec["warnings"] if "não comprovada" in w or w.startswith("Taxa de serviço")]
        if notes:
            text += ". Atenção: " + "; ".join(notes)
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
            result = agent.run(AgentContext(session, state, self._runtime, events, task_id, self._knowledge))
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
