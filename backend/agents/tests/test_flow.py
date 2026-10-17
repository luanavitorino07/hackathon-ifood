import unittest

from backend.agents.bootstrap import build_orchestrator
from backend.agents.events import PAYLOAD_KEYS
from backend.agents.models import Constraints, SessionContext
from backend.agents.testing.fakes import InMemoryMemory, FakeRuntime, RecordingSink


def make(text, runtime=None, mode="demo", constraints=Constraints()):
    sink, memory = RecordingSink(), InMemoryMemory()
    orch = build_orchestrator(runtime or FakeRuntime(), memory, sink)
    ctx = SessionContext("sess_1", "tenant_demo", None, mode, text, constraints=constraints)
    return orch, ctx, sink, memory


class FlowTest(unittest.TestCase):
    def test_happy_path_vegetarian_within_budget(self):
        orch, ctx, sink, memory = make("Quero comida para quatro pessoas, até R$ 120, com uma opção vegetariana")
        out = orch.handle_message(ctx)
        self.assertEqual(out.session_status, "active")
        self.assertTrue(out.recommendations)
        for rec in out.recommendations:
            self.assertLessEqual(rec["total_cents"], 12000)
            self.assertEqual(rec["data_origin"], "demo")
            self.assertEqual(sum(i["quantity"] for i in rec["items"]), 4)
        types = sink.types()
        for t in ("agent_status", "agent_message", "tool_activity", "recommendations_ready",
                  "decision_made", "chat_message"):
            self.assertIn(t, types)
        self.assertGreater(memory.load("sess_1").revision, 0)

    def test_events_match_closed_contract(self):
        orch, ctx, sink, _ = make("Quero para 2 pessoas até R$ 100")
        orch.handle_message(ctx)
        for e in sink.events:
            self.assertEqual(set(e["payload"]), PAYLOAD_KEYS[e["type"]])
            if e["type"] == "agent_message":
                self.assertEqual(e["actor"]["kind"], "agent")
                self.assertEqual(e["recipient"]["kind"], "agent")
            if e["type"] == "chat_message":
                self.assertEqual(e["visibility"], "both")
            else:
                self.assertIn(e["visibility"], ("admin", "both"))

    def test_budget_too_low_asks_customer(self):
        orch, ctx, sink, _ = make("Quero para quatro pessoas até R$ 20")
        out = orch.handle_message(ctx)
        self.assertEqual(out.session_status, "waiting_customer")
        self.assertEqual(out.recommendations, [])

    def test_quota_error_degrades_with_retryable_error(self):
        orch, ctx, sink, _ = make("Quero um lanche", FakeRuntime(error="quota"))
        out = orch.handle_message(ctx)
        err = [e for e in sink.events if e["type"] == "error"][0]["payload"]
        self.assertEqual((err["code"], err["retryable"]), ("LLM_QUOTA", True))
        self.assertEqual(out.session_status, "active")

    def test_real_mode_rejects_unverified_origin(self):
        orch, ctx, sink, _ = make("Quero um lanche", mode="real")
        out = orch.handle_message(ctx)
        self.assertEqual(out.recommendations, [])
        self.assertIn("error", sink.types())

    def test_real_mode_accepts_proven_mcp_origin(self):
        orch, ctx, _, _ = make("Quero para 2 pessoas até R$ 100", FakeRuntime(provider="ifood_mcp"), mode="real")
        out = orch.handle_message(ctx)
        self.assertEqual(out.recommendations[0]["data_origin"], "ifood_mcp")

    def test_invalid_offers_are_dropped(self):
        bad = [{"product_id": "x", "name": "Sem preço", "merchant_id": "m", "merchant_name": "M"}]
        orch, ctx, _, _ = make("Quero um lanche", FakeRuntime(offers=bad))
        self.assertEqual(orch.handle_message(ctx).session_status, "waiting_customer")

    def test_customer_constraints_not_overridden(self):
        orch, ctx, _, memory = make("Quero um lanche até R$ 500", constraints=Constraints(budget_cents=3000))
        orch.handle_message(ctx)
        self.assertEqual(memory.load("sess_1").state["constraints"]["budget_cents"], 3000)

    def test_runtime_call_carries_timeout_and_minimal_context(self):
        runtime = FakeRuntime()
        sink, memory = RecordingSink(), InMemoryMemory()
        ctx = SessionContext("sess_1", "tenant_demo", "client_x", "demo", "Quero um lanche",
                             initial_context={"location": {"lat": -23.5, "lng": -46.6}, "email": "a@b.c"})
        build_orchestrator(runtime, memory, sink).handle_message(ctx)
        call = runtime.calls[0]
        self.assertEqual(call.timeout_s, 60.0)
        self.assertEqual(call.context, {"location": {"lat": -23.5, "lng": -46.6}})
        self.assertNotIn("client_x", call.prompt)
        self.assertEqual(call.allowed_tools, ("offer_search",))

    def test_contexts_do_not_share_mutable_default(self):
        from backend.agents.ports import RuntimeCall
        a, b = RuntimeCall("a", "t", "s", "", "", {}), RuntimeCall("a", "t", "s", "", "", {})
        self.assertIsNot(a.context, b.context)

    def test_runtime_detail_stays_out_of_events(self):
        orch, ctx, sink, _ = make("Quero um lanche", FakeRuntime(error="timeout"))
        orch.handle_message(ctx)
        self.assertNotIn("falha simulada", str(sink.events))

    def test_catalog_lists_registered_agents(self):
        orch, *_ = make("x")
        self.assertEqual([a["agent_id"] for a in orch.catalog()], ["researcher", "planner", "auditor"])


if __name__ == "__main__":
    unittest.main()
