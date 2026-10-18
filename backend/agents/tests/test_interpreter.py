import copy
import unittest

from backend.agents.bootstrap import build_orchestrator
from backend.agents.models import SessionContext, persona_key
from backend.agents.ports import RuntimeOutcome, ToolTrace
from backend.agents.testing.fakes import FakeRuntime, InMemoryMemory, RecordingSink
from backend.memory import SQLiteCustomerMemory


def offer(pid, name, price, merchant, mid):
    return {"product_id": pid, "name": name, "unit_price_cents": price, "merchant_id": mid, "merchant_name": merchant,
            "tags": [], "delivery_fee_cents": 0, "other_fees_cents": 0, "eta_minutes": 30}


def reading(**kw):
    base = {"intencao": "pedido", "busca": None, "pessoas": None, "orcamento_reais": None, "restricoes": [],
            "preferencias": [], "resumo": "pedido", "resposta": None, "conflito_com_perfil": None}
    return {**base, **kw}


class ByQueryRuntime(FakeRuntime):
    """Ofertas diferentes por termo de busca (para a nova busca pedida pelo Curador)."""

    def __init__(self, catalog, **kw):
        super().__init__(offers=[], **kw)
        self.catalog = catalog

    def run(self, call):
        if not call.allowed_tools:
            return super().run(call)
        self.calls.append(call)
        found = next((v for k, v in self.catalog.items() if f"Produto desejado: {k}." in call.prompt), [])
        trace = ToolTrace("c", "offer_search", "demo", "succeeded", 1, f"{len(found)} oferta(s)")
        return RuntimeOutcome(ok=True, structured={"offers": copy.deepcopy(found)}, tool_calls=(trace,))


def make(runtime, customers=None, initial_context=None, sid="s1"):
    sink = RecordingSink()
    memory = InMemoryMemory()
    orch = build_orchestrator(runtime, memory, sink, customers=customers or SQLiteCustomerMemory())

    def say(text):
        return orch.handle_message(SessionContext(sid, "t", "cli", "demo", text, initial_context=initial_context))
    return orch, sink, say


def kinds(sink, type_):
    return [e for e in sink.events if e["type"] == type_]


def talk(sink):
    return [(e["actor"]["id"], e["recipient"]["id"]) for e in kinds(sink, "agent_message")]


POKES = [offer("p1", "Poke Salmão", 4500, "Poke House", "ph"), offer("p2", "Poke de Tofu", 4200, "Poke House", "ph")]


class InterpreterTest(unittest.TestCase):
    def test_ai_understands_friends_and_vegan_friend(self):
        cur = {"items": [{"product_id": "p1", "fit": "sim", "reason": "poke", "atende_restricoes": []},
                         {"product_id": "p2", "fit": "sim", "reason": "poke", "atende_restricoes": ["vegan"]}]}
        rt = FakeRuntime(offers=POKES, reasoning={
            "interpreter": reading(busca="poke", pessoas=4, restricoes=[{"tipo": "vegano", "para_todos": False}],
                                   resumo="poke para 4, um vegano"),
            "curator": cur})
        _, sink, say = make(rt)
        out = say("to com 3 dos meus amigos e um deles é vegano, a gente quer poke")
        items = {i["name"]: i["quantity"] for i in out.recommendations[0]["items"]}
        self.assertEqual(sum(items.values()), 4)
        self.assertGreaterEqual(items.get("Poke de Tofu", 0), 1)  # ao menos um item vegano
        self.assertIn("vegana (para ao menos uma pessoa) (avaliada pela IA)", " ".join(out.recommendations[0]["reasons"]))
        self.assertFalse(any("vegana" in w for w in out.recommendations[0]["warnings"]))  # dieta por escolha: sem aviso
        self.assertIn(("interpreter", "orchestrator"), talk(sink))
        self.assertIn("Produto desejado: poke.", rt.calls[0].prompt)

    def test_typo_and_lactose_become_search_and_restriction(self):
        sorvetes = [offer("m", "Milk Shake Morango", 1800, "Sorveteria", "s"),
                    offer("f", "Sorbet de Limão", 1500, "Sorveteria", "s")]
        cur = {"items": [{"product_id": "m", "fit": "nao", "reason": "milk shake, leva leite"},
                         {"product_id": "f", "fit": "sim", "reason": "sorbet", "atende_restricoes": ["lactose-free"]}]}
        rt = FakeRuntime(offers=sorvetes, reasoning={
            "interpreter": reading(busca="sorvete", restricoes=[{"tipo": "sem lactose", "para_todos": True}],
                                   resumo="sorvete sem lactose"), "curator": cur})
        _, _, say = make(rt)
        out = say("tenho intelorancia a lactose, mas quero sorvete")
        self.assertEqual(out.recommendations[0]["items"][0]["name"], "Sorbet de Limão")
        self.assertIn("Produto desejado: sorvete.", rt.calls[0].prompt)
        self.assertNotIn("intelorancia", rt.calls[0].prompt.split("Produto desejado:")[1])
        self.assertIn("sem lactose", " ".join(out.recommendations[0]["warnings"]))

    def test_lactose_without_ai_evaluation_is_not_approved(self):
        rt = FakeRuntime(offers=[offer("m", "Sorvete de Creme", 1500, "Sorveteria", "s")], reasoning={
            "curator": {"items": [{"product_id": "m", "fit": "sim", "reason": "sorvete"}]}})
        _, _, say = make(rt)
        out = say("tenho intolerância a lactose e quero sorvete")
        self.assertEqual(out.recommendations, [])
        self.assertIn("sem lactose", out.reply_text)

    def test_follow_up_keeps_previous_dish(self):
        rt = FakeRuntime(offers=POKES, reasoning={"interpreter": reading(busca="poke")})
        _, _, say = make(rt)
        say("quero poke")
        rt.reasoning["interpreter"] = reading(intencao="ajuste", busca="poke",
                                              preferencias=["poke pronto, não monte o seu"])
        say("acha um montado")
        self.assertIn("Produto desejado: poke.", rt.calls[-1].prompt)

    def test_ai_budget_needs_money_in_the_text(self):
        rt = FakeRuntime(offers=POKES, reasoning={"interpreter": reading(busca="poke", orcamento_reais=10)})
        _, _, say = make(rt)
        out = say("quero poke")  # a IA inventou orçamento: ignorado
        self.assertTrue(out.recommendations)

    def test_chat_reply_from_ai(self):
        rt = FakeRuntime(reasoning={"interpreter": reading(intencao="conversa", resposta="Oi! O que vai ser hoje?")})
        _, _, say = make(rt)
        self.assertEqual(say("eae").reply_text, "Oi! O que vai ser hoje?")
        self.assertEqual(rt.calls, [])

    def test_chat_reply_with_price_is_discarded(self):
        rt = FakeRuntime(reasoning={"interpreter": reading(intencao="conversa", resposta="Pizza por R$ 5?")})
        _, _, say = make(rt)
        self.assertNotIn("R$", say("eae").reply_text)


class CuratorAsksResearcherTest(unittest.TestCase):
    def test_new_search_when_nothing_fits(self):
        rt = ByQueryRuntime({"sorvete": [offer("m", "Milk Shake", 1800, "S", "s")],
                             "sorbet": [offer("f", "Sorbet de Manga", 1600, "S", "s")]}, reasoning={
            "interpreter": reading(busca="sorvete", restricoes=[{"tipo": "sem lactose", "para_todos": True}]),
            "curator": lambda prompt: (
                {"items": [{"product_id": "m", "fit": "nao", "reason": "leite"}], "nova_busca": "sorbet"}
                if '"m"' in prompt else
                {"items": [{"product_id": "f", "fit": "sim", "reason": "sorbet", "atende_restricoes": ["lactose-free"]}]})})
        _, sink, say = make(rt)
        out = say("quero sorvete sem lactose")
        self.assertEqual(out.recommendations[0]["items"][0]["name"], "Sorbet de Manga")
        self.assertIn(("curator", "researcher"), talk(sink))
        statuses = [e["payload"]["status"] for e in kinds(sink, "conflict_detected")
                    if e["payload"]["agent_ids"] == ["curator", "researcher"]]
        self.assertEqual(statuses, ["open", "resolved"])
        self.assertEqual(len(rt.calls), 2)

    def test_new_search_without_results_keeps_old_offers(self):
        rt = ByQueryRuntime({"pizza": [offer("p", "Pizza Doce", 3000, "P", "p")]}, reasoning={
            "interpreter": reading(busca="pizza"),
            "curator": {"items": [{"product_id": "p", "fit": "parcial", "reason": "doce"}], "nova_busca": "calzone"}})
        _, sink, say = make(rt)
        out = say("quero pizza")
        self.assertEqual(out.recommendations[0]["items"][0]["name"], "Pizza Doce")
        self.assertEqual(len(rt.calls), 2)


class ConflictsAndSalesTest(unittest.TestCase):
    BIG = [offer("g", "Pizza Gigante", 9000, "Pizzaria", "pz")]

    def test_strategist_and_discount_disagree(self):
        rt = FakeRuntime(offers=self.BIG, reasoning={
            "sales_strategist": {"estrategia": "premium", "ordem": [], "argumento": "Capricho total.",
                                 "motivo": "cliente fiel", "precisa_incentivo": False},
            "discount_specialist": {"sugerir": True, "desconto_bps": 500, "motivo": "acima do mínimo"}})
        _, sink, say = make(rt)
        say("quero pizza até R$ 200")
        self.assertIn(("sales_strategist", "discount_specialist"), talk(sink))
        self.assertIn(("discount_specialist", "sales_strategist"), talk(sink))
        conf = [e["payload"] for e in kinds(sink, "conflict_detected")
                if e["payload"]["agent_ids"] == ["sales_strategist", "discount_specialist"]]
        self.assertEqual([c["status"] for c in conf], ["open", "resolved"])

    def test_budget_conflict_waits_for_customer_then_resolves(self):
        rt = FakeRuntime(offers=self.BIG)
        _, sink, say = make(rt)
        out = say("quero pizza para 1 pessoa até R$ 50")
        self.assertIn("R$ 90,00", out.reply_text)
        self.assertEqual([e["payload"]["status"] for e in kinds(sink, "conflict_detected")], ["open"])
        say("pode ser até R$ 100")
        self.assertEqual([e["payload"]["status"] for e in kinds(sink, "conflict_detected")], ["open", "resolved"])

    def test_confirmation_records_sale_for_strategy(self):
        customers = SQLiteCustomerMemory()
        rt = FakeRuntime(offers=self.BIG, reasoning={
            "sales_strategist": {"estrategia": "premium", "ordem": [], "argumento": "Capricho.", "motivo": "x"}})
        _, sink, say = make(rt, customers)
        say("quero pizza até R$ 200")
        rt.reasoning["interpreter"] = reading(intencao="confirmar")
        out = say("fechado, pode ser")
        self.assertIn("Anotei seu pedido de Pizzaria", out.reply_text)
        self.assertIn(("premium", 1, 1), customers.strategy_performance("t"))
        self.assertTrue(any("Venda fechada" in e["payload"]["summary"] for e in kinds(sink, "agent_message")))

    def test_strategy_performance_is_reported_by_memory(self):
        customers = SQLiteCustomerMemory()
        customers.record_offer("t", "outro", "s0", "favorito", 5000, True)
        _, sink, say = make(FakeRuntime(offers=self.BIG), customers)
        say("quero pizza até R$ 200")
        perf = [e["payload"]["summary"] for e in kinds(sink, "agent_message")
                if e["payload"]["summary"].startswith("Desempenho das estratégias:")]
        self.assertEqual(perf, ["Desempenho das estratégias: Favorito do cliente 1/1"])


class PersonaTest(unittest.TestCase):
    def test_fictitious_customer_profile_restriction_applies(self):
        customers = SQLiteCustomerMemory()
        key = persona_key("cli", "Carla Mendes")
        customers.declare("t", key, ("lactose-free",), ("comida leve",))
        rt = FakeRuntime(offers=[offer("m", "Sorvete de Creme", 1500, "S", "s")])
        _, sink, say = make(rt, customers, {"name": "Carla Mendes", "age": None, "location": None,
                                            "preferences": [], "restrictions": []})
        out = say("quero sorvete")
        self.assertEqual(out.recommendations, [])  # sem prova de "sem lactose", não aprova
        self.assertTrue(any(e["payload"]["summary"].startswith("Cadastro do cliente: restrições sem lactose")
                            for e in kinds(sink, "agent_message")))

    def test_persona_history_is_separate_from_other_personas(self):
        self.assertNotEqual(persona_key("cli", "Ana Souza"), persona_key("cli", "Bruno Lima"))
        self.assertEqual(persona_key("cli", None), "cli")

    def test_lifestyle_restriction_yields_to_explicit_order(self):
        customers = SQLiteCustomerMemory()
        key = persona_key("cli", "Ana Souza")
        customers.declare("t", key, ("vegetarian",), ())
        rt = FakeRuntime(offers=[offer("c", "Picanha", 6000, "Churrascaria", "c")], reasoning={
            "interpreter": reading(busca="picanha", conflito_com_perfil="cadastro vegetariano pedindo picanha")})
        _, sink, say = make(rt, customers, {"name": "Ana Souza", "age": None, "location": None,
                                            "preferences": [], "restrictions": []})
        out = say("quero picanha")
        self.assertEqual(out.recommendations[0]["items"][0]["name"], "Picanha")
        conf = [e["payload"]["agent_ids"] for e in kinds(sink, "conflict_detected")]
        self.assertIn(["interpreter", "customer_memory"], conf)


if __name__ == "__main__":
    unittest.main()


class ExtrasTest(unittest.TestCase):
    CATALOG = {
        "hambúrguer": [offer("b1", "X-Burger", 2500, "Lanchonete A", "a"), offer("b2", "Cheeseburger", 2000, "Burger B", "b")],
        "coca zero": [offer("c1", "Coca-Cola Zero Lata", 700, "Lanchonete A", "a"),
                      offer("c9", "Coca-Cola Zero 2L", 1400, "Mercado", "m")],
    }

    CURATOR = {"items": [{"product_id": p, "fit": "sim", "reason": "ok"} for p in ("b1", "b2", "c1", "c9")]}

    def runtime(self, **reading_kw):
        return ByQueryRuntime(self.CATALOG, reasoning={
            "interpreter": reading(busca="hambúrguer", complementos=["coca zero"], **reading_kw),
            "curator": self.CURATOR})

    def test_burger_with_coke_from_the_same_restaurant_comes_first(self):
        rt = self.runtime()
        _, sink, say = make(rt)
        out = say("quero hambúrguer com coca zero")
        first = out.recommendations[0]
        self.assertEqual({i["name"] for i in first["items"]}, {"X-Burger", "Coca-Cola Zero Lata"})
        self.assertIn("Inclui coca zero", first["reasons"])
        other = next(r for r in out.recommendations if r["merchant_id"] == "b")
        self.assertIn("Sem 'coca zero' neste restaurante na busca; peça à parte", other["warnings"])
        self.assertEqual(len(rt.calls), 2)  # prato + complemento
        self.assertNotIn("Mercado", [r["merchant_name"] for r in out.recommendations])

    def test_and_the_coke_keeps_the_burger(self):
        rt = ByQueryRuntime(self.CATALOG, reasoning={"interpreter": reading(busca="hambúrguer"),
                                                     "curator": self.CURATOR})
        _, _, say = make(rt)
        say("quero hambúrguer")
        rt.reasoning["interpreter"] = reading(intencao="ajuste", busca="hambúrguer", complementos=["coca zero"])
        out = say("e a coca")
        self.assertEqual({i["name"] for i in out.recommendations[0]["items"]}, {"X-Burger", "Coca-Cola Zero Lata"})


class RestrictionsByAiTest(unittest.TestCase):
    BURGERS = [offer("f", "Hambúrguer de falafel", 1190, "Veg", "v"), offer("s", "Smash Burger", 2500, "Veg", "v")]

    def test_intolerance_accepts_items_ai_says_are_safe_with_short_warning(self):
        cur = {"items": [{"product_id": "f", "fit": "sim", "reason": "x", "viola_restricoes": ["intolerância a grão de bico"]},
                         {"product_id": "s", "fit": "sim", "reason": "x", "viola_restricoes": []}]}
        rt = FakeRuntime(offers=self.BURGERS, reasoning={"curator": cur, "interpreter": reading(
            busca="hambúrguer", restricoes=[{"tipo": "intolerância a grão de bico", "para_todos": True}])})
        _, _, say = make(rt)
        out = say("tenho intolerância a grão de bico, quero hambúrguer")
        self.assertEqual([i["name"] for i in out.recommendations[0]["items"]], ["Smash Burger"])
        self.assertTrue(any("avaliada pela IA: confirme" in w for w in out.recommendations[0]["warnings"]))

    def test_vegan_judged_by_ai_has_no_unverified_warning(self):
        cur = {"items": [{"product_id": "f", "fit": "sim", "reason": "x", "atende_restricoes": ["vegan"]},
                         {"product_id": "s", "fit": "sim", "reason": "x", "atende_restricoes": []}]}
        rt = FakeRuntime(offers=self.BURGERS, reasoning={"curator": cur, "interpreter": reading(
            busca="hambúrguer", restricoes=[{"tipo": "vegano", "para_todos": True}])})
        _, _, say = make(rt)
        out = say("sou vegano, quero hambúrguer")
        rec = out.recommendations[0]
        self.assertEqual([i["name"] for i in rec["items"]], ["Hambúrguer de falafel"])
        self.assertFalse(any("não comprovada" in w or "Não encontrei exatamente" in w for w in rec["warnings"]))
        self.assertNotIn("Orçamento não informado", rec["warnings"])

    def test_no_profile_conflict_without_registered_restrictions(self):
        rt = FakeRuntime(offers=self.BURGERS, reasoning={"interpreter": reading(
            busca="hambúrguer", conflito_com_perfil="sugestão anterior tinha grão de bico")})
        _, sink, say = make(rt)
        say("quero hambúrguer")
        self.assertEqual(kinds(sink, "conflict_detected"), [])


class CorrectionsTest(unittest.TestCase):
    def test_customer_can_retract_a_restriction_explicitly(self):
        burgers = [offer("v", "Burger Vegano", 3000, "A", "a"), offer("c", "X-Bacon", 2500, "A", "a")]
        cur = {"items": [{"product_id": "v", "fit": "sim", "reason": "x", "atende_restricoes": ["vegan"]},
                         {"product_id": "c", "fit": "sim", "reason": "x"}]}
        rt = FakeRuntime(offers=burgers, reasoning={"curator": cur, "interpreter": reading(
            busca="hambúrguer", restricoes=[{"tipo": "vegano", "para_todos": True}])})
        _, sink, say = make(rt)
        self.assertEqual(say("sou vegano, quero hambúrguer").recommendations[0]["items"][0]["name"], "Burger Vegano")
        rt.reasoning["interpreter"] = reading(intencao="ajuste", busca="hambúrguer", remover_restricoes=["vegano"])
        out = say("não sou vegano não, errei")
        self.assertEqual(out.recommendations[0]["items"][0]["name"], "X-Bacon")
        self.assertTrue(any("removida a pedido do cliente: vegana" in e["payload"]["summary"]
                            for e in kinds(sink, "memory_changed")))

    def test_combo_that_includes_the_drink_needs_no_extra(self):
        catalog = {"hambúrguer": [offer("x", "X-Burger", 2000, "A", "a"), offer("k", "Combo X-Burger + Coca", 2900, "A", "a")],
                   "coca": [offer("z", "Coca-Cola Lata", 600, "B", "b")]}
        cur = {"items": [{"product_id": "x", "fit": "sim", "reason": "x"},
                         {"product_id": "k", "fit": "sim", "reason": "combo", "inclui": ["coca"]},
                         {"product_id": "z", "fit": "sim", "reason": "coca"}]}
        rt = ByQueryRuntime(catalog, reasoning={"curator": cur, "interpreter": reading(busca="hambúrguer", complementos=["coca"])})
        _, _, say = make(rt)
        rec = say("hambúrguer com coca").recommendations[0]
        self.assertEqual([i["name"] for i in rec["items"]], ["Combo X-Burger + Coca"])
        self.assertIn("Inclui coca", rec["reasons"])
