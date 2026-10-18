import unittest

from backend.agents.bootstrap import build_orchestrator
from backend.agents.models import SessionContext
from backend.agents.testing.fakes import FakeRuntime, InMemoryMemory, RecordingSink
from backend.memory import SQLiteCustomerMemory


def offer(pid, name, price, merchant, mid):
    return {"product_id": pid, "name": name, "unit_price_cents": price, "merchant_id": mid, "merchant_name": merchant,
            "tags": [], "delivery_fee_cents": 0, "other_fees_cents": 0, "eta_minutes": 30}


PIZZA_REAL = offer("p1", "Pizza Calabresa Grande", 4500, "Pizzaria Real", "pr")
ESFIHA = offer("e1", "Pizza", 899, "Ponto da Esfiha", "pe")
PASTEL = offer("pa", "Pastel de Pizza", 700, "Pastelaria", "pt")
OFFERS = [PIZZA_REAL, ESFIHA, PASTEL]
CURATOR = {"items": [{"product_id": "p1", "fit": "sim", "reason": "pizza grande para dividir"},
                     {"product_id": "e1", "fit": "nao", "reason": "esfiha de pizza, porção pequena"},
                     {"product_id": "pa", "fit": "nao", "reason": "pastel, não é pizza"}]}


def run(text="quero pizza para 2 pessoas até R$ 200", reasoning=None, offers=OFFERS, customers=None, mode="demo"):
    runtime = FakeRuntime(offers=offers, reasoning=reasoning or {}, provider="ifood_mcp" if mode == "real" else "demo")
    sink = RecordingSink()
    orch = build_orchestrator(runtime, InMemoryMemory(), sink, customers=customers or SQLiteCustomerMemory())
    out = orch.handle_message(SessionContext("s1", "t", "cli", mode, text))
    return out, runtime, sink, orch


def events(sink, type_):
    return [e for e in sink.events if e["type"] == type_]


class CuratorTest(unittest.TestCase):
    def test_ai_rejects_cheap_esfiha_and_pastel(self):
        out, runtime, sink, _ = run(reasoning={"curator": CURATOR})
        names = [i["name"] for r in out.recommendations for i in r["items"]]
        self.assertEqual(set(names), {"Pizza Calabresa Grande"})
        msg = [e["payload"]["summary"] for e in events(sink, "agent_message") if e["actor"]["id"] == "curator"]
        self.assertIn("esfiha de pizza", msg[0])
        self.assertEqual(len(runtime.calls), 1)  # pergunta à IA não conta como busca

    def test_ai_cannot_add_items_that_did_not_come_from_the_search(self):
        fake = {"items": CURATOR["items"] + [{"product_id": "inventado", "fit": "sim", "reason": "x"}]}
        out, *_ = run(reasoning={"curator": fake})
        self.assertNotIn("inventado", str(out.recommendations))

    def test_without_ai_lexical_fallback_still_works(self):
        out, _, sink, _ = run()
        self.assertTrue(out.recommendations)
        failed = [e["payload"] for e in events(sink, "tool_activity") if e["payload"]["tool_name"] == "raciocinio_ia"]
        self.assertTrue(failed and all(p["status"] == "failed" for p in failed))

    def test_quota_reason_is_shown_to_manager(self):
        runtime = FakeRuntime(offers=OFFERS)
        runtime.reasoning = {}
        orig = runtime.run
        def run_with_quota(call):
            if not call.allowed_tools:
                from backend.agents.ports import RuntimeOutcome
                runtime.reasoning_calls.append(call)
                return RuntimeOutcome(ok=False, error="quota", retry_after_s=30)
            return orig(call)
        runtime.run = run_with_quota
        sink = RecordingSink()
        build_orchestrator(runtime, InMemoryMemory(), sink, customers=SQLiteCustomerMemory()).handle_message(
            SessionContext("s1", "t", None, "demo", "quero pizza para 2 pessoas até R$ 200"))
        notes = [e["payload"]["summary"] for e in events(sink, "tool_activity") if e["payload"]["tool_name"] == "raciocinio_ia"]
        self.assertTrue(notes and all("cota da IA esgotada" in n for n in notes))

    def test_everything_rejected_means_ask_customer(self):
        reject = {"items": [{"product_id": p["product_id"], "fit": "nao", "reason": "não é pizza"} for p in OFFERS]}
        out, *_ = run(reasoning={"curator": reject})
        self.assertEqual((out.recommendations, out.session_status), ([], "waiting_customer"))

    def test_ai_judgment_reused_on_follow_up(self):
        runtime = FakeRuntime(offers=OFFERS, reasoning={"curator": CURATOR})
        orch = build_orchestrator(runtime, InMemoryMemory(), RecordingSink(), customers=SQLiteCustomerMemory())
        orch.handle_message(SessionContext("s1", "t", None, "demo", "quero pizza para 2 pessoas até R$ 200"))
        orch.handle_message(SessionContext("s1", "t", None, "demo", "agora são 3 pessoas"))
        curator_calls = [c for c in runtime.reasoning_calls if c.agent_id == "curator"]
        self.assertEqual((len(runtime.calls), len(curator_calls)), (1, 1))


class StrategistTest(unittest.TestCase):
    TWO = [offer("a", "Pizza Calabresa", 3000, "Pizzaria A", "a"), offer("b", "Pizza Mussarela", 4000, "Pizzaria B", "b")]

    def test_strategist_consults_memory_agent_and_ai_orders(self):
        def strat(prompt):
            import json, re
            opts = json.loads(re.search(r"OPCOES_JSON:\s*(.*)", prompt).group(1))
            last = [o["id"] for o in opts if o["restaurante"] == "Pizzaria B"]
            return {"ordem": last, "argumento": "Esta tem o queijo que você curte.", "motivo": "cliente prefere mussarela"}
        out, _, sink, _ = run(offers=self.TWO, reasoning={"sales_strategist": strat})
        self.assertEqual(out.recommendations[0]["merchant_name"], "Pizzaria B")
        self.assertIn("queijo que você curte", out.reply_text)
        talk = [(e["actor"]["id"], e["recipient"]["id"]) for e in events(sink, "agent_message")]
        self.assertIn(("sales_strategist", "customer_memory"), talk)
        self.assertIn(("customer_memory", "sales_strategist"), talk)

    def test_pitch_with_numbers_is_discarded(self):
        def strat(prompt):
            return {"ordem": [], "argumento": "Só R$ 10 hoje!", "motivo": "x"}
        out, *_ = run(offers=self.TWO, reasoning={"sales_strategist": strat})
        self.assertNotIn("R$ 10", out.reply_text)


class DiscountTest(unittest.TestCase):
    BIG = [offer("g", "Pizza Gigante", 6000, "Pizzaria", "pz")]

    def test_ai_can_decline_discount(self):
        out, _, sink, _ = run(offers=self.BIG, reasoning={
            "discount_specialist": {"sugerir": False, "desconto_bps": 0, "motivo": "cliente novo, sem histórico"}})
        self.assertEqual(events(sink, "discount_proposed"), [])

    def test_ai_discount_is_capped_by_policy(self):
        out, _, sink, _ = run(offers=self.BIG, reasoning={
            "discount_specialist": {"sugerir": True, "desconto_bps": 5000, "motivo": "cliente fiel"}})
        p = events(sink, "discount_proposed")[0]["payload"]
        self.assertEqual(p["discount_bps"], 500)  # máximo da política
        self.assertIn("IA: cliente fiel", p["reason"])
        self.assertEqual(out.recommendations[0]["discount_cents"], 0)  # sugerido, nunca aplicado

    def test_discount_agent_also_asks_memory(self):
        _, _, sink, _ = run(offers=self.BIG)
        talk = [(e["actor"]["id"], e["recipient"]["id"]) for e in events(sink, "agent_message")]
        self.assertIn(("discount_specialist", "customer_memory"), talk)


class ReplyTest(unittest.TestCase):
    def test_ai_reply_accepted_when_guardrails_pass(self):
        def reply(prompt):
            import re
            base = re.search(r"RESPOSTA_BASE:\s*(.*)", prompt).group(1)
            return {"resposta": "Oba! " + base}
        out, *_ = run(offers=[PIZZA_REAL], reasoning={"orchestrator": reply})
        self.assertTrue(out.reply_text.startswith("Oba! Sugiro Pizzaria Real"))

    def test_ai_reply_with_wrong_price_is_rejected(self):
        out, *_ = run(offers=[PIZZA_REAL], reasoning={"orchestrator": {
            "resposta": "Sugiro Pizzaria Real por R$ 1,00 no total R$ 90,00. Confirma?"}})
        self.assertTrue(out.reply_text.startswith("Sugiro Pizzaria Real: 2x Pizza Calabresa Grande. Total R$ 90,00"))

    def test_ai_reply_without_merchant_is_rejected(self):
        out, *_ = run(offers=[PIZZA_REAL], reasoning={"orchestrator": {"resposta": "Achei uma pizza ótima! R$ 90,00. Confirma?"}})
        self.assertIn("Pizzaria Real", out.reply_text)


if __name__ == "__main__":
    unittest.main()
