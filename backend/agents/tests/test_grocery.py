import unittest
from datetime import datetime, timedelta, timezone

from backend.agents.auditor import audit_basket
from backend.agents.bootstrap import build_orchestrator
from backend.agents.demo.runtime import DemoCatalogRuntime
from backend.agents.grocery import (ListItem, edit_items, next_occurrence, parse_items, parse_schedule,
                                    schedule_from_ai)
from backend.agents.models import Constraints, Offer, SessionContext, WorkingState
from backend.agents.ports import RuntimeOutcome
from backend.agents.testing.fakes import FakeRuntime, InMemoryMemory, RecordingSink
from backend.memory import SQLiteCustomerMemory

# sábado, 18/10/2026, 10h00 em Brasília
NOW = datetime(2026, 10, 18, 13, 0, tzinfo=timezone.utc)


class NoAIRuntime(DemoCatalogRuntime):
    """Catálogo demo, mas a IA dos agentes fica indisponível (vale a regra de reserva)."""

    def run(self, call):
        if not call.allowed_tools:
            return RuntimeOutcome(ok=False, error="unavailable", detail="sem IA")
        return super().run(call)


class PartialAIRuntime(DemoCatalogRuntime):
    """Reproduz o bug da demo real: com muitos produtos, a IA do Montador julga só uma parte (aqui, só o arroz)."""

    def run(self, call):
        out = super().run(call)
        if call.agent_id == "grocery_basket" and out.ok:
            out.structured["produtos"] = [p for p in out.structured["produtos"] if p["product_id"] in {"gm1", "ge1"}]
        return out


class ManyOffersRuntime(FakeRuntime):
    """20 arrozes de 6 mercados por busca; registra quantos produtos foram enviados à IA."""

    def __init__(self):
        offers = [{"product_id": f"a{n}", "name": f"Arroz Tipo 1 Marca {n} 5kg", "unit_price_cents": 2000 + n,
                   "merchant_id": f"m{n % 6}", "merchant_name": f"Mercado {n % 6}", "tags": [],
                   "delivery_fee_cents": 500, "other_fees_cents": 0, "eta_minutes": 40} for n in range(20)]
        super().__init__(offers=offers, reasoning={"grocery_basket": self._judge})
        self.sent = 0

    def _judge(self, prompt):
        import json, re
        products = json.loads(re.search(r"PRODUTOS_JSON:\s*(.*)", prompt).group(1))
        self.sent = len(products)
        return {"produtos": [{"product_id": p["product_id"], "fit": "sim", "quantidade": 1} for p in products]}


def make(runtime=None, mode="demo", clock=None):
    sink = RecordingSink()
    now = clock or [NOW]
    orch = build_orchestrator(runtime or DemoCatalogRuntime(), InMemoryMemory(), sink,
                              customers=SQLiteCustomerMemory(), clock=lambda: now[0])

    def say(text, sid="s1"):
        return orch.handle_message(SessionContext(sid, "t", "cli", mode, text))
    return orch, sink, say, now


def names(out):
    return [i["name"] for i in out.recommendations[0]["items"]]


class ParsingTest(unittest.TestCase):
    def test_list_with_quantities_sizes_and_accents(self):
        items = parse_items("compra do mês no mercado: arroz 5kg, 2 pacotes de feijão, 3 leites, café e 1 dúzia de ovos")
        self.assertEqual([i.label() for i in items],
                         ["arroz (5 kg)", "2x feijão", "3x leite", "café", "ovos (1 dúzia)"])

    def test_edit_list(self):
        items = parse_items("mercado: arroz, feijão")
        self.assertEqual([i.name for i in edit_items("adiciona papel higiênico", items)],
                         ["arroz", "feijão", "papel higiênico"])
        self.assertEqual([i.name for i in edit_items("tira o feijão", items)], ["arroz"])
        self.assertIsNone(edit_items("quero pizza", items))

    def test_schedule_rules(self):
        weekly = parse_schedule("mercado todo sábado às 10h: arroz", NOW)
        self.assertEqual((weekly.when, weekly.recurrence), (datetime(2026, 10, 24, 13, 0, tzinfo=timezone.utc), "weekly"))
        tomorrow = parse_schedule("amanhã de manhã", NOW)
        self.assertEqual(tomorrow.when, datetime(2026, 10, 19, 12, 0, tzinfo=timezone.utc))
        self.assertEqual(parse_schedule("dia 25 às 14h30", NOW).when, datetime(2026, 10, 25, 17, 30, tzinfo=timezone.utc))
        self.assertIsNone(parse_schedule("mercado: arroz e feijão", NOW))
        self.assertIsNone(parse_schedule("toda semana", NOW).when)  # quer agendar, falta o dia

    def test_schedule_from_ai_and_recurrence(self):
        s = schedule_from_ai({"quer_agendar": True, "data": "2026-11-30", "hora": "18:00", "recorrencia": "mensal"}, NOW)
        self.assertEqual(s.when, datetime(2026, 11, 30, 21, 0, tzinfo=timezone.utc))
        self.assertEqual(next_occurrence(s.when, "monthly"), datetime(2026, 12, 30, 21, 0, tzinfo=timezone.utc))
        jan31 = datetime(2027, 1, 31, 13, 0, tzinfo=timezone.utc)
        self.assertEqual(next_occurrence(jan31, "monthly").day, 28)  # fevereiro
        self.assertIsNone(schedule_from_ai({"quer_agendar": False}, NOW))


class GroceryFlowTest(unittest.TestCase):
    def test_basket_in_one_market_with_grocery_search(self):
        runtime = DemoCatalogRuntime()
        _, sink, say, _ = make(runtime)
        out = say("quero fazer a compra do mês no mercado: arroz 5kg, 2 pacotes de feijão, leite e café")
        self.assertEqual(out.session_status, "active")
        rec = out.recommendations[0]
        self.assertEqual(rec["merchant_name"], "Mercado Bom Preço Demo")
        self.assertEqual(names(out), ["Arroz Branco Tipo 1 5kg", "Feijão Carioca 1kg", "Leite Integral 1L",
                                      "Café Torrado e Moído 500g"])  # 'Doce de Leite' rejeitado pela IA
        self.assertEqual([i["quantity"] for i in rec["items"]], [1, 2, 1, 1])
        self.assertTrue(all(c.context.get("merchant_type") == "GROCERIES" for c in runtime.calls))
        self.assertEqual(rec["total_cents"], rec["subtotal_cents"] + rec["delivery_fee_cents"])
        self.assertIn("Montei sua cesta no Mercado Bom Preço Demo", out.reply_text)
        agents = {e["payload"]["agent_id"] for e in sink.events if e["type"] == "agent_status"}
        self.assertTrue({"researcher", "grocery_basket", "auditor"} <= agents)
        self.assertFalse({"planner", "curator", "sales_strategist"} & agents)

    def test_missing_items_searched_inside_best_market(self):
        runtime = DemoCatalogRuntime()
        _, sink, say, _ = make(runtime)
        out = say("lista do mercado: detergente, papel higiênico, cerveja")
        scoped = [c for c in runtime.calls if c.context.get("merchant_id")]
        self.assertEqual([c.context["merchant_id"] for c in scoped], ["demo_mercado_1"])  # cerveja no Bom Preço
        self.assertIn("Não encontrei neste mercado: cerveja", out.reply_text)

    def test_products_the_ai_did_not_judge_fall_back_to_words(self):
        """Bug da demo: 'adiciona detergente' -> 100 produtos, IA julgou só parte e a cesta ficou só com arroz."""
        _, _, say, _ = make(PartialAIRuntime())
        out = say("lista do mercado: arroz 5kg, 2 feijões, leite, café e detergente")
        rec = out.recommendations[0]
        self.assertEqual(rec["merchant_name"], "Mercado Bom Preço Demo")
        self.assertEqual(len(rec["items"]), 5)
        self.assertNotIn("Doce de Leite 400g", names(out))

    def test_ai_receives_at_most_six_candidates_per_item(self):
        runtime = ManyOffersRuntime()
        _, _, say, _ = make(runtime)
        say("mercado: arroz")
        self.assertEqual(runtime.sent, 6)

    def test_lactose_restriction_picks_lactose_free_milk(self):
        _, _, say, _ = make()
        out = say("sou intolerante a lactose. mercado: leite e café")
        self.assertIn("Leite Zero Lactose 1L", names(out))
        self.assertNotIn("Leite Integral 1L", names(out))

    def test_item_named_lactose_free_is_not_a_basket_restriction(self):
        orch, _, say, _ = make()
        out = say("mercado: leite sem lactose e arroz")
        self.assertEqual(out.session_status, "active")
        state = orch._memory.load("s1").state
        self.assertEqual(state["constraints"]["dietary"], [])

    def test_budget_too_small_asks_to_adjust(self):
        _, sink, say, _ = make()
        out = say("mercado até R$ 20: arroz 5kg, café e papel higiênico")
        self.assertEqual(out.session_status, "waiting_customer")
        self.assertIn("aumentar o orçamento", out.reply_text)
        self.assertTrue(any(e["type"] == "conflict_detected" for e in sink.events))

    def test_without_ai_rules_build_basket_with_warning(self):
        _, _, say, _ = make(NoAIRuntime())
        out = say("supermercado: arroz 5kg e café")
        self.assertEqual(out.session_status, "active")
        self.assertIn("Tamanhos pedidos não conferidos", out.reply_text)

    def test_ask_for_list_when_empty(self):
        _, _, say, _ = make()
        out = say("quero fazer mercado")
        self.assertEqual(out.session_status, "waiting_customer")
        self.assertIn("lista de mercado", out.reply_text)

    def test_switch_back_to_food_clears_list(self):
        _, _, say, _ = make()
        say("mercado: arroz e café")
        out = say("na verdade quero pizza")
        self.assertIn("Pizzaria Forno Demo", out.reply_text)

    def test_real_session_without_mcp_proof_is_discarded(self):
        _, sink, say, _ = make(FakeRuntime(), mode="real")
        out = say("mercado: arroz")
        self.assertEqual(out.recommendations, [])
        self.assertTrue(any(e["type"] == "error" for e in sink.events))


class SchedulingTest(unittest.TestCase):
    def test_schedule_confirm_run_and_cancel(self):
        orch, sink, say, now = make()
        out = say("mercado todo sábado às 10h: arroz, feijão e café")
        self.assertIn("Agendo para sábado, 24/10 às 10h00 (toda semana)", out.reply_text)
        self.assertIn("Confirma o agendamento?", out.reply_text)
        self.assertEqual(orch.due_schedules(NOW + timedelta(days=30)), [])  # pendente até confirmar
        out = say("fechado")
        self.assertIn("Agendado!", out.reply_text)
        self.assertIn("nenhum pedido é enviado ao iFood", out.reply_text)
        self.assertIn("sábado, 24/10", say("meus agendamentos").reply_text)
        now[0] = datetime(2026, 10, 24, 13, 1, tzinfo=timezone.utc)
        due = orch.due_schedules()
        self.assertEqual(len(due), 1)
        chosen = orch._schedules.get(due[0]).merchant_id
        run = orch.run_schedule(due[0])
        self.assertIn("Chegou o dia da sua compra agendada", run.reply_text)
        self.assertEqual(run.recommendations[0]["merchant_id"], chosen)  # mesmo mercado da cesta aceita
        self.assertIn("Mesmo mercado da sua compra agendada", run.recommendations[0]["reasons"])
        self.assertEqual(orch.due_schedules(), [])  # já avançou para o próximo sábado
        self.assertIsNone(orch.run_schedule(due[0]))
        cancel = say("cancela o agendamento")
        self.assertIn("sábado, 31/10", cancel.reply_text)
        self.assertIn("não tem compras agendadas", say("meus agendamentos").reply_text)

    def test_one_time_schedule_is_done_after_run(self):
        orch, _, say, now = make()
        say("supermercado amanhã às 18h: café")
        say("pode ser")
        now[0] = datetime(2026, 10, 19, 21, 0, tzinfo=timezone.utc)
        sid = orch.due_schedules()[0]
        orch.run_schedule(sid)
        self.assertEqual(orch._schedules.get(sid).status, "done")

    def test_schedule_without_date_asks_when(self):
        _, _, say, _ = make()
        out = say("quero agendar uma compra de mercado toda semana: arroz e café")
        self.assertIn("Para quando agendo", out.reply_text)
        out = say("segunda às 9h")
        self.assertIn("segunda, 19/10 às 09h00 (toda semana)", out.reply_text)

    def test_past_time_is_refused(self):
        _, _, say, _ = make()
        out = say("mercado hoje às 8h: café")
        self.assertEqual(out.recommendations, [])
        self.assertIn("já passou", out.reply_text)

    def test_cancel_without_schedules(self):
        _, _, say, _ = make()
        self.assertIn("não tem compras agendadas", say("cancelar agendamento").reply_text)


class BasketAuditTest(unittest.TestCase):
    def test_rejects_product_not_in_list_and_wrong_price(self):
        offer = Offer("p1", "Arroz 5kg", 2000, "m1", "Mercado", delivery_fee_cents=500, other_fees_cents=0)
        other = Offer("p2", "Chocolate", 900, "m1", "Mercado", delivery_fee_cents=500, other_fees_cents=0)
        st = WorkingState(constraints=Constraints(), offers=[offer, other], shopping_list=(ListItem("arroz"),),
                          grocery_of={"p1": "arroz"})
        rec = {"recommendation_id": "r", "merchant_id": "m1", "merchant_name": "Mercado", "currency": "BRL",
               "items": [{"product_id": "p1", "name": "Arroz 5kg", "quantity": 1, "unit_price_cents": 1500},
                         {"product_id": "p2", "name": "Chocolate", "quantity": 1, "unit_price_cents": 900}],
               "subtotal_cents": 2400, "delivery_fee_cents": 500, "other_fees_cents": 0, "discount_cents": 0,
               "total_cents": 2900, "eta_minutes": None, "reasons": [], "warnings": [], "data_origin": "demo"}
        issues = audit_basket(rec, st)
        self.assertIn("Preço de p1 diverge da busca", issues)
        self.assertIn("Produto p2 não corresponde a item da lista", issues)


if __name__ == "__main__":
    unittest.main()
