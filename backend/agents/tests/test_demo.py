import io
import unittest

from backend.agents.demo.cli import SCRIPT, main, run_conversation
from backend.agents.demo.runtime import DemoCatalogRuntime
from backend.agents.events import PAYLOAD_KEYS
from backend.agents.ports import RuntimeCall


def call(text, filters=None):
    ctx = {"dietary_filters": filters} if filters else {}
    return RuntimeCall("researcher", "t", "s", "", f"Pedido do cliente: {text}\nOrçamento: None", {},
                       allowed_tools=("offer_search",), context=ctx)


class DemoRuntimeTest(unittest.TestCase):
    def test_keyword_search_and_demo_provider(self):
        out = DemoCatalogRuntime().run(call("quero pizza"))
        names = {o["merchant_name"] for o in out.structured["offers"]}
        self.assertEqual(names, {"Pizzaria Forno Demo"})
        self.assertEqual(out.tool_calls[0].provider, "demo")
        self.assertNotIn("keywords", out.structured["offers"][0])

    def test_unknown_text_returns_whole_catalog(self):
        self.assertGreater(len(DemoCatalogRuntime().run(call("asdf")).structured["offers"]), 10)

    def test_generic_words_do_not_restrict_search(self):
        names = {o["merchant_name"] for o in DemoCatalogRuntime().run(call("quero comida para jantar")).structured["offers"]}
        self.assertGreaterEqual(len(names), 4)

    def test_dietary_filter(self):
        offers = DemoCatalogRuntime().run(call("quero pizza", ["VEGAN"])).structured["offers"]
        self.assertTrue(offers and all("vegan" in o["tags"] for o in offers))

    def test_without_tags_imitates_real_ifood(self):
        offers = DemoCatalogRuntime(with_tags=False).run(call("pizza")).structured["offers"]
        self.assertTrue(all(o["tags"] == [] and o["other_fees_cents"] is None for o in offers))

    def test_forced_failure(self):
        out = DemoCatalogRuntime(fail="quota").run(call("pizza"))
        self.assertEqual((out.ok, out.error), (False, "quota"))


class DemoConversationTest(unittest.TestCase):
    def test_script_runs_offline_and_events_follow_contract(self):
        buf = io.StringIO()
        sink = run_conversation(SCRIPT, out=buf, office=True)
        text = buf.getvalue()
        self.assertIn("MODO DEMONSTRAÇÃO OFFLINE", text)
        self.assertEqual(text.count("Bot:"), len(SCRIPT))
        self.assertIn("[dados de demonstração]", text)
        self.assertIn("DESCONTO SUGERIDO (não aplicado)", text)
        for e in sink.events:
            self.assertEqual(set(e["payload"]), PAYLOAD_KEYS[e["type"]])

    def test_realistic_mode_restriction_is_evaluated_by_ai(self):
        buf = io.StringIO()
        run_conversation(["quero pizza para 2 pessoas até R$ 200"], out=buf, with_tags=False,
                         initial_context={"restrictions": ["vegetariana"], "preferences": []})
        out = buf.getvalue()  # sem tags do iFood: a IA (simulada) avalia; dieta por escolha não gera aviso
        self.assertIn("Pizza Margherita", out)
        self.assertNotIn("Calabresa", out)

    def test_main_prompt_scenario_works_in_both_modes(self):
        for tags in (True, False):
            buf = io.StringIO()
            run_conversation(["quero comida pra 4 pessoas até R$ 120, com uma opção vegetariana"],
                             out=buf, with_tags=tags)
            self.assertIn("Escondidinho de Mandioca e Legumes", buf.getvalue(), tags)
            self.assertIn("R$ 115,60", buf.getvalue(), tags)

    def test_generic_order_with_pizza_preference_suggests_pizza(self):
        buf = io.StringIO()
        run_conversation(["quero comida para 2 pessoas até R$ 200"], out=buf, client_id="anon",
                         initial_context={"preferences": ["pizza"], "restrictions": []})
        out = buf.getvalue()
        self.assertIn("Sugiro Pizzaria Forno Demo", out)
        self.assertIn("combina com o que você gosta de pedir", out)  # argumento da IA simulada

    def test_preference_and_demo_history_are_not_repeated(self):
        buf = io.StringIO()
        run_conversation(["quero comida para 2 pessoas até R$ 200"], out=buf, client_id="client_demo_1",
                         initial_context={"preferences": ["pizza"], "restrictions": []})
        self.assertNotIn("pizza, pizza", buf.getvalue())

    def test_failure_mode_is_honest(self):
        buf = io.StringIO()
        run_conversation(["quero pizza"], out=buf, fail="quota")
        self.assertIn("tentar de novo", buf.getvalue())

    def test_cli_entrypoint_with_script(self):
        import contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            main(["--roteiro"])
        self.assertIn("Cliente: valeu", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
