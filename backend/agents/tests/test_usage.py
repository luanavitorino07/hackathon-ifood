import unittest

from backend.agents.bootstrap import build_orchestrator
from backend.agents.models import SessionContext
from backend.agents.ports import RuntimeOutcome, Usage
from backend.agents.testing.fakes import FakeRuntime, InMemoryMemory, RecordingSink
from backend.agents.usage import UsageLedger
from backend.memory import SQLiteCustomerMemory


class PaidRuntime(FakeRuntime):
    """Cada chamada (busca ou IA) custa US$ 0,001 e 1.000 tokens, como o OpenCode informaria."""

    def run(self, call):
        out = super().run(call)
        return RuntimeOutcome(out.ok, out.structured, out.tool_calls, out.error, out.retry_after_s, out.detail,
                              Usage(input_tokens=600, output_tokens=400, cost_usd=0.001))


CONFIRM = {"intencao": "confirmar", "busca": None, "pessoas": None, "orcamento_reais": None, "restricoes": [],
           "resumo": "aceitou", "resposta": None, "conflito_com_perfil": None}
ORDER = {**CONFIRM, "intencao": "pedido", "busca": "pizza", "resumo": "pizza"}


class UsageTest(unittest.TestCase):
    def test_cost_per_client_and_share_of_sale(self):
        runtime = PaidRuntime(reasoning={"interpreter": ORDER})
        ledger = UsageLedger(usd_brl=5.0, margin_bps=3000)
        orch = build_orchestrator(runtime, InMemoryMemory(), RecordingSink(), customers=SQLiteCustomerMemory(),
                                  usage=ledger)
        ctx = {"name": "Bruno Lima", "age": None, "location": None, "preferences": [], "restrictions": []}

        def say(text):
            return orch.handle_message(SessionContext("s1", "t", "cli", "demo", text, initial_context=ctx))
        out = say("quero pizza")
        total = out.recommendations[0]["total_cents"]
        runtime.reasoning["interpreter"] = CONFIRM
        say("fechado")
        row = orch.usage_report("t")["clients"][0]
        calls = len(runtime.calls) + len(runtime.reasoning_calls)
        self.assertEqual(row["client_label"], "Bruno Lima")
        self.assertEqual(row["ai_calls"], calls)
        self.assertEqual(row["input_tokens"] + row["output_tokens"], 1000 * calls)
        self.assertEqual(row["ai_cost_usd_micros"], 1000 * calls)
        self.assertEqual(row["ai_cost_cents"], round(0.001 * calls * 5.0 * 100))
        self.assertEqual((row["sales"], row["sales_cents"]), (1, total))
        self.assertEqual(row["ai_cost_share_bps"], round(row["ai_cost_cents"] * 10000 / total))
        self.assertEqual(row["estimated_profit_cents"], round(total * 0.3) - row["ai_cost_cents"])

    def test_without_sale_share_is_unknown_and_tenants_are_isolated(self):
        orch = build_orchestrator(PaidRuntime(reasoning={"interpreter": ORDER}), InMemoryMemory(), RecordingSink(),
                                  customers=SQLiteCustomerMemory())
        orch.handle_message(SessionContext("s1", "t", None, "demo", "quero pizza"))
        row = orch.usage_report("t")["clients"][0]
        self.assertEqual(row["client_label"], "Atendimento anônimo")
        self.assertIsNone(row["ai_cost_share_bps"])
        self.assertIsNone(row["estimated_profit_cents"])
        self.assertEqual(orch.usage_report("outro")["clients"], [])

    def test_ai_activity_shows_tokens_and_cost_to_manager(self):
        sink = RecordingSink()
        orch = build_orchestrator(PaidRuntime(reasoning={"interpreter": ORDER}), InMemoryMemory(), sink,
                                  customers=SQLiteCustomerMemory())
        orch.handle_message(SessionContext("s1", "t", None, "demo", "quero pizza"))
        ai = [e for e in sink.events if e["type"] == "tool_activity" and e["payload"]["tool_name"] == "raciocinio_ia"]
        self.assertIn("1.000 tokens · US$ 0.00100", ai[0]["payload"]["summary"])
        self.assertEqual(ai[0]["visibility"], "admin")


if __name__ == "__main__":
    unittest.main()
