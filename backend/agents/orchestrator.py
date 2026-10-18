"""Orquestrador: seleciona agentes pelo registro, coordena a esteira e emite os eventos."""
from __future__ import annotations

import re
import time
from dataclasses import replace
from datetime import datetime, timezone
from typing import Any, Callable

from .chat import classify, reply_for
from .events import ORCHESTRATOR_ID, EventEmitter, new_id
from .customer_memory_agent import MEMORY_ID, customer_facts
from .grocery import (ListItem, ScheduleRequest, describe_when, iso, list_text, next_occurrence, parse_iso,
                      wants_schedule_cancel, wants_schedule_list)
from .intent import constraints_from_initial_context, extract_constraints, overlay, wants_cheaper
from .interpreter import DEFINITION as INTERPRETER_DEFINITION, INTERPRETER_ID, Reading, describe, interpret
from .models import (AgentResult, AgentsOutput, Constraints, SessionContext, WorkingState, persona_key,
                     restriction_label, tag_requirements)
from .ports import (AgentRuntimePort, CustomerMemoryPort, CustomerProfile, EventSink, KnowledgePort,
                    MemoryPort, RevisionConflict, ScheduledPurchase, SchedulePort)
from .ai import ask
from .failures import classify_failure
from .resumption import reusable_offers, signature
from .registry import Agent, AgentContext, AgentDefinition, AgentRegistry
from .scheduler import SCHEDULE_NOTE, plan_schedule
from .usage import MeteredRuntime, UsageLedger
from .strategist import STRATEGIES

REPLY_SYSTEM = ("Você é o atendente simpático de um chatbot de comida. Reescreva a RESPOSTA_BASE de forma natural "
                "e calorosa, em português do Brasil, em até 3 frases. Mantenha exatamente o nome do restaurante, os "
                "itens, o valor total e TODOS os avisos (comece-os com 'Atenção:'); não invente preços, prazos ou "
                "promoções; termine perguntando se o cliente quer confirmar o pedido.")
REPLY_SCHEMA = {"type": "object", "required": ["resposta"], "properties": {"resposta": {"type": "string"}}}

ORCHESTRATOR_DEFINITION = AgentDefinition(
    ORCHESTRATOR_ID, "Orquestrador", "Coordenação do atendimento",
    "Conversa com o cliente (com IA), decide quais especialistas acionar e resolve conflitos", ["orchestration"])


PRESENTED_RECOMMENDATIONS = 3
MAX_OFFERED = 30  # opções guardadas por atendimento para o botão Comprar


def _brl(cents: int | None) -> str:
    return "valor indisponível" if cents is None else f"R$ {cents // 100},{cents % 100:02d}"


def _customer_note(warning: str) -> bool:
    """Avisos que o cliente precisa ler na resposta (restrição sem prova, taxa, prato aproximado)."""
    return ("não comprovada" in warning or "avaliada pela IA" in warning or warning.startswith("Taxa de serviço")
            or warning.startswith(("Não encontrei exatamente", "Não encontrei neste mercado", "Restrições não verificadas",
                                   "Tamanhos pedidos não conferidos")))


class Orchestrator:
    def __init__(self, registry: AgentRegistry, runtime: AgentRuntimePort,
                 memory: MemoryPort, sink: EventSink, knowledge: KnowledgePort | None = None,
                 customers: CustomerMemoryPort | None = None, schedules: SchedulePort | None = None,
                 clock: Callable[[], datetime] | None = None, usage: UsageLedger | None = None) -> None:
        self._usage = usage or UsageLedger()
        runtime = MeteredRuntime(runtime, self._usage)  # todo consumo de IA dos agentes é contabilizado
        self._registry, self._runtime, self._memory, self._sink = registry, runtime, memory, sink
        self._knowledge, self._customers, self._schedules = knowledge, customers, schedules
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._current: SessionContext | None = None

    def catalog(self) -> list[dict[str, object]]:
        return [ORCHESTRATOR_DEFINITION.to_dict(), INTERPRETER_DEFINITION.to_dict()] + self._registry.catalog()

    # ------------------------------------------------------------------
    def handle_message(self, session: SessionContext) -> AgentsOutput:
        events = EventEmitter(self._sink, session.session_id)
        self._current = session
        self._bind_usage(session)
        now = self._clock()
        if self._schedules is not None and wants_schedule_list(session.message_text):
            return self._list_schedules(session, events)
        if self._schedules is not None and wants_schedule_cancel(session.message_text):
            return self._cancel_schedule(session, events)
        stored = self._memory.load(session.session_id).state
        self._resolve_open_conflicts(session, stored, events)
        grocery = stored.get("grocery") if isinstance(stored.get("grocery"), dict) else {}
        stored_list = tuple(i for i in (ListItem.from_dict(x) for x in grocery.get("items") or []) if i)
        stored_schedule = ScheduleRequest.from_dict(grocery.get("schedule"))
        base, constraints, in_order, shown, stored_terms = self._build_constraints(session)
        search = stored.get("search") if isinstance(stored.get("search"), dict) else {}
        stored_extras = tuple(x for x in search.get("extras") or [] if isinstance(x, str))
        profile = self._profile(session)
        base, constraints = self._apply_profile(stored, base, constraints, profile, events)
        state = WorkingState(constraints=constraints, customer_profile=profile, now=now)
        reading = self._interpret(session, state, base, stored_terms, in_order, shown, events, stored_extras,
                                  stored_list, stored_schedule)
        constraints = state.constraints = reading.constraints
        state.query_terms, state.request_summary = reading.terms, reading.summary
        state.extra_terms = reading.extras
        shown_total = shown.get("total_cents") if shown else None
        if wants_cheaper(session.message_text) and isinstance(shown_total, int):
            state.price_ceiling_cents = shown_total
        intent = reading.intent
        if intent == "repeat":  # "quero o mesmo": último pedido do cliente
            if profile is not None and profile.last_terms:
                state.query_terms = state.query_terms or profile.last_terms
                state.constraints = constraints = overlay(
                    Constraints(profile.last_budget_cents, profile.last_party_size), constraints)
                intent = "order"
            else:
                intent = "chat" if not state.query_terms else "order"
        if intent == "confirm" and shown:
            return self._confirm(session, events, constraints, shown)
        if reading.profile_conflict and profile is not None and profile.declared_restrictions:
            constraints = state.constraints = self._profile_conflict(reading.profile_conflict, constraints,
                                                                     profile, events)
        if reading.groceries is not None:  # compra de supermercado (agendada ou não)
            return self._grocery(session, state, reading, events)
        if grocery:  # mudou de mercado para comida: a lista deixa de valer
            self._persist(session.session_id, ORCHESTRATOR_ID, {"grocery": None})
        if intent != "order":  # papo: responde direto, sem a esteira de busca
            return self._chat_only(session, events, constraints, reading, profile)
        self._persist(session.session_id, ORCHESTRATOR_ID,
                      {"constraints": constraints.to_dict(), "conversation": {"stage": "ordering"},
                       "search": {"terms": list(state.query_terms), "summary": state.request_summary,
                                  "extras": list(state.extra_terms)}})
        current_signature = {**signature(session, constraints, state.query_terms),
                             "extras": sorted(state.extra_terms)}
        return self._pipeline(session, state, events, current_signature)

    def _pipeline(self, session: SessionContext, state: WorkingState, events: EventEmitter,
                  current_signature: dict[str, Any], allow_reuse: bool = True) -> AgentsOutput:
        """Esteira de especialistas escolhidos pelo registro, reavaliada a cada estágio."""
        constraints = state.constraints
        events.agent_status(ORCHESTRATOR_ID, "running", None, "Planejando atendimento")
        # o julgamento do Curador depende também das preferências ("acha um já montado")
        curation_signature = {**current_signature, "preferences": sorted(constraints.preferences)}
        reuse = reusable_offers(self._memory.load(session.session_id).state, session, current_signature) \
            if allow_reuse else None
        if reuse is not None:  # só mudou quantidade/orçamento: replaneja sem nova busca
            state.offers, state.data_origin, why = reuse  # type: ignore[assignment]
            saved_search = self._memory.load(session.session_id).state.get("last_search") or {}
            state.extra_of = {k: v for k, v in (saved_search.get("extra_of") or {}).items() if isinstance(v, str)}
            state.grocery_of = {k: v for k, v in (saved_search.get("grocery_of") or {}).items() if isinstance(v, str)}
            curation = self._memory.load(session.session_id).state.get("curation")
            if isinstance(curation, dict) and curation.get("signature") == curation_signature:
                state.ai_fit = {k: (v[0], v[1]) for k, v in (curation.get("fit") or {}).items()
                                if isinstance(v, list) and len(v) == 2}
                state.ai_serves = {k: v for k, v in (curation.get("serves") or {}).items()
                                   if isinstance(v, int) and 1 <= v <= 12}
                state.ai_restrictions = {k: tuple(v) for k, v in (curation.get("restrictions") or {}).items()
                                         if isinstance(v, list)}
            events.agent_message(ORCHESTRATOR_ID, "researcher", new_id("task"), "resolution",
                                 f"Pesquisa reaproveitada, sem nova busca: {why}")
        if self._customers is not None and hasattr(self._customers, "strategy_performance"):
            state.strategy_performance = self._customers.strategy_performance(session.tenant_id)

        ran: set[str] = set()
        missing: list[str] = []
        limitations: list[str] = []
        retry: dict[str, Any] | None = None  # nova busca pedida pelo Curador ao Pesquisador (uma vez)
        while True:  # a esteira é reavaliada a cada estágio concluído
            pending = [a for a in self._registry.select(session, state)
                       if a.definition.agent_id not in ran]
            if not pending:
                break
            agent = pending[0]
            aid = agent.definition.agent_id
            ran.add(aid)
            result = self._run_agent(agent, session, state, events)
            if aid == "researcher" and retry is not None and not retry.get("searched"):
                retry["searched"] = True
                if not state.offers:  # a nova busca não trouxe nada: volta ao que havia
                    self._restore(state, retry)
                    self._close_retry(events, retry, "Nova busca sem resultado; mantidas as ofertas anteriores")
                    retry["closed"] = True
                    continue
            if aid == "curator" and state.ai_fit:
                self._persist(session.session_id, ORCHESTRATOR_ID, {"curation": {
                    "signature": curation_signature, "fit": {k: list(v) for k, v in state.ai_fit.items()},
                    "serves": dict(state.ai_serves),
                    "restrictions": {k: list(v) for k, v in state.ai_restrictions.items()}}})
                if retry is None and state.research_hint:
                    retry = self._ask_new_search(state, events)
                    ran -= {"researcher", "curator"}
                    continue
                if retry is not None and not retry.get("closed"):
                    good = sum(1 for pid, (fit, _) in state.ai_fit.items() if fit == "sim" and pid not in state.extra_of)
                    if not good:  # a nova busca também não serviu: fica a melhor das duas
                        self._restore(state, retry)
                    self._close_retry(events, retry, f"Nova busca '{retry['hint']}': {good} opção(ões) atendem"
                                      if good else f"Nova busca '{retry['hint']}' também não serviu; "
                                      "mantida a opção mais próxima")
                    retry["closed"] = True
            if aid == "researcher" and result.status == "done" and state.offers:
                self._persist(session.session_id, ORCHESTRATOR_ID, {"last_search": {
                    "signature": current_signature, "at": time.time(), "count": len(state.offers),
                    "extra_of": dict(state.extra_of), "grocery_of": dict(state.grocery_of)}})
            missing += result.missing_data
            limitations += result.limitations
            if result.status == "error":
                return self._fail(events, result)
            if result.status == "needs_info":
                break
        state.missing_data = missing
        plan_schedule(state, events)  # compra de mercado agendada: confere o horário da cesta aprovada
        return self._finish(session.session_id, state, events, limitations)

    # ---- compras de supermercado e agendamentos ---------------------------------------
    def _grocery(self, session: SessionContext, state: WorkingState, reading: Reading,
                 events: EventEmitter) -> AgentsOutput:
        """Lista de mercado: busca item a item, monta a cesta por mercado e, se pedido, agenda."""
        items, schedule = reading.groceries or (), reading.schedule
        constraints = state.constraints
        self._persist(session.session_id, ORCHESTRATOR_ID, {
            "constraints": constraints.to_dict(), "conversation": {"stage": "ordering"},
            "search": {"terms": [], "summary": state.request_summary, "extras": []},
            "grocery": {"items": [i.to_dict() for i in items], "schedule": schedule.to_dict() if schedule else None}})
        if not items:
            return self._ask(events, "O que vai na sua lista de mercado? Pode mandar tudo numa mensagem, "
                                     "ex.: arroz 5 kg, 2 leites, café e detergente.")
        if schedule is not None and schedule.when is None:
            return self._ask(events, f"Anotei a lista ({list_text(items)}). Para quando agendo a compra? "
                                     "Ex.: sábado às 10h, ou toda segunda às 9h.")
        state.shopping_list, state.schedule = items, schedule
        state.query_terms, state.extra_terms = (), ()
        current_signature = {**signature(session, constraints, ()), "extras": [],
                             "groceries": sorted(i.name for i in items)}
        return self._pipeline(session, state, events, current_signature)

    def _ask(self, events: EventEmitter, text: str) -> AgentsOutput:
        events.agent_status(ORCHESTRATOR_ID, "waiting", None, "Aguardando cliente")
        events.assistant_message(text)
        return AgentsOutput("waiting_customer", text, [])

    def _my_schedules(self, session: SessionContext) -> list[ScheduledPurchase]:
        assert self._schedules is not None
        return self._schedules.list_for(session.tenant_id, self._client_key(session), session.session_id)

    @staticmethod
    def _schedule_line(p: ScheduledPurchase) -> str:
        when = parse_iso(p.next_run_at)
        items = list_text(tuple(i for i in (ListItem.from_dict(x) for x in p.items) if i))
        pending = " (aguardando sua confirmação)" if p.status == "pending_confirmation" else ""
        return (f"{describe_when(when, p.recurrence) if when else p.next_run_at}"
                f"{' no ' + p.merchant_name if p.merchant_name else ''}: {items}{pending}")

    def _list_schedules(self, session: SessionContext, events: EventEmitter) -> AgentsOutput:
        mine = [p for p in self._my_schedules(session) if p.status == "active"]
        if not mine:
            text = "Você não tem compras agendadas. Quer agendar uma? Mande a lista e o dia, ex.: mercado todo sábado às 10h: arroz, feijão e café."
        else:
            lines = "; ".join(f"{n}) {self._schedule_line(p)}" for n, p in enumerate(mine, 1))
            text = f"Suas compras agendadas: {lines}. Quer mudar ou cancelar alguma?"
        events.agent_status(ORCHESTRATOR_ID, "running", None, f"Consulta de agendamentos: {len(mine)} ativo(s)")
        return self._ask(events, text)

    def _cancel_schedule(self, session: SessionContext, events: EventEmitter) -> AgentsOutput:
        assert self._schedules is not None
        mine = [p for p in self._my_schedules(session) if p.status == "active"]
        pick = re.search(r"\b(\d{1,2})\b", session.message_text)
        if not mine:
            return self._ask(events, "Você não tem compras agendadas para cancelar. Posso ajudar com outra coisa?")
        if len(mine) > 1 and not pick:
            lines = "; ".join(f"{n}) {self._schedule_line(p)}" for n, p in enumerate(mine, 1))
            return self._ask(events, f"Qual agendamento cancelo? {lines}. Responda, por exemplo, 'cancelar agendamento 1'.")
        index = int(pick.group(1)) - 1 if pick and len(mine) > 1 else 0
        if not 0 <= index < len(mine):
            return self._ask(events, "Não achei esse número na sua lista de agendamentos. Pode conferir?")
        target = mine[index]
        self._schedules.save(replace(target, status="cancelled"))
        events.memory_changed("customer" if target.client_key else "session", ["schedules"],
                              "Compra agendada cancelada pelo cliente")
        return self._ask(events, f"Pronto, cancelei a compra agendada de {self._schedule_line(target)}. "
                                 "Quer agendar outra ou pedir alguma coisa agora?")

    def _record_sale(self, session_id: str, recommendation_id: Any, total_cents: Any) -> bool:
        """Venda aceita (no chat ou pelo botão de compra) conta uma vez por recomendação."""
        sold = self._memory.load(session_id).state.get("sold")
        sold = [x for x in sold if isinstance(x, str)] if isinstance(sold, list) else []
        if isinstance(recommendation_id, str) and recommendation_id in sold:
            return False
        self._usage.add_sale(session_id, total_cents if isinstance(total_cents, int) else None)
        if isinstance(recommendation_id, str):
            self._persist(session_id, ORCHESTRATOR_ID, {"sold": sold + [recommendation_id]})
        return True

    def simulate_purchase(self, session_id: str, recommendation_id: str, client_action_id: str) -> dict[str, Any]:
        """Botão "Comprar": registra uma compra SIMULADA da recomendação e avisa o cliente no chat.

        Nada é enviado ao iFood e nenhum pagamento é feito (o MCP liberado só busca). Idempotente por
        `client_action_id`. Conta como venda no custo de IA por cliente e na monitoria de estratégias."""
        events = EventEmitter(self._sink, session_id)
        stored = self._memory.load(session_id).state
        orders = [o for o in stored.get("orders") or [] if isinstance(o, dict)]
        done = next((o for o in orders if o.get("client_action_id") == client_action_id), None)
        if done is not None:
            return done
        # o chat mantém os cards de sugestões anteriores: vale qualquer opção já mostrada neste atendimento
        known = [p for p in (stored.get("offered") or []) + (stored.get("proposals") or []) if isinstance(p, dict)]
        rec = next((p for p in known if p.get("recommendation_id") == recommendation_id), None)
        if rec is None:
            events.order_status(None, "failed", "Recomendação não encontrada neste atendimento")
            events.assistant_message("Não encontrei essa opção neste atendimento. Pode pedir de novo?")
            return {"status": "failed"}
        order_id = "sim_" + new_id("ord")[4:]
        total = rec.get("total_cents") if isinstance(rec.get("total_cents"), int) else rec.get("subtotal_cents")
        items = ", ".join(f"{i.get('quantity')}x {i.get('name')}" for i in rec.get("items") or [])
        if self._record_sale(session_id, recommendation_id, total):
            shown = stored.get("shown") if isinstance(stored.get("shown"), dict) else {}
            owner = self._usage.owner(session_id)
            if (owner and not owner[1].startswith("anon:") and self._customers is not None
                    and hasattr(self._customers, "record_acceptance")
                    and shown.get("recommendation_id") == recommendation_id):
                self._customers.record_acceptance(owner[0], owner[1], session_id)
        order = {"order_id": order_id, "client_action_id": client_action_id, "recommendation_id": recommendation_id,
                 "merchant": rec.get("merchant_name"), "total_cents": total, "status": "confirmed", "simulated": True}
        self._persist(session_id, ORCHESTRATOR_ID, {"orders": orders + [order],
                                                    "conversation": {"stage": "confirmed"}})
        events.agent_status(ORCHESTRATOR_ID, "done", None, "Compra simulada registrada")
        events.order_status(order_id, "confirmed",
                            f"Compra SIMULADA em {rec.get('merchant_name')} ({_brl(total)}): nada foi enviado ao iFood")
        events.memory_changed("session", ["orders"], f"Compra simulada {order_id} registrada")
        events.assistant_message(
            f"Compra registrada! 🎉 Pedido {order_id} no {rec.get('merchant_name')}: {items}. Total {_brl(total)}. "
            "Isto é uma simulação: nenhum pedido foi enviado ao iFood e nenhum pagamento foi feito. "
            "Quer pedir mais alguma coisa?")
        return order

    def _remember_offered(self, session_id: str, approved: list[dict[str, Any]]) -> None:
        """Opções mostradas ao cliente neste atendimento (as mais recentes), para o botão Comprar."""
        offered = [p for p in self._memory.load(session_id).state.get("offered") or [] if isinstance(p, dict)]
        ids = {r["recommendation_id"] for r in approved}
        offered = [p for p in offered if p.get("recommendation_id") not in ids] + approved
        self._persist(session_id, ORCHESTRATOR_ID, {"offered": offered[-MAX_OFFERED:]})

    def usage_report(self, tenant_id: str) -> dict[str, Any]:
        """Custo de IA por cliente e vendas aceitas (Análise financeira do gestor)."""
        return self._usage.report(tenant_id)

    def _bind_usage(self, session: SessionContext) -> None:
        name = (session.initial_context or {}).get("name")
        label = name if isinstance(name, str) and name.strip() else (
            "Cliente sem cadastro" if session.client_id else "Atendimento anônimo")
        self._usage.bind(session.session_id, session.tenant_id, self._client_key(session), label)

    def scheduled(self, schedule_id: str) -> ScheduledPurchase | None:
        """Agendamento pelo id (a API usa para saber a sessão e o cliente antes de rodar)."""
        return self._schedules.get(schedule_id) if self._schedules is not None else None

    def due_schedules(self, now: datetime | None = None) -> list[str]:
        """Ids das compras agendadas que já chegaram na data (a API chama periodicamente)."""
        if self._schedules is None:
            return []
        return [p.schedule_id for p in self._schedules.due(iso(now or self._clock()))]

    def run_schedule(self, schedule_id: str) -> AgentsOutput | None:
        """Chegou a data: refaz a cesta com os preços do dia, de preferência no mesmo mercado, e pede
        confirmação ao cliente no atendimento de origem. Nunca compra sozinho."""
        p = self._schedules.get(schedule_id) if self._schedules is not None else None
        now = self._clock()
        if p is None or p.status != "active" or p.next_run_at > iso(now):  # só na data (evita rodar duas vezes)
            return None
        when = parse_iso(p.next_run_at) or now
        following = next_occurrence(when, p.recurrence)
        while following is not None and following <= now:  # API ficou parada: pula as datas perdidas
            following = next_occurrence(following, p.recurrence)
        # avança antes de rodar: uma falha na busca não faz o agendamento disparar de novo a cada consulta
        self._schedules.save(replace(p, next_run_at=iso(following) if following else p.next_run_at,
                                     status="active" if following else "done"))
        items = tuple(i for i in (ListItem.from_dict(x) for x in p.items) if i)
        session = SessionContext(p.session_id, p.tenant_id, p.client_id, p.mode,
                                 "Compra agendada: " + list_text(items), initial_context=p.initial_context)
        self._current = session
        self._bind_usage(session)
        events = EventEmitter(self._sink, session.session_id)
        stored = self._memory.load(session.session_id).state
        saved = Constraints.from_dict(stored.get("constraints"))
        constraints = Constraints(p.budget_cents, None, saved.dietary, saved.preferences)
        label = describe_when(when, p.recurrence)
        task = new_id("task")
        events.agent_message(ORCHESTRATOR_ID, "researcher", task, "request",
                             f"Compra agendada chegou ({label}): refazer a cesta com os preços do dia")
        state = WorkingState(constraints=constraints, now=now, shopping_list=items,
                             preferred_merchant_id=p.merchant_id,
                             reply_prefix=f"📅 Chegou o dia da sua compra agendada ({describe_when(when)})! ")
        self._persist(session.session_id, ORCHESTRATOR_ID, {
            "constraints": constraints.to_dict(), "conversation": {"stage": "ordering"},
            "grocery": {"items": [i.to_dict() for i in items], "schedule": None}})
        out = self._pipeline(session, state, events, {**signature(session, constraints, ()), "extras": [],
                                                      "groceries": sorted(i.name for i in items)}, allow_reuse=False)
        best = out.recommendations[0] if out.recommendations else None
        if best is not None:
            current = self._schedules.get(schedule_id) or p  # type: ignore[union-attr]
            self._schedules.save(replace(current, last_total_cents=best["total_cents"]))  # type: ignore[union-attr]
        return out

    def _save_schedule(self, session: SessionContext, state: WorkingState, best: dict[str, Any]) -> str | None:
        """Agendamento proposto fica pendente até o cliente confirmar."""
        plan = state.schedule_plan or {}
        if self._schedules is None or "when" not in plan:
            return None
        sid = new_id("sched")
        context = {k: v for k, v in (session.initial_context or {}).items()
                   if k in ("location", "name") and v}  # o nome identifica o cliente fictício na memória
        self._schedules.save(ScheduledPurchase(
            schedule_id=sid, tenant_id=session.tenant_id, session_id=session.session_id,
            client_id=session.client_id, client_key=self._client_key(session), mode=session.mode,
            items=tuple(i.to_dict() for i in state.shopping_list), budget_cents=state.constraints.budget_cents,
            merchant_id=best["merchant_id"], merchant_name=best["merchant_name"], next_run_at=plan["when"],
            recurrence=plan["recurrence"], status="pending_confirmation",
            initial_context=context or None, last_total_cents=best["total_cents"]))
        return sid

    def _basket_text(self, rec: dict[str, Any], state: WorkingState) -> str:
        items = ", ".join(f"{i['quantity']}x {i['name']}" for i in rec["items"])
        total = _brl(rec["total_cents"] if rec["total_cents"] is not None else rec["subtotal_cents"])
        text = f"Montei sua cesta no {rec['merchant_name']}: {items}. Total {total}"
        if rec["total_cents"] is None:
            text += " (sem taxas, que ainda não foram informadas)"
        notes = [w for w in rec["warnings"] if _customer_note(w)]
        if notes:
            text += ". Atenção: " + "; ".join(notes)
        plan = state.schedule_plan or {}
        if "label" in plan:
            text += f". Agendo para {plan['label']}: {SCHEDULE_NOTE[0].lower() + SCHEDULE_NOTE[1:]}. Confirma o agendamento?"
        else:
            text += ". Deseja confirmar esta compra?"
        if state.data_origin == "demo":
            text += " [dados de demonstração]"
        return text

    # ---- entendimento, cadastro e conflitos ------------------------------------------
    def _interpret(self, session: SessionContext, state: WorkingState, base: Constraints,
                   stored_terms: tuple[str, ...], in_order: bool, shown: dict[str, Any] | None,
                   events: EventEmitter, stored_extras: tuple[str, ...] = (),
                   stored_list: tuple[ListItem, ...] = (), stored_schedule: ScheduleRequest | None = None) -> Reading:
        task = new_id("task")
        events.agent_message(ORCHESTRATOR_ID, INTERPRETER_ID, task, "request", "Entender a mensagem do cliente")
        events.agent_status(INTERPRETER_ID, "running", task, INTERPRETER_DEFINITION.role)
        ctx = AgentContext(session, state, self._runtime, events, task, self._knowledge)
        facts: dict[str, Any] = {}
        if state.customer_profile is not None:
            events.agent_message(INTERPRETER_ID, MEMORY_ID, task, "request", "O que sabemos deste cliente?")
            facts = customer_facts(state, session)
            from .customer_memory_agent import summary
            events.agent_message(MEMORY_ID, INTERPRETER_ID, task, "proposal", "Cliente: " + summary(facts))
        last = None
        if shown:
            items = ", ".join(shown.get("items") or [])
            last = f"{shown.get('merchant') or ''}: {items}".strip(": ") or None
        reading = interpret(ctx, base, state.constraints, stored_terms, in_order, last, facts, stored_extras,
                            stored_list, stored_schedule)
        events.agent_status(INTERPRETER_ID, "done", task, "Mensagem entendida")
        events.agent_message(INTERPRETER_ID, ORCHESTRATOR_ID, task, "proposal", describe(reading))
        removed = [r for r in state.constraints.dietary if r not in reading.constraints.dietary]
        if removed:
            events.memory_changed("session", ["constraints"], "Restrição removida a pedido do cliente: "
                                  + ", ".join(restriction_label(r) for r in removed))
        added = [r for r in reading.constraints.dietary if r not in state.constraints.dietary]
        if added:
            events.memory_changed("session", ["constraints"],
                                  "Restrição entendida pela IA: " + ", ".join(restriction_label(r) for r in added))
        return reading

    def _apply_profile(self, stored: dict[str, Any], base: Constraints, constraints: Constraints,
                       profile: CustomerProfile | None, events: EventEmitter) -> tuple[Constraints, Constraints]:
        """Restrições/preferências do cadastro valem desde a primeira mensagem (só acumulam)."""
        if profile is None or not (profile.declared_restrictions or profile.declared_preferences):
            return base, constraints
        cadastro = Constraints(None, None, profile.declared_restrictions, profile.declared_preferences)
        if not isinstance(stored.get("constraints"), dict):  # primeira mensagem do atendimento
            labels = ", ".join(restriction_label(r) for r in profile.declared_restrictions)
            likes = ", ".join(profile.declared_preferences)
            events.agent_message(MEMORY_ID, ORCHESTRATOR_ID, new_id("task"), "proposal",
                                 "Cadastro do cliente: " + (f"restrições {labels}" if labels else "sem restrições")
                                 + (f"; gosta de {likes}" if likes else ""))
        return overlay(base, cadastro), overlay(constraints, cadastro)

    def _profile_conflict(self, description: str, constraints: Constraints, profile: CustomerProfile | None,
                          events: EventEmitter) -> Constraints:
        """O pedido contraria o cadastro. Saúde (lactose, glúten, alergia) se mantém; dieta por escolha
        (vegetariano/vegano) cede ao pedido explícito de agora, e o cliente é avisado."""
        cid = new_id("conf")
        events.conflict(cid, [INTERPRETER_ID, MEMORY_ID], f"Pedido × cadastro: {description}", "open")
        lifestyle = {"vegetarian", "vegetarian_option", "vegan", "vegan_option"}
        declared = set(profile.declared_restrictions) if profile else set()
        dropped = [r for r in constraints.dietary if r in lifestyle and r in declared]
        if dropped:
            how = ("Vale o pedido de agora: " + ", ".join(restriction_label(r) for r in dropped)
                   + " do cadastro não se aplica a este pedido; restrições de saúde mantidas")
            constraints = Constraints(constraints.budget_cents, constraints.party_size,
                                      tuple(r for r in constraints.dietary if r not in dropped),
                                      constraints.preferences)
        else:
            how = "Restrição de saúde do cadastro mantida; o cliente é avisado"
        events.agent_message(ORCHESTRATOR_ID, INTERPRETER_ID, cid, "resolution", how)
        events.conflict(cid, [INTERPRETER_ID, MEMORY_ID], how, "resolved")
        return constraints

    def _resolve_open_conflicts(self, session: SessionContext, stored: dict[str, Any],
                                events: EventEmitter) -> None:
        """Conflitos que esperavam o cliente são resolvidos pela resposta dele."""
        pending = stored.get("open_conflicts")
        if not isinstance(pending, list) or not pending:
            return
        for c in pending:
            if isinstance(c, dict) and isinstance(c.get("id"), str):
                events.conflict(c["id"], list(c.get("agents") or [ORCHESTRATOR_ID]),
                                f"Cliente respondeu: {session.message_text[:120]}", "resolved")
        self._persist(session.session_id, ORCHESTRATOR_ID, {"open_conflicts": []})

    def _ask_new_search(self, state: WorkingState, events: EventEmitter) -> dict[str, Any]:
        """Curador × Pesquisador: nada do que veio serve; o Curador pede outra busca."""
        hint = state.research_hint or ""
        cid = new_id("conf")
        wanted = state.request_summary or " ".join(state.query_terms)
        events.conflict(cid, ["curator", "researcher"],
                        f"Nenhuma das {len(state.offers)} ofertas encontradas atende: {wanted}", "open")
        events.agent_message("curator", "researcher", cid, "request",
                             f"Nada aqui serve para \"{wanted}\". Pode buscar \"{hint}\"?")
        saved = {"offers": state.offers, "fit": state.ai_fit, "serves": state.ai_serves,
                 "restrictions": state.ai_restrictions, "terms": state.query_terms, "origin": state.data_origin}
        state.offers, state.ai_fit, state.ai_serves, state.ai_restrictions = [], {}, {}, {}
        state.query_terms, state.research_hint = tuple(hint.split()), None
        return {"id": cid, "hint": hint, "saved": saved}

    @staticmethod
    def _restore(state: WorkingState, retry: dict[str, Any]) -> None:
        saved = retry["saved"]
        state.offers, state.ai_fit, state.ai_serves = saved["offers"], saved["fit"], saved["serves"]
        state.ai_restrictions, state.query_terms, state.data_origin = (saved["restrictions"], saved["terms"],
                                                                       saved["origin"])

    @staticmethod
    def _close_retry(events: EventEmitter, retry: dict[str, Any], how: str) -> None:
        events.agent_message(ORCHESTRATOR_ID, "curator", retry["id"], "resolution", how)
        events.conflict(retry["id"], ["curator", "researcher"], how, "resolved")

    def _confirm(self, session: SessionContext, events: EventEmitter, constraints: Constraints,
                 shown: dict[str, Any]) -> AgentsOutput:
        """O cliente aceitou a última sugestão: registra a venda da estratégia (monitoria)."""
        scheduled = self._schedules.get(shown["schedule_id"]) if self._schedules is not None and \
            isinstance(shown.get("schedule_id"), str) else None
        if scheduled is not None and scheduled.status == "pending_confirmation":
            return self._confirm_schedule(session, events, constraints, scheduled)
        strategy = shown.get("strategy")
        self._record_sale(session.session_id, shown.get("recommendation_id"), shown.get("total_cents"))
        key = self._client_key(session)
        if self._customers is not None and key and hasattr(self._customers, "record_acceptance"):
            strategy = self._customers.record_acceptance(session.tenant_id, key, session.session_id) or strategy
        name = STRATEGIES.get(strategy or "", strategy or "sem estratégia")
        events.agent_message(ORCHESTRATOR_ID, "sales_strategist", new_id("task"), "resolution",
                             f"Venda fechada: cliente aceitou {shown.get('merchant')} (estratégia: {name})")
        events.memory_changed("customer", ["strategy_outcomes"], f"Venda registrada para a estratégia {name}")
        total = _brl(shown.get("total_cents"))
        text = (f"Perfeito! ✅ Anotei seu pedido de {shown.get('merchant')} ({total}). Nesta demonstração o envio "
                "ao iFood é simulado e nenhum pagamento é feito. Quer pedir mais alguma coisa?")
        self._persist(session.session_id, ORCHESTRATOR_ID, {"constraints": constraints.to_dict(),
                                                            "conversation": {"stage": "confirmed"}})
        events.agent_status(ORCHESTRATOR_ID, "done", None, "Pedido aceito pelo cliente")
        events.assistant_message(text)
        return AgentsOutput("waiting_customer", text, [])

    def _confirm_schedule(self, session: SessionContext, events: EventEmitter, constraints: Constraints,
                          scheduled: ScheduledPurchase) -> AgentsOutput:
        assert self._schedules is not None
        self._schedules.save(replace(scheduled, status="active"))
        line = self._schedule_line(replace(scheduled, status="active"))
        events.memory_changed("customer" if scheduled.client_key else "session", ["schedules"],
                              "Compra de mercado agendada pelo cliente")
        text = (f"Agendado! ✅ {line[0].upper() + line[1:]}. Na data eu refaço a cesta com os preços do dia e peço "
                "sua confirmação antes de comprar; nesta versão nenhum pedido é enviado ao iFood e nenhum pagamento "
                "é feito. Para ver ou cancelar, é só dizer 'meus agendamentos'. Quer mais alguma coisa?")
        self._persist(session.session_id, ORCHESTRATOR_ID, {"constraints": constraints.to_dict(), "grocery": None,
                                                            "conversation": {"stage": "confirmed"}, "shown": None})
        events.agent_status(ORCHESTRATOR_ID, "done", None, "Compra agendada")
        events.assistant_message(text)
        return AgentsOutput("waiting_customer", text, [])

    def _build_constraints(self, session: SessionContext) -> tuple[
            Constraints, Constraints, bool, dict[str, Any] | None, tuple[str, ...]]:
        """initial_context < constraints persistidas < session.constraints < mensagem atual.

        O `initial_context` só preenche a base na PRIMEIRA vez: depois que `constraints` existe
        na memória ele já foi absorvido, e reaplicá-lo desfaria correções do cliente.

        Devolve (base antes da mensagem, após as regras da mensagem, pedido em andamento?, última
        sugestão mostrada, prato da busca anterior).
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
        shown = shown if isinstance(shown, dict) else None
        search = state.get("search")
        raw_terms = search.get("terms") if isinstance(search, dict) else None
        stored_terms = tuple(t for t in raw_terms if isinstance(t, str)) if isinstance(raw_terms, list) else ()
        return merged, extract_constraints(session.message_text, merged), in_order, shown, stored_terms

    def _client_key(self, session: SessionContext) -> str | None:
        """Cliente na memória: na demo, cada cliente fictício (nome no initial_context) tem a sua."""
        if not session.client_id:
            return None
        return persona_key(session.client_id, (session.initial_context or {}).get("name"))

    def _remember_request(self, session_id: str, state: WorkingState, events: EventEmitter) -> None:
        """Guarda no histórico do cliente o prato pedido neste atendimento (só prato/quantidade/orçamento)."""
        session = self._current
        key = self._client_key(session) if session is not None else None
        if self._customers is None or session is None or not key or not state.query_terms:
            return
        c = state.constraints
        if hasattr(self._customers, "record_offer") and state.strategy:
            best = next((r for r in state.recommendations if r["recommendation_id"] in state.approved_ids), None)
            self._customers.record_offer(session.tenant_id, key, session_id, state.strategy,
                                         best["total_cents"] if best else None)
        if self._customers.record_request(session.tenant_id, key, session_id, state.query_terms,
                                          c.party_size, c.budget_cents):
            events.memory_changed("customer", ["requests"],
                                  f"Pedido registrado no histórico do cliente: {' '.join(state.query_terms)}")

    def _profile(self, session: SessionContext) -> CustomerProfile | None:
        key = self._client_key(session)
        if self._customers is None or not key:
            return None
        return self._customers.profile(session.tenant_id, key)

    def _chat_only(self, session: SessionContext, events: EventEmitter, constraints: Constraints,
                   reading: Reading, profile: CustomerProfile | None = None) -> AgentsOutput:
        self._persist(session.session_id, ORCHESTRATOR_ID, {"constraints": constraints.to_dict()})
        kind = classify(session.message_text)
        kind = kind if kind != "order" else "vague"
        text = reading.reply  # resposta da IA do Intérprete (já validada); reserva por regra
        if not text:
            text = reply_for(kind, session.message_text)
            if kind == "greeting" and profile is not None and profile.last_terms:
                text = (f"Oi de novo! 😊 Da última vez você pediu {' '.join(profile.last_terms)}. "
                        "Quer pedir o mesmo ou prefere outra coisa?")
        events.agent_status(ORCHESTRATOR_ID, "waiting", None, f"Conversa ({kind}); aguardando o cliente")
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
                author = "grocery_basket" if state.shopping_list else "planner"
                events.conflict(cid, [author, "auditor"], f"Proposta {rid}: " + "; ".join(problems), "open")
                events.agent_message(ORCHESTRATOR_ID, author, cid, "resolution",
                                     f"Proposta {rid} descartada por reprovação na auditoria")
                events.conflict(cid, [author, "auditor"], f"Proposta {rid} descartada", "resolved")
        if not approved:
            unverifiable = tag_requirements(state.constraints, state.offers)
            problem = (state.schedule_plan or {}).get("problem")
            if problem:
                reason, ask = problem, "Pode escolher outro dia e horário?"
            elif state.shopping_list and not state.offers:
                reason = f"Não encontrei esses produtos em mercados perto de você agora ({list_text(state.shopping_list)})."
                ask = "Quer ajustar a lista ou tentar mais tarde?"
            elif state.shopping_list and state.cheapest_over_budget_cents is None:
                reason = "Não consegui montar uma cesta que atenda à lista e às restrições."
                ask = "Quer ajustar a lista ou as restrições?"
            elif not state.offers and state.query_terms:
                reason = f"Não encontrei \"{' '.join(state.query_terms)}\" disponível agora perto de você."
                ask = "Quer tentar outro prato ou um termo mais geral?"
            elif not state.offers:
                reason, ask = "Não encontrei ofertas disponíveis.", "Pode ajustar o pedido?"
            elif state.relevance_miss:
                wanted = f"\"{' '.join(state.query_terms)}\"" if state.query_terms else "o que você pediu"
                reason = f"Não encontrei {wanted} disponível agora perto de você."
                ask = "Quer tentar outro prato ou descrever de outro jeito?"
            elif state.price_ceiling_cents is not None:
                reason = ("Essa já é a opção mais barata que encontrei com o que você pediu "
                          f"({_brl(state.price_ceiling_cents)}).")
                ask = "Quer ajustar algo, como o orçamento ou as restrições?"
            elif state.cheapest_over_budget_cents is not None and state.constraints.budget_cents is not None:
                c = state.constraints
                people = f" para {c.party_size} pessoas" if c.party_size and c.party_size > 1 else ""
                reason = (f"Com {_brl(c.budget_cents)}{people} não encontrei opção; a mais em conta sai "
                          f"{_brl(state.cheapest_over_budget_cents)}.")
                ask = "Quer aumentar o orçamento ou mudar a quantidade?"
                cid = new_id("conf")
                agents = ["planner", INTERPRETER_ID]
                events.conflict(cid, agents, f"Orçamento × pedido: {reason}", "open")
                events.agent_message("planner", ORCHESTRATOR_ID, cid, "review",
                                     f"Orçamento não cobre o pedido; mínimo encontrado {_brl(state.cheapest_over_budget_cents)}")
                self._persist(session_id, ORCHESTRATOR_ID, {"open_conflicts": [{"id": cid, "agents": agents}]})
            elif unverifiable:
                names = ", ".join(restriction_label(r) for r in unverifiable)
                reason = f"Não consegui confirmar nas ofertas a restrição: {names}."
                ask = "Pode me dizer como prefere seguir, ou ajustar a restrição?"
            elif state.constraints.dietary and state.constraints.budget_cents is None:
                labels = ", ".join(restriction_label(r) for r in state.constraints.dietary)
                reason = f"Não encontrei, num mesmo restaurante, opção que atenda: {labels}."
                ask = "Quer que eu tente outro prato ou ajustar a restrição?"
            else:
                reason, ask = ("Nenhuma opção atende orçamento e restrições ao mesmo tempo.",
                               "Pode ajustar o orçamento ou as restrições?")
            text = (state.reply_prefix or "") + f"{reason} {ask}"
            events.decision(None, reason, [], limitations or state.missing_data)
            events.agent_status(ORCHESTRATOR_ID, "waiting", None, "Aguardando cliente")
            events.assistant_message(text)
            return AgentsOutput("waiting_customer", text, [])
        best = approved[0]
        self._remember_offered(session_id, approved)
        shown = best["total_cents"] if best["total_cents"] is not None else best["subtotal_cents"]
        schedule_id = self._save_schedule(self._current, state, best) if self._current is not None else None
        self._persist(session_id, ORCHESTRATOR_ID,
                      {"shown": {"recommendation_id": best["recommendation_id"], "total_cents": shown,
                                 "merchant": best["merchant_name"], "strategy": state.strategy,
                                 "items": [f"{i['quantity']}x {i['name']}" for i in best["items"]],
                                 "schedule_id": schedule_id}})
        self._remember_request(session_id, state, events)
        events.recommendations_ready(approved)
        events.decision(best["recommendation_id"],
                        f"Recomendação principal: {best['merchant_name']}",
                        best["reasons"], limitations + best["warnings"])
        events.agent_status(ORCHESTRATOR_ID, "done", None, "Recomendação pronta")
        if state.shopping_list:  # cesta: texto montado pelo código (lista longa, sem reescrita da IA)
            text = self._basket_text(best, state)
        else:
            text = self._reply_text(best, state.data_origin, state.pitch)
            text = self._ai_reply(state, best, text, events) or text
        text = (state.reply_prefix or "") + text
        events.assistant_message(text)
        return AgentsOutput("active", text, approved)

    @staticmethod
    def _reply_text(rec: dict[str, Any], origin: str, pitch: str | None = None) -> str:
        items = ", ".join(f"{i['quantity']}x {i['name']}" for i in rec["items"])
        total = _brl(rec["total_cents"] if rec["total_cents"] is not None else rec["subtotal_cents"])
        text = f"Sugiro {rec['merchant_name']}: {items}. Total {total}"
        if rec["total_cents"] is None:
            text += " (sem taxas, que ainda não foram informadas)"
        liked = next((r for r in rec["reasons"] if r.startswith("Combina com sua preferência")), None)
        if liked:
            text += f". {liked}"
        if pitch:
            text += f". {pitch.rstrip('.')}"
        notes = [w for w in rec["warnings"] if _customer_note(w)]
        if notes:
            text += ". Atenção: " + "; ".join(notes)
        text += ". Deseja confirmar este pedido?"
        if origin == "demo":
            text += " [dados de demonstração]"
        return text

    def _ai_reply(self, state: WorkingState, rec: dict[str, Any], fallback: str,
                  events: EventEmitter) -> str | None:
        """A IA reescreve a resposta de forma natural. Guarda-corpo: restaurante, total e avisos vêm do
        código; a resposta da IA só vale se citar o restaurante e o total exatos e não trouxer outro valor."""
        session = self._current
        if session is None:
            return None
        total = _brl(rec["total_cents"] if rec["total_cents"] is not None else rec["subtotal_cents"])
        allowed = {total} | {_brl(i["unit_price_cents"]) for i in rec["items"]}
        ctx = AgentContext(session, state, self._runtime, events, new_id("task"), self._knowledge)
        base = fallback.replace(" [dados de demonstração]", "")
        answer = ask(ctx, ORCHESTRATOR_ID, REPLY_SYSTEM,
                     f"Pedido do cliente: {session.message_text}\n"
                     + (f"Pedido entendido: {state.request_summary}\n" if state.request_summary else "")
                     + f"RESPOSTA_BASE: {base}", REPLY_SCHEMA)
        if answer is None:
            return None
        text = " ".join(answer["resposta"].split())
        amounts = set(re.findall(r"R\$ ?\d+(?:[.,]\d{2})?", text))
        normalized = {a.replace("R$", "R$ ").replace("  ", " ") for a in amounts}
        notes = [w for w in rec["warnings"] if _customer_note(w)]
        if (len(text) > 600 or rec["merchant_name"] not in text or total not in text
                or not normalized <= allowed or not text.endswith("?")
                or any(n[:40] not in text for n in notes)):
            return None  # fora do guarda-corpo: vale a resposta montada pelo código
        if state.data_origin == "demo" and "[dados de demonstração]" not in text:
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
