import unittest

from backend.agents.bootstrap import build_orchestrator
from backend.agents.models import SessionContext
from backend.agents.testing.fakes import FakeRuntime, InMemoryMemory, RecordingSink

FIRST = "Quero comida para 2 pessoas até R$ 100"


class Conversation:
    def __init__(self, runtime=None, mode="demo", initial_context=None, session_id="sess_1", memory=None):
        self.runtime = runtime or FakeRuntime(provider="ifood_mcp" if mode == "real" else "demo")
        self.memory = memory or InMemoryMemory()
        self.sink = RecordingSink()
        self.orch = build_orchestrator(self.runtime, self.memory, self.sink)
        self.mode, self.ic, self.sid = mode, initial_context, session_id

    def say(self, text, initial_context="same"):
        ic = self.ic if initial_context == "same" else initial_context
        return self.orch.handle_message(SessionContext(self.sid, "t", None, self.mode, text, initial_context=ic))

    @property
    def searches(self):
        return len(self.runtime.calls)

    def state(self):
        return self.memory.load(self.sid).state


class ResumptionTest(unittest.TestCase):
    def test_party_size_change_reuses_search(self):
        c = Conversation()
        c.say(FIRST)
        out = c.say("Agora são 3 pessoas")
        self.assertEqual(c.searches, 1)
        self.assertEqual(c.state()["constraints"]["party_size"], 3)
        self.assertEqual(sum(i["quantity"] for i in out.recommendations[0]["items"]), 3)

    def test_budget_change_reuses_search(self):
        c = Conversation()
        c.say(FIRST)
        out = c.say("pode ser até R$ 70")
        self.assertEqual(c.searches, 1)
        self.assertTrue(all(r["total_cents"] <= 7000 for r in out.recommendations))

    def test_party_then_budget_in_sequence_still_one_search(self):
        c = Conversation()
        c.say(FIRST)
        c.say("Agora são 3 pessoas")
        c.say("e até R$ 150")
        self.assertEqual(c.searches, 1)
        self.assertEqual((c.state()["constraints"]["party_size"], c.state()["constraints"]["budget_cents"]),
                         (3, 15000))

    def test_cheaper_follow_up_does_not_search(self):
        c = Conversation()
        c.say(FIRST)
        c.say("tem algo mais barato?")
        self.assertEqual(c.searches, 1)

    def test_restrictions_kept_when_reusing(self):
        c = Conversation(initial_context={"restrictions": ["vegetariana"], "preferences": []})
        c.say("Quero comida para 2 pessoas até R$ 100")
        out = c.say("Agora são 3 pessoas")
        self.assertEqual(c.searches, 1)
        self.assertEqual(c.state()["constraints"]["dietary"], ["vegetarian"])
        names = [i["name"] for r in out.recommendations for i in r["items"]]
        self.assertTrue(names and all("vegetariano" in n.lower() or "Pizza" in n for n in names))

    def test_reuse_is_visible_to_manager(self):
        c = Conversation()
        c.say(FIRST)
        c.say("Agora são 3 pessoas")
        msgs = [e["payload"]["summary"] for e in c.sink.events if e["type"] == "agent_message"]
        self.assertTrue(any("Pesquisa reaproveitada" in m for m in msgs))

    def test_dish_change_searches_again(self):
        c = Conversation()
        c.say(FIRST)
        c.say("na verdade quero pizza")
        self.assertEqual(c.searches, 2)

    def test_dietary_filter_change_searches_again(self):
        c = Conversation()
        c.say(FIRST)
        c.say("tudo vegetariano")
        self.assertEqual(c.searches, 2)

    def test_location_change_searches_again(self):
        c = Conversation(initial_context={"location": "São Carlos, SP", "preferences": [], "restrictions": []})
        c.say(FIRST)
        c.say("Agora são 3 pessoas", initial_context={"location": "Araraquara, SP", "preferences": [],
                                                      "restrictions": []})
        self.assertEqual(c.searches, 2)

    def test_explicit_refresh_searches_again(self):
        c = Conversation()
        c.say(FIRST)
        c.say("busca de novo, quero ver outras opções")
        self.assertEqual(c.searches, 2)

    def test_expired_search_is_not_reused(self):
        c = Conversation()
        c.say(FIRST)
        snap = c.memory.load("sess_1")
        last = dict(snap.state["last_search"], at=snap.state["last_search"]["at"] - 3600)
        c.memory.save_patch("sess_1", {"last_search": last}, snap.revision, "test")
        c.say("Agora são 3 pessoas")
        self.assertEqual(c.searches, 2)

    def test_sessions_do_not_share_searches(self):
        memory = InMemoryMemory()
        a = Conversation(memory=memory, session_id="a")
        b = Conversation(memory=memory, session_id="b")
        a.say(FIRST)
        b.say("Agora são 3 pessoas")
        self.assertEqual((a.searches, b.searches), (1, 1))

    def test_failure_is_not_cached(self):
        c = Conversation(runtime=FakeRuntime(error="quota"))
        c.say(FIRST)
        c.runtime.error = None
        out = c.say("Agora são 3 pessoas")
        self.assertEqual(c.searches, 2)
        self.assertTrue(out.recommendations)

    def test_empty_search_is_not_reused(self):
        c = Conversation(runtime=FakeRuntime(offers=[]))
        c.say(FIRST)
        c.say("Agora são 3 pessoas")
        self.assertEqual(c.searches, 2)

    def test_real_session_never_reuses_demo_results(self):
        c = Conversation(mode="real")
        c.say(FIRST)
        snap = c.memory.load("sess_1")
        c.memory.save_patch("sess_1", {"data_origin": "demo"}, snap.revision, "test")
        c.say("Agora são 3 pessoas")
        self.assertEqual(c.searches, 2)

    def test_real_session_reuses_proven_ifood_results(self):
        c = Conversation(mode="real")
        c.say(FIRST)
        out = c.say("Agora são 3 pessoas")
        self.assertEqual(c.searches, 1)
        self.assertEqual(out.recommendations[0]["data_origin"], "ifood_mcp")


if __name__ == "__main__":
    unittest.main()
