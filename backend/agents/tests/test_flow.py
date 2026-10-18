import unittest

from backend.agents.bootstrap import build_orchestrator
from backend.agents.events import PAYLOAD_KEYS
from backend.agents.auditor import audit_recommendation
from backend.agents.models import Constraints, Offer, SessionContext, WorkingState
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

    def test_caller_constraints_kept_when_message_is_silent(self):
        orch, ctx, _, memory = make("Quero um lanche", constraints=Constraints(budget_cents=3000))
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
        ids = [a["agent_id"] for a in orch.catalog()]
        self.assertEqual(ids[:6], ["orchestrator", "interpreter", "researcher", "curator", "planner", "auditor"])
        self.assertIn("customer_memory", ids)


def second_message(orch, ctx, text):
    return orch.handle_message(SessionContext(ctx.session_id, ctx.tenant_id, None, ctx.mode, text,
                                              initial_context=ctx.initial_context))


def saved(memory):
    return memory.load("sess_1").state["constraints"]


class ConstraintsTest(unittest.TestCase):
    def test_unknown_restriction_blocks_approval_and_asks_customer(self):
        orch, ctx, sink, memory = make("Quero para 2 pessoas até R$ 100")
        ctx = SessionContext("sess_1", "t", None, "demo", ctx.message_text,
                             initial_context={"restrictions": ["alergia a amendoim"]})
        out = orch.handle_message(ctx)
        self.assertEqual(out.session_status, "waiting_customer")
        self.assertEqual(out.recommendations, [])
        self.assertIn("alergia a amendoim", out.reply_text)
        self.assertNotIn("recommendations_ready", sink.types())
        self.assertIn("alergia-a-amendoim", saved(memory)["dietary"])

    def test_restriction_verified_by_offer_tags_is_approved(self):
        offers = [{"product_id": "p1", "name": "Prato", "unit_price_cents": 3000, "merchant_id": "m",
                   "merchant_name": "M", "tags": ["Gluten-Free"], "delivery_fee_cents": 0,
                   "other_fees_cents": 0, "eta_minutes": 20}]
        orch, ctx, _, _ = make("Quero para 2 pessoas até R$ 100", FakeRuntime(offers=offers))
        ctx = SessionContext("sess_1", "t", None, "demo", ctx.message_text,
                             initial_context={"restrictions": ["sem glúten"]})
        self.assertEqual(len(orch.handle_message(ctx).recommendations), 1)

    def test_soft_restriction_without_tags_is_recommended_but_unverified(self):
        offers = [{"product_id": "p1", "name": "Salada", "unit_price_cents": 2000, "merchant_id": "m",
                   "merchant_name": "M", "tags": [], "delivery_fee_cents": 500,
                   "other_fees_cents": None, "eta_minutes": 30}]
        runtime = FakeRuntime(offers=offers)
        orch, ctx, sink, _ = make("Quero para 2 pessoas até R$ 100", runtime)
        ctx = SessionContext("sess_1", "t", None, "demo", ctx.message_text,
                             initial_context={"restrictions": ["vegetariana"]})
        out = orch.handle_message(ctx)
        self.assertEqual(runtime.calls[0].context["dietary_filters"], ["VEGETARIAN"])
        rec = out.recommendations[0]
        self.assertTrue(any("não comprovada" in w for w in rec["warnings"]))
        self.assertTrue(any(w.startswith("Taxa de serviço") for w in rec["warnings"]))
        self.assertNotIn("Atende", " ".join(r for r in rec["reasons"] if "vegetarian" in r.lower()))
        self.assertIn("não comprovada", out.reply_text)
        self.assertEqual(rec["total_cents"], 2 * 2000 + 500)

    def test_one_vegetarian_option_does_not_filter_whole_search(self):
        runtime = FakeRuntime()
        orch, ctx, _, _ = make("quero comida para 4 pessoas até R$ 120, com uma opção vegetariana", runtime)
        orch.handle_message(ctx)
        self.assertNotIn("dietary_filters", runtime.calls[0].context)

    def test_one_vegetarian_option_without_tags_uses_item_from_filtered_search(self):
        from backend.agents.demo.runtime import DemoCatalogRuntime
        runtime = DemoCatalogRuntime(with_tags=False)
        orch, ctx, _, _ = make("quero comida pra 4 pessoas até R$ 120, com uma opção vegetariana", runtime)
        out = orch.handle_message(ctx)
        self.assertEqual([c.context.get("dietary_filters") for c in runtime.calls], [None, ["VEGETARIAN"]])
        names = [i["name"] for i in out.recommendations[0]["items"]]
        self.assertIn("Escondidinho de Mandioca e Legumes", names)
        self.assertTrue(any("não comprovada" in w for w in out.recommendations[0]["warnings"]))

    def test_all_vegetarian_makes_a_single_filtered_search(self):
        runtime = FakeRuntime()
        orch, ctx, _, _ = make("quero comida vegetariana para 2 pessoas até R$ 100", runtime)
        orch.handle_message(ctx)
        self.assertEqual([c.context.get("dietary_filters") for c in runtime.calls], [["VEGETARIAN"]])

    def test_economy_option_is_really_the_cheapest_combination(self):
        offers = [{"product_id": p, "name": p, "unit_price_cents": c, "merchant_id": "m", "merchant_name": "M",
                   "tags": t, "delivery_fee_cents": 0, "other_fees_cents": 0, "eta_minutes": 30}
                  for p, c, t in (("pf", 2790, []), ("veg", 3190, ["vegetarian"]), ("caro", 3690, []))]
        orch, ctx, _, _ = make("quero comida para 4 pessoas até R$ 120, com uma opção vegetariana",
                               FakeRuntime(offers=offers))
        recs = orch.handle_message(ctx).recommendations
        self.assertEqual(recs[0]["total_cents"], 3190 + 3 * 2790)

    def test_gluten_and_vegan_become_search_filters(self):
        runtime = FakeRuntime()
        orch, ctx, _, memory = make("Quero para 2 pessoas até R$ 100", runtime)
        ctx = SessionContext("sess_1", "t", None, "demo", ctx.message_text,
                             initial_context={"restrictions": ["vegana", "sem glúten"]})
        orch.handle_message(ctx)
        self.assertEqual(runtime.calls[0].context["dietary_filters"], ["GLUTEN_FREE", "VEGAN"])

    def test_unknown_delivery_fee_keeps_total_unknown(self):
        offers = [{"product_id": "p1", "name": "Prato", "unit_price_cents": 2000, "merchant_id": "m",
                   "merchant_name": "M", "tags": [], "delivery_fee_cents": None,
                   "other_fees_cents": None, "eta_minutes": None}]
        orch, ctx, _, _ = make("Quero para 2 pessoas até R$ 100", FakeRuntime(offers=offers))
        self.assertIsNone(orch.handle_message(ctx).recommendations[0]["total_cents"])

    def test_auditor_rejects_unverified_tag_restriction(self):
        st = WorkingState(Constraints(dietary=("sem-gluten",)), offers=[
            Offer("p1", "Prato", 1000, "m", "M", tags=())], data_origin="demo")
        rec = {"merchant_id": "m", "items": [{"product_id": "p1", "name": "Prato", "quantity": 1,
               "unit_price_cents": 1000}], "subtotal_cents": 1000, "delivery_fee_cents": 0,
               "other_fees_cents": 0, "discount_cents": 0, "total_cents": 1000, "data_origin": "demo"}
        self.assertTrue(any("não verificada" in i for i in audit_recommendation(rec, st)))

    def test_vegetarian_restriction_from_initial_context_is_enforced(self):
        orch, ctx, _, memory = make("Quero para 2 pessoas até R$ 100")
        ctx = SessionContext("sess_1", "t", None, "demo", ctx.message_text,
                             initial_context={"restrictions": ["vegetariana"], "preferences": ["japonesa"]})
        out = orch.handle_message(ctx)
        self.assertEqual(saved(memory)["dietary"], ["vegetarian"])
        self.assertEqual(saved(memory)["preferences"], ["japonesa"])
        for rec in out.recommendations:
            self.assertTrue(all("Burger vegetariano" in i["name"] or "Pizza" in i["name"] for i in rec["items"]))

    def test_budget_and_party_persist_between_messages(self):
        orch, ctx, _, memory = make("Quero comida para 4 pessoas até R$ 120")
        orch.handle_message(ctx)
        out = second_message(orch, ctx, "Tem algo mais simples?")
        self.assertEqual((saved(memory)["budget_cents"], saved(memory)["party_size"]), (12000, 4))
        for rec in out.recommendations:
            self.assertLessEqual(rec["total_cents"], 12000)

    def test_explicit_update_replaces_previous_value(self):
        orch, ctx, _, memory = make("Quero comida para 4 pessoas até R$ 120")
        orch.handle_message(ctx)
        second_message(orch, ctx, "Na verdade, até R$ 50")
        self.assertEqual((saved(memory)["budget_cents"], saved(memory)["party_size"]), (5000, 4))

    def test_initial_context_is_applied_once_and_later_changes_are_ignored(self):
        orch, ctx, _, memory = make("Quero para 2 pessoas")
        ic = {"restrictions": ["vegetariana"], "preferences": ["japonesa"]}
        orch.handle_message(SessionContext("sess_1", "t", None, "demo", "Quero para 2 pessoas",
                                           initial_context=ic))
        orch.handle_message(SessionContext("sess_1", "t", None, "demo", "Quero para 2 pessoas",
                                           initial_context={**ic, "preferences": ["barata"]}))
        self.assertEqual(saved(memory)["dietary"], ["vegetarian"])
        self.assertEqual(saved(memory)["preferences"], ["japonesa"])

    def test_customer_correction_survives_initial_context_on_next_messages(self):
        orch, ctx, _, memory = make("oi")
        ic = {"restrictions": ["vegetariana"], "preferences": []}

        def send(text):
            return orch.handle_message(SessionContext("sess_1", "t", None, "demo", text, initial_context=ic))

        send("oi")
        self.assertEqual(saved(memory)["dietary"], ["vegetarian"])
        send("quero para 2 pessoas, com uma opção vegetariana")
        self.assertEqual(saved(memory)["dietary"], ["vegetarian_option"])
        send("mais barato?")
        self.assertEqual(saved(memory)["dietary"], ["vegetarian_option"])

    def test_null_and_partial_initial_context(self):
        for ic in (None, {}, {"name": "Ana", "age": None, "location": None,
                                "preferences": [], "restrictions": []}):
            orch, ctx, _, _ = make("Quero para 2 pessoas até R$ 100")
            ctx = SessionContext("sess_1", "t", None, "demo", ctx.message_text, initial_context=ic)
            self.assertEqual(orch.handle_message(ctx).session_status, "active")

    def test_malformed_memory_state_is_ignored(self):
        orch, ctx, _, memory = make("Quero para 2 pessoas até R$ 100")
        memory.save_patch("sess_1", {"constraints": "lixo"}, 0, "test")
        self.assertEqual(orch.handle_message(ctx).session_status, "active")


PIZZA_ONLY = [{"product_id": "pz", "name": "Pizza grande", "unit_price_cents": 5990, "merchant_id": "pz_m",
               "merchant_name": "Pizzaria", "tags": [], "delivery_fee_cents": 800, "other_fees_cents": 0,
               "eta_minutes": 40}]


class CommercialTest(unittest.TestCase):
    def test_discount_is_suggested_to_manager_only_and_never_applied(self):
        orch, ctx, sink, _ = make("quero pizza para 2 pessoas até R$ 200", FakeRuntime(offers=PIZZA_ONLY))
        out = orch.handle_message(ctx)
        types = sink.types()
        self.assertLess(types.index("knowledge_retrieved"), types.index("discount_proposed"))
        disc = [e for e in sink.events if e["type"] == "discount_proposed"][0]
        p = disc["payload"]
        self.assertEqual((p["status"], p["requires_approval"], disc["visibility"]), ("suggested", True, "admin"))
        self.assertEqual(p["discount_cents"], 2 * 5990 * 500 // 10000)
        self.assertGreater(p["estimated_profit_delta_cents"], 0)
        rec = out.recommendations[0]
        self.assertEqual((rec["discount_cents"], rec["total_cents"]), (0, 2 * 5990 + 800))
        self.assertNotIn("desconto", out.reply_text.lower())

    def test_real_mode_discount_is_only_a_suggestion_marked_as_demo_hypothesis(self):
        orch, ctx, sink, _ = make("quero pizza para 2 pessoas até R$ 200",
                                  FakeRuntime(offers=PIZZA_ONLY, provider="ifood_mcp"), mode="real")
        out = orch.handle_message(ctx)
        proposals = [e["payload"] for e in sink.events if e["type"] == "discount_proposed"]
        self.assertTrue(proposals and all(p["status"] == "suggested" and p["requires_approval"] for p in proposals))
        self.assertTrue(all(r["discount_cents"] == 0 for r in out.recommendations))

    def test_no_discount_below_policy_minimum(self):
        orch, ctx, sink, _ = make("quero um lanche até R$ 200")
        orch.handle_message(ctx)
        self.assertNotIn("discount_proposed", sink.types())

    def test_stated_preference_puts_matching_option_first_and_tells_customer(self):
        orch, ctx, sink, _ = make("quero comida para 2 pessoas até R$ 200")
        ctx = SessionContext("sess_1", "t", None, "demo", ctx.message_text,
                             initial_context={"preferences": ["pizza"], "restrictions": []})
        out = orch.handle_message(ctx)
        self.assertEqual(out.recommendations[0]["merchant_name"], "Pizzaria Demo")
        self.assertIn("preferência: pizza", out.reply_text)
        pat = [e["payload"] for e in sink.events if e["type"] == "pattern_identified"]
        self.assertEqual(pat[0]["basis"], "stated_preference")

    def test_demo_history_only_for_demo_client_in_demo_mode(self):
        orch, ctx, sink, _ = make("quero comida para 2 pessoas até R$ 200")
        orch.handle_message(SessionContext("sess_1", "t", "client_demo_1", "demo", ctx.message_text))
        self.assertIn("demo", [e["payload"]["basis"] for e in sink.events if e["type"] == "pattern_identified"])
        orch2, ctx2, sink2, _ = make("quero comida para 2 pessoas até R$ 200",
                                     FakeRuntime(provider="ifood_mcp"), mode="real")
        orch2.handle_message(SessionContext("sess_1", "t", "client_demo_1", "real", ctx2.message_text))
        self.assertNotIn("pattern_identified", sink2.types())

    def test_no_duplicate_recommendations(self):
        orch, ctx, _, _ = make("quero comida para 2 pessoas até R$ 200")
        recs = orch.handle_message(ctx).recommendations
        keys = [(r["merchant_id"], sorted((i["product_id"], i["quantity"]) for i in r["items"])) for r in recs]
        self.assertEqual(len(keys), len({str(k) for k in keys}))


class _FakeKB:
    def __init__(self, hits):
        self.hits, self.queries = hits, []

    def search(self, tenant_id, query, topics=(), k=3):
        self.queries.append((query, topics))
        return list(self.hits)


def _policy_hit(**overrides):
    from backend.agents.ports import KnowledgeHit
    data = {"desconto_bps": 1000, "pedido_minimo_centavos": 5000, "teto_desconto_centavos": 5000,
            "margem_suposta_bps": 4000, "conversao_sem_desconto_bps": 4000, "conversao_com_desconto_bps": 7000}
    data.update(overrides)
    return KnowledgeHit("pol_x", "Política X", "Parâmetros: ...", 3.0, data)


class RagTest(unittest.TestCase):
    def run_order(self, knowledge="padrão", text="quero pizza para 2 pessoas até R$ 200"):
        sink = RecordingSink()
        kwargs = {} if knowledge == "padrão" else {"knowledge": knowledge}
        orch = build_orchestrator(FakeRuntime(offers=PIZZA_ONLY), InMemoryMemory(), sink, **kwargs)
        orch.handle_message(SessionContext("sess_1", "t", None, "demo", text))
        return sink

    def events(self, sink, type_):
        return [e["payload"] for e in sink.events if e["type"] == type_]

    def test_default_bootstrap_uses_markdown_knowledge_base(self):
        sink = self.run_order()
        docs = {s["document_id"] for p in self.events(sink, "knowledge_retrieved") for s in p["sources"]}
        self.assertIn("politica_comercial_demo", docs)
        self.assertEqual(self.events(sink, "discount_proposed")[0]["discount_bps"], 500)

    def test_discount_follows_retrieved_policy_parameters(self):
        sink = self.run_order(_FakeKB([_policy_hit()]))
        p = self.events(sink, "discount_proposed")[0]
        self.assertEqual((p["discount_bps"], p["discount_cents"]), (1000, 2 * 5990 * 1000 // 10000))
        self.assertIn("Política X", p["reason"])
        self.assertEqual(self.events(sink, "knowledge_retrieved")[0]["sources"],
                         [{"document_id": "pol_x", "title": "Política X"}])

    def test_no_policy_retrieved_means_no_discount(self):
        from backend.agents.ports import KnowledgeHit
        sink = self.run_order(_FakeKB([KnowledgeHit("outro", "Outro doc", "...", 1.0, {})]))
        self.assertNotIn("discount_proposed", sink.types())

    def test_retrieved_minimum_is_respected(self):
        sink = self.run_order(_FakeKB([_policy_hit(pedido_minimo_centavos=50000)]))
        self.assertNotIn("discount_proposed", sink.types())

    def test_without_knowledge_base_falls_back_to_embedded_policy(self):
        sink = self.run_order(knowledge=None)
        self.assertEqual(self.events(sink, "knowledge_retrieved")[0]["sources"][0]["document_id"], "demo_policy_v1")
        self.assertIn("(embutida)", self.events(sink, "discount_proposed")[0]["reason"])

    def test_strategist_cites_sales_strategy_document(self):
        from backend.memory import default_knowledge_base
        sink = RecordingSink()
        orch = build_orchestrator(FakeRuntime(), InMemoryMemory(), sink, knowledge=default_knowledge_base())
        orch.handle_message(SessionContext("sess_1", "t", None, "demo", "quero comida para 2 pessoas até R$ 200",
                                           initial_context={"preferences": ["pizza"], "restrictions": []}))
        strat = [e for e in sink.events if e["type"] == "knowledge_retrieved" and e["actor"]["id"] == "sales_strategist"]
        self.assertEqual(strat[0]["payload"]["sources"][0]["document_id"], "estrategias_venda_demo")


def _offer(pid, name, price, merchant, mid, is_open=None):
    return {"product_id": pid, "name": name, "unit_price_cents": price, "merchant_id": mid,
            "merchant_name": merchant, "tags": [], "delivery_fee_cents": 0, "other_fees_cents": 0,
            "eta_minutes": 30, "is_open": is_open}


TORTA = _offer("t1", "2 Tortas", 1590, "Mcdonald's - São Carlos", "mc")
MARMITA_FRANGO = _offer("m1", "Marmita - Frango à Milanesa", 1999, "Marmitaria Tio Genaro", "tg")
MARMITA_PARME = _offer("m2", "Marmita Parmegiana de Carne", 2490, "Restaurante Bom Prato", "bp")
PEDIDO = "quero marmita parmegiana pra 2 pessoas por 100 conto no maximo, busque melhor preço"


class PartySizeTest(unittest.TestCase):
    def test_party_without_the_word_pessoas(self):
        from backend.agents.intent import extract_constraints
        cases = {"quero feijoada pra 2 até R$ 150": (2, 15000), "pizza para dois": (2, None),
                 "quero 2 pessoas": (2, None), "lanche pra 2 reais": (None, 200), "para hoje": (None, None),
                 "quero comida pra 4 pessoas até R$ 120": (4, 12000)}
        for text, (party, budget) in cases.items():
            c = extract_constraints(text, Constraints())
            self.assertEqual((c.party_size, c.budget_cents), (party, budget), text)


class RelevanceTest(unittest.TestCase):
    def ask(self, offers, text=PEDIDO):
        runtime = FakeRuntime(offers=offers)
        orch, ctx, sink, memory = make(text, runtime)
        return orch.handle_message(ctx), runtime, sink, memory, orch, ctx

    def test_cheap_unrelated_item_is_never_recommended(self):
        out, *_ = self.ask([TORTA, MARMITA_FRANGO, MARMITA_PARME])
        names = [i["name"] for r in out.recommendations for i in r["items"]]
        self.assertTrue(names and all("Parmegiana" in n for n in names))
        self.assertNotIn("Tortas", out.reply_text)

    def test_closest_option_comes_with_warning(self):
        out, *_ = self.ask([TORTA, MARMITA_FRANGO])
        self.assertIn("Marmita - Frango", out.reply_text)
        self.assertIn("Não encontrei exatamente o que você pediu (parmegiana)", out.reply_text)

    def test_nothing_relevant_asks_customer_instead_of_suggesting(self):
        out, _, sink, *_ = self.ask([TORTA])
        self.assertEqual((out.session_status, out.recommendations), ("waiting_customer", []))
        self.assertIn('Não encontrei "marmita parmegiana"', out.reply_text)
        self.assertNotIn("recommendations_ready", sink.types())

    def test_search_prompt_carries_only_the_dish(self):
        _, runtime, *_ = self.ask([MARMITA_PARME])
        self.assertIn("Produto desejado: marmita parmegiana.", runtime.calls[0].prompt)

    def test_dish_is_remembered_in_follow_up(self):
        _, runtime, _, memory, orch, ctx = self.ask([TORTA, MARMITA_PARME])
        self.assertEqual(memory.load("sess_1").state["search"]["terms"], ["marmita", "parmegiana"])
        out = second_message(orch, ctx, "agora são 3 pessoas")
        self.assertTrue(all("Parmegiana" in i["name"] for r in out.recommendations for i in r["items"]))

    def test_new_dish_replaces_previous_one(self):
        _, _, _, memory, orch, ctx = self.ask([TORTA, MARMITA_PARME])
        second_message(orch, ctx, "na verdade quero pizza para 2 pessoas")
        self.assertEqual(memory.load("sess_1").state["search"]["terms"], ["pizza"])

    def test_customization_and_fillers_are_not_dish_terms(self):
        from backend.agents.relevance import food_terms
        self.assertEqual(food_terms("quero um hamburguer sem cebola"), ("hamburguer",))
        self.assertEqual(food_terms("me vê um xis salada pfv"), ("xis", "salada"))
        self.assertEqual(food_terms(PEDIDO), ("marmita", "parmegiana"))

    def test_generic_order_is_not_filtered(self):
        out, *_ = self.ask([TORTA, MARMITA_FRANGO], text="quero comida para 1 pessoa até R$ 100")
        self.assertTrue(out.recommendations)

    def test_empty_search_names_the_dish(self):
        out, *_ = self.ask([])
        self.assertIn('Não encontrei "marmita parmegiana" disponível agora', out.reply_text)

    def test_closed_restaurant_is_excluded(self):
        closed = dict(MARMITA_PARME, is_open=False)
        out, *_ = self.ask([closed, MARMITA_FRANGO])
        self.assertNotIn("Bom Prato", out.reply_text)
        self.assertIn("Marmita - Frango", out.reply_text)

    def test_only_closed_matches_means_not_available(self):
        out, *_ = self.ask([TORTA, dict(MARMITA_PARME, is_open=False)])
        self.assertEqual(out.recommendations, [])
        self.assertIn("disponível agora", out.reply_text)

    def test_auditor_rejects_unrelated_and_closed_items(self):
        from backend.agents.auditor import audit_recommendation
        from backend.agents.researcher import parse_offers
        offers, _ = parse_offers({"offers": [TORTA, dict(MARMITA_PARME, is_open=False)]})
        st = WorkingState(Constraints(), offers=offers, data_origin="demo", query_terms=("marmita", "parmegiana"))
        base = {"merchant_id": "mc", "subtotal_cents": 1590, "delivery_fee_cents": 0, "other_fees_cents": 0,
                "discount_cents": 0, "total_cents": 1590, "data_origin": "demo", "warnings": []}
        torta = dict(base, items=[{"product_id": "t1", "name": "2 Tortas", "quantity": 1, "unit_price_cents": 1590}])
        self.assertIn("Item t1 não corresponde ao pedido", audit_recommendation(torta, st))
        parme = dict(base, merchant_id="bp", subtotal_cents=2490, total_cents=2490,
                     items=[{"product_id": "m2", "name": "Marmita Parmegiana", "quantity": 1, "unit_price_cents": 2490}])
        self.assertTrue(any("fechado" in i for i in audit_recommendation(parme, st)))


class FailureMessageTest(unittest.TestCase):
    def run_with(self, error, detail):
        orch, ctx, sink, _ = make("quero pizza", FakeRuntime(error=error, detail=detail))
        out = orch.handle_message(ctx)
        err = [e for e in sink.events if e["type"] == "error"][0]["payload"]
        return out, err, sink

    def test_auth_required_is_not_retryable_and_does_not_say_try_again_soon(self):
        out, err, _ = self.run_with("unavailable", "auth_required")
        self.assertEqual((err["code"], err["retryable"]), ("IFOOD_AUTH_REQUIRED", False))
        self.assertIn("não vai resolver", out.reply_text)

    def test_location_required(self):
        out, err, _ = self.run_with("unavailable", "location_required")
        self.assertEqual((err["code"], err["retryable"]), ("LOCATION_REQUIRED", False))
        self.assertIn("localização", out.reply_text)

    def test_invalid_query_asks_customer_to_rephrase(self):
        out, err, _ = self.run_with("invalid_output", "invalid_query")
        self.assertEqual((err["code"], out.session_status), ("SEARCH_QUERY_INVALID", "waiting_customer"))
        self.assertIn("pizza margherita", out.reply_text)

    def test_quota_mentions_wait_time(self):
        out, err, _ = self.run_with("quota", "quota_exceeded")
        self.assertEqual((err["code"], err["retryable"]), ("LLM_QUOTA", True))
        self.assertIn("30 segundos", out.reply_text)

    def test_unknown_detail_falls_back_to_error_kind(self):
        out, err, _ = self.run_with("unavailable", "tool_not_called")
        self.assertEqual((err["code"], err["retryable"], out.session_status), ("IFOOD_UNAVAILABLE", True, "active"))

    def test_runtime_detail_never_leaks(self):
        _, _, sink = self.run_with("unavailable", "segredo_interno_123")
        self.assertNotIn("segredo_interno_123", str(sink.events))


class CheaperTest(unittest.TestCase):
    def test_cheaper_returns_only_options_below_the_one_shown(self):
        orch, ctx, _, memory = make("Quero comida para 2 pessoas até R$ 200")
        memory.save_patch("sess_1", {"conversation": {"stage": "ordering"},
                                     "shown": {"recommendation_id": "rec_x", "total_cents": 10000}}, 0, "t")
        out = second_message(orch, ctx, "tem algo mais barato?")
        self.assertTrue(out.recommendations)
        for rec in out.recommendations:
            self.assertLess(rec["total_cents"], 10000)

    def test_cheaper_when_already_cheapest_says_so_instead_of_repeating(self):
        orch, ctx, sink, _ = make("Quero comida para 2 pessoas até R$ 200")
        first = orch.handle_message(ctx)
        shown = first.recommendations[0]["total_cents"]
        out = second_message(orch, ctx, "tem algo mais barato?")
        self.assertEqual((out.recommendations, out.session_status), ([], "waiting_customer"))
        self.assertIn("mais barata", out.reply_text)
        self.assertIn(f"{shown // 100},{shown % 100:02d}", out.reply_text)

    def test_cheaper_without_previous_recommendation_does_not_crash(self):
        orch, ctx, _, memory = make("Quero comida para 2 pessoas até R$ 200")
        memory.save_patch("sess_1", {"conversation": {"stage": "ordering"}}, 0, "t")
        self.assertTrue(second_message(orch, ctx, "mais barato").recommendations)

    def test_shown_total_is_saved_after_recommendation(self):
        orch, ctx, _, memory = make("Quero comida para 2 pessoas até R$ 200")
        out = orch.handle_message(ctx)
        self.assertEqual(memory.load("sess_1").state["shown"]["total_cents"],
                         out.recommendations[0]["total_cents"])


class ChatTest(unittest.TestCase):
    def chat(self, text, runtime=None, **kw):
        runtime = runtime or FakeRuntime()
        orch, ctx, sink, memory = make(text, runtime, **kw)
        return orch, ctx, sink, memory, runtime, orch.handle_message(ctx)

    def test_small_talk_never_touches_runtime_and_asks_what_to_eat(self):
        for text, must_ask in (("oi eae bot", True), ("Obrigado!", True), ("quero comer", True),
                               ("Qual o horário de vocês?", True), ("asdfgh", True)):
            _, _, sink, _, runtime, out = self.chat(text)
            self.assertEqual(len(runtime.calls), 0, text)
            self.assertEqual((out.session_status, out.recommendations), ("waiting_customer", []), text)
            self.assertEqual(out.reply_text.count("?") >= 1, must_ask, text)
            self.assertNotIn("recommendations_ready", sink.types())
            self.assertEqual(sink.types()[-1], "chat_message")

    def test_goodbye_does_not_search(self):
        _, _, _, _, runtime, out = self.chat("tchau")
        self.assertEqual((len(runtime.calls), out.session_status), (0, "waiting_customer"))

    def test_greeting_with_order_still_runs_agents(self):
        _, _, _, _, runtime, out = self.chat("oi, quero pizza")
        self.assertEqual(len(runtime.calls), 1)
        self.assertTrue(out.recommendations)

    def test_followup_during_order_is_treated_as_order(self):
        orch, ctx, _, memory = make("Quero comida para 2 pessoas até R$ 100")
        orch.handle_message(ctx)
        self.assertEqual(memory.load("sess_1").state["conversation"]["stage"], "ordering")
        out = second_message(orch, ctx, "tem algo mais barato?")
        self.assertTrue(out.recommendations or out.session_status == "waiting_customer")

    def test_small_talk_does_not_start_an_order(self):
        _, _, _, memory, _, _ = self.chat("oi")
        self.assertNotIn("conversation", memory.load("sess_1").state)

    def test_small_talk_still_remembers_initial_context_constraints(self):
        orch, ctx, _, memory = make("oi")
        ctx = SessionContext("sess_1", "t", None, "demo", "oi",
                             initial_context={"restrictions": ["vegetariana"]})
        orch.handle_message(ctx)
        self.assertEqual(saved(memory)["dietary"], ["vegetarian"])

    def test_chat_events_follow_contract(self):
        _, _, sink, _, _, _ = self.chat("oi")
        for e in sink.events:
            self.assertEqual(set(e["payload"]), PAYLOAD_KEYS[e["type"]])


if __name__ == "__main__":
    unittest.main()
