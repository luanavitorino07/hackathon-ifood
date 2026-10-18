import tempfile
import threading
import unittest
from pathlib import Path

from backend.agents.ports import KnowledgePort, MemoryPort, RevisionConflict
from backend.memory import MarkdownKnowledgeBase, SQLiteMemory, default_knowledge_base


class SQLiteMemoryTest(unittest.TestCase):
    def setUp(self):
        self.mem = SQLiteMemory()

    def test_is_a_memory_port(self):
        self.assertIsInstance(self.mem, MemoryPort)

    def test_unknown_session_is_empty_revision_zero(self):
        snap = self.mem.load("nada")
        self.assertEqual((snap.state, snap.revision), ({}, 0))

    def test_patch_replaces_top_level_keys_only(self):
        self.mem.save_patch("s", {"a": {"x": 1, "y": 2}, "b": 1}, 0, "t")
        self.mem.save_patch("s", {"a": {"x": 9}}, 1, "t")
        snap = self.mem.load("s")
        self.assertEqual((snap.state, snap.revision), ({"a": {"x": 9}, "b": 1}, 2))

    def test_none_is_stored_as_null_and_key_kept(self):
        self.mem.save_patch("s", {"a": 1}, 0, "t")
        self.mem.save_patch("s", {"a": None}, 1, "t")
        self.assertEqual(self.mem.load("s").state, {"a": None})

    def test_conflict_writes_nothing(self):
        self.mem.save_patch("s", {"a": 1}, 0, "t")
        with self.assertRaises(RevisionConflict):
            self.mem.save_patch("s", {"a": 2}, 0, "t")
        snap = self.mem.load("s")
        self.assertEqual((snap.state, snap.revision), ({"a": 1}, 1))
        self.assertEqual(len(self.mem.audit("s")), 1)

    def test_load_returns_independent_copy(self):
        self.mem.save_patch("s", {"a": [1]}, 0, "t")
        self.mem.load("s").state["a"].append(2)
        self.assertEqual(self.mem.load("s").state, {"a": [1]})

    def test_rejects_non_json_values(self):
        with self.assertRaises(ValueError):
            self.mem.save_patch("s", {"a": object()}, 0, "t")
        self.assertEqual(self.mem.load("s").revision, 0)

    def test_audit_records_author_and_keys_without_values(self):
        self.mem.save_patch("s", {"constraints": {"budget_cents": 100}}, 0, "api")
        self.mem.save_patch("s", {"shown": {}, "audit": {}}, 1, "orchestrator")
        log = self.mem.audit("s")
        self.assertEqual([(e["revision"], e["author"], e["keys"]) for e in log],
                         [(1, "api", ["constraints"]), (2, "orchestrator", ["audit", "shown"])])
        self.assertNotIn("100", str(log))

    def test_sessions_are_isolated(self):
        self.mem.save_patch("s1", {"a": 1}, 0, "t")
        self.assertEqual(self.mem.load("s2").state, {})

    def test_concurrent_writers_only_one_wins_each_revision(self):
        wins, errors = [], []

        def writer(i):
            try:
                wins.append(self.mem.save_patch("s", {"who": i}, 0, f"w{i}"))
            except RevisionConflict:
                errors.append(i)

        threads = [threading.Thread(target=writer, args=(i,)) for i in range(8)]
        [t.start() for t in threads]
        [t.join() for t in threads]
        self.assertEqual((len(wins), len(errors)), (1, 7))
        self.assertEqual(self.mem.load("s").revision, 1)

    def test_persists_across_reopen(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "mem.db"
            m = SQLiteMemory(path)
            m.save_patch("s", {"constraints": {"budget_cents": 12000}}, 0, "api")
            m.close()
            again = SQLiteMemory(path)
            self.assertEqual(again.load("s").state["constraints"]["budget_cents"], 12000)
            again.close()


class KnowledgeBaseTest(unittest.TestCase):
    def setUp(self):
        self.kb = MarkdownKnowledgeBase()

    def test_is_a_knowledge_port(self):
        self.assertIsInstance(self.kb, KnowledgePort)
        self.assertIs(default_knowledge_base(), default_knowledge_base())

    def test_discount_policy_parameters_are_retrieved(self):
        hits = self.kb.search("t", "política de desconto margem pedido mínimo", ("desconto",))
        params = next(h.data for h in hits if h.data)
        self.assertEqual((params["desconto_bps"], params["pedido_minimo_centavos"]), (500, 8000))
        self.assertTrue(all(h.document_id == "politica_comercial_demo" for h in hits[:2]))

    def test_personalization_strategy_is_retrieved(self):
        hits = self.kb.search("t", "personalização preferência do cliente histórico", ("personalização",))
        self.assertEqual(hits[0].document_id, "estrategias_venda_demo")
        self.assertIn("Personalização", hits[0].excerpt)

    def test_unrelated_query_returns_nothing(self):
        self.assertEqual(self.kb.search("t", "xyzzy foguete marciano"), [])

    def test_k_limits_results_and_scores_sorted(self):
        hits = self.kb.search("t", "desconto restrições cliente", k=2)
        self.assertLessEqual(len(hits), 2)
        self.assertEqual([h.score for h in hits], sorted([h.score for h in hits], reverse=True))

    def test_custom_directory(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, "x.md").write_text("# Doc X\n\n## Seção\ntopics: frete\n\nFrete grátis acima de R$ 50.\n",
                                       encoding="utf-8")
            hits = MarkdownKnowledgeBase(d).search("t", "frete grátis")
            self.assertEqual((hits[0].document_id, hits[0].title), ("x", "Doc X"))


if __name__ == "__main__":
    unittest.main()


class DemoSeedTest(unittest.TestCase):
    def test_fictitious_customers_are_loaded_once(self):
        from backend.agents.models import persona_key
        from backend.memory.customer_memory import SQLiteCustomerMemory
        from backend.memory.demo_seed import PERSONAS, seed_demo_customers
        memory = SQLiteCustomerMemory()
        seed_demo_customers(memory)
        before = memory.strategy_performance("tenant_demo")
        seed_demo_customers(memory)  # idempotente
        self.assertEqual(memory.strategy_performance("tenant_demo"), before)
        carla = memory.profile("tenant_demo", persona_key("client_demo_1", "Carla Mendes"))
        self.assertEqual(carla.declared_restrictions, ("lactose-free",))
        self.assertEqual(carla.requests, 4)
        self.assertEqual(len(PERSONAS), 4)

    def test_acceptance_marks_strategy(self):
        from backend.memory.customer_memory import SQLiteCustomerMemory
        memory = SQLiteCustomerMemory()
        memory.record_offer("t", "c", "s1", "premium", 5000)
        self.assertEqual(memory.strategy_performance("t"), [("premium", 1, 0)])
        self.assertEqual(memory.record_acceptance("t", "c", "s1"), "premium")
        self.assertEqual(memory.strategy_performance("t"), [("premium", 1, 1)])
        self.assertIsNone(memory.record_acceptance("t", "c", "outra"))
