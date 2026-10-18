import unittest

from backend.agents.bootstrap import build_orchestrator
from backend.agents.models import SessionContext
from backend.agents.testing.fakes import FakeRuntime, InMemoryMemory, RecordingSink
from backend.memory import SQLiteCustomerMemory

PIZZA = [{"product_id": f"p{i}", "name": n, "unit_price_cents": c, "merchant_id": "pz", "merchant_name": "Pizzaria",
          "tags": [], "delivery_fee_cents": 0, "other_fees_cents": 0, "eta_minutes": 30}
         for i, (n, c) in enumerate([("Pizza Calabresa", 4000), ("Pizza Mussarela", 3800)])]
MARMITA = [{"product_id": "m1", "name": "Marmita Parmegiana", "unit_price_cents": 2500, "merchant_id": "mm",
            "merchant_name": "Marmitaria", "tags": [], "delivery_fee_cents": 0, "other_fees_cents": 0,
            "eta_minutes": 30}]


class Client:
    """Um cliente com vários atendimentos (sessões) e memória do cliente compartilhada."""

    def __init__(self, customers=None, client_id="cli_1", offers=None):
        self.customers = customers or SQLiteCustomerMemory()
        self.runtime = FakeRuntime(offers=offers if offers is not None else PIZZA + MARMITA)
        self.sink = RecordingSink()
        self.orch = build_orchestrator(self.runtime, InMemoryMemory(), self.sink, customers=self.customers)
        self.client_id = client_id

    def say(self, session, text):
        return self.orch.handle_message(SessionContext(session, "tenant_demo", self.client_id, "demo", text))

    def events(self, type_):
        return [e["payload"] for e in self.sink.events if e["type"] == type_]


class CustomerMemoryFlowTest(unittest.TestCase):
    def test_request_is_remembered_and_greeting_mentions_it(self):
        c = Client()
        c.say("s1", "quero marmita parmegiana para 2 pessoas até R$ 100")
        out = c.say("s2", "oi")
        self.assertIn("Da última vez você pediu marmita parmegiana", out.reply_text)
        self.assertTrue(out.reply_text.endswith("?"))
        self.assertEqual(c.runtime.calls.__len__(), 1)  # saudação não busca

    def test_memory_changed_event_for_new_request_only(self):
        c = Client()
        c.say("s1", "quero marmita parmegiana para 2 pessoas até R$ 100")
        c.say("s1", "agora são 3 pessoas")  # mesmo atendimento: atualiza, não conta de novo
        changed = c.events("memory_changed")
        self.assertEqual(len(changed), 1)
        self.assertEqual((changed[0]["scope"], changed[0]["keys"]), ("customer", ["requests"]))
        p = c.customers.profile("tenant_demo", "cli_1")
        self.assertEqual((p.requests, p.last_party_size), (1, 3))

    def test_repeat_last_order_uses_dish_party_and_budget(self):
        c = Client()
        c.say("s1", "quero marmita parmegiana para 2 pessoas até R$ 100")
        out = c.say("s2", "quero o mesmo")
        self.assertEqual(len(c.runtime.calls), 2)
        self.assertIn("Produto desejado: marmita parmegiana.", c.runtime.calls[1].prompt)
        self.assertEqual(sum(i["quantity"] for i in out.recommendations[0]["items"]), 2)
        self.assertIn("Marmita Parmegiana", out.reply_text)

    def test_repeat_without_history_stays_a_question(self):
        c = Client()
        out = c.say("s1", "quero o mesmo")
        self.assertEqual((len(c.runtime.calls), out.session_status), (0, "waiting_customer"))

    def test_favorite_dish_after_two_sessions_drives_strategy(self):
        c = Client()
        c.say("s1", "quero pizza para 2 pessoas até R$ 200")
        c.say("s2", "quero pizza para 2 pessoas até R$ 200")
        c.say("s3", "quero comida para 2 pessoas até R$ 200")
        patterns = [p for p in c.events("pattern_identified") if "atendimentos anteriores" in p["description"]]
        self.assertEqual(patterns[-1]["description"], "Em atendimentos anteriores pediu pizza (2 vezes)")
        self.assertEqual(patterns[-1]["basis"], "stated_preference")

    def test_anonymous_session_is_not_remembered(self):
        customers = SQLiteCustomerMemory()
        c = Client(customers=customers, client_id=None)
        c.say("s1", "quero pizza para 2 pessoas até R$ 200")
        self.assertEqual(c.events("memory_changed"), [])
        self.assertIsNone(customers.profile("tenant_demo", ""))

    def test_clients_are_isolated(self):
        customers = SQLiteCustomerMemory()
        a, b = Client(customers, "a"), Client(customers, "b")
        a.say("s1", "quero pizza para 2 pessoas até R$ 200")
        self.assertNotIn("Da última vez", b.say("s2", "oi").reply_text)

    def test_generic_request_without_dish_is_not_recorded(self):
        c = Client()
        c.say("s1", "quero comida para 2 pessoas até R$ 200")
        self.assertIsNone(c.customers.profile("tenant_demo", "cli_1"))


class SQLiteCustomerMemoryTest(unittest.TestCase):
    def test_profile_aggregates(self):
        m = SQLiteCustomerMemory()
        m.record_request("t", "c", "s1", ("pizza",), 2, 10000)
        m.record_request("t", "c", "s2", ("pizza",), 4, 16000)
        m.record_request("t", "c", "s3", ("sushi",), 1, 6000)
        p = m.profile("t", "c")
        self.assertEqual((p.requests, p.favorite_dishes, p.last_terms), (3, (("pizza", 2),), ("sushi",)))
        self.assertEqual(p.typical_budget_per_person_cents, 5000)

    def test_forget_removes_history(self):
        m = SQLiteCustomerMemory()
        m.record_request("t", "c", "s1", ("pizza",), 2, 10000)
        self.assertEqual(m.forget("t", "c"), 1)
        self.assertIsNone(m.profile("t", "c"))

    def test_tenant_isolation_and_invalid_input(self):
        m = SQLiteCustomerMemory()
        m.record_request("t1", "c", "s1", ("pizza",), 2, 10000)
        self.assertIsNone(m.profile("t2", "c"))
        self.assertFalse(m.record_request("t1", "", "s1", ("pizza",), 2, 10000))
        self.assertFalse(m.record_request("t1", "c", "s1", (), 2, 10000))


if __name__ == "__main__":
    unittest.main()
