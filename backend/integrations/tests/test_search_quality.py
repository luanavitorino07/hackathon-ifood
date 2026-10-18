"""Qualidade de busca com fixtures sintéticas; zero chamadas externas."""

import pytest

from backend.integrations.errors import InvalidOutputError
from backend.integrations.search_quality import (
    AVAILABILITY_UNKNOWN,
    CUSTOMIZATION_UNKNOWN,
    DISTANCE_UNKNOWN,
    PUBLIC_LOCATION,
    SearchEvidenceStore,
    SearchIntent,
    select_matching_offers,
)


def offer(name, merchant="m1", product="p1", price=2590):
    return dict(
        name=name,
        product_id=product,
        merchant_id=merchant,
        merchant_name=merchant,
        unit_price_cents=price,
    )


@pytest.mark.parametrize(
    "dish",
    [
        "parmegiana de frango",
        "acarajé",
        "sashimi de tilápia",
        "arroz de pato",
        "yakisoba",
        "caldo de mandioquinha",
    ],
)
def test_arbitrary_food_is_not_limited_to_a_fixed_menu(dish):
    intent = SearchIntent.from_prompt(
        f"Pedido do cliente: Quero {dish} para 2 pessoas até R$ 100\n"
        f"Produto desejado: {dish}.\n"
        "Orçamento (centavos): 10000; pessoas: 2; preferências: ['pizza']."
    )
    intent.validate_query(dish)
    assert intent.matches(dish)
    assert not intent.matches("Pizza margherita")


def test_specific_dish_is_not_replaced_by_same_protein():
    intent = SearchIntent.from_prompt(
        "Pedido do cliente: Quero parmegiana de frango\nProduto desejado: parmegiana frango."
    )
    for query in ("frango", "strogonoff de frango", "pizza"):
        with pytest.raises(InvalidOutputError, match="invalid_query"):
            intent.validate_query(query)
    selected, dropped = select_matching_offers(
        [
            offer("Strogonoff de frango"),
            offer("Parmegiana de carne", product="p2"),
            offer("Filé de frango à parmegiana", product="p3", price=3290),
        ],
        intent,
    )
    assert [o["product_id"] for o in selected] == ["p3"]
    assert selected[0]["unit_price_cents"] == 3290
    assert dropped == 2


def test_no_matches_stays_empty_instead_of_showing_whole_catalog():
    selected, dropped = select_matching_offers(
        [offer("Strogonoff de frango")],
        SearchIntent.from_prompt("Produto desejado: parmegiana frango."),
    )
    assert selected == []
    assert dropped == 1


def test_generic_request_can_compare_multiple_merchants():
    intent = SearchIntent.from_prompt("Quero comida para quatro pessoas até R$ 120")
    assert intent.terms == frozenset()
    data = [
        offer("Prato A", product="a"),
        offer("Prato B", product="b"),
        offer("Prato C", merchant="m2", product="c"),
    ]
    selected, _ = select_matching_offers(data, intent)
    assert [o["merchant_id"] for o in selected] == ["m1", "m2", "m1"]
    assert len(selected) == 3


def test_dedup_uses_merchant_and_product_not_name():
    a = offer("Pizza", merchant="a")
    b = offer("Pizza", merchant="b")
    selected, _ = select_matching_offers([a, a, b], SearchIntent.from_prompt("pizza"))
    assert selected == [a, b]


def test_customization_is_a_request_not_proof_of_support():
    intent = SearchIntent.from_prompt(
        "Pedido do cliente: Quero hambúrguer sem cebola, até R$ 50\nProduto desejado: hamburguer."
    )
    assert intent.customization_requested
    assert intent.matches("Hamburger artesanal")
    store = SearchEvidenceStore()
    store.record(
        "s",
        [offer("Hamburger artesanal")],
        public_location=True,
        customization=intent.customization_requested,
    )
    notes = store.recommendation_warnings("s", "m1", ["p1"])
    assert CUSTOMIZATION_UNKNOWN in notes
    assert AVAILABILITY_UNKNOWN in notes
    assert DISTANCE_UNKNOWN in notes
    assert PUBLIC_LOCATION in notes
    assert any("personalização solicitada" in note for note in notes)


def test_spelling_variation_does_not_substitute_dish():
    intent = SearchIntent.from_prompt("Produto desejado: parmigiana frango.")
    assert intent.matches("Parmegiana de frango")
    assert not intent.matches("Strogonoff de frango")


def test_store_does_not_share_evidence_between_sessions_and_expires():
    clock = [0.0]
    store = SearchEvidenceStore(clock=lambda: clock[0], ttl_seconds=10, max_sessions=1)
    store.record("a", [offer("Pizza")], public_location=True, customization=False)
    assert PUBLIC_LOCATION in store.recommendation_warnings("a", "m1", ["p1"])
    assert PUBLIC_LOCATION not in store.recommendation_warnings("b", "m1", ["p1"])
    clock[0] = 11
    assert any("vencida" in n for n in store.recommendation_warnings("a", "m1", ["p1"]))
    store.record("b", [offer("Pizza")], public_location=False, customization=False)
    assert len(store._sessions) == 1
    assert "a" not in store._sessions


def test_empty_query_rejected():
    with pytest.raises(InvalidOutputError, match="invalid_query"):
        SearchIntent.from_prompt("")


def test_finite_evidence_store_limits_are_required():
    with pytest.raises(ValueError):
        SearchEvidenceStore(max_sessions=0)
    with pytest.raises(ValueError):
        SearchEvidenceStore(ttl_seconds=0)


@pytest.mark.parametrize(
    "customer, product",
    [
        (
            "quero marmita parmegiana pra 2 pessoas por 100 conto no maximo, busque melhor preço",
            "marmita parmegiana",
        ),
        ("na verdade quero pizza", "pizza"),
        ("tem algo mais barato?", "pizza"),
        ("me vê um xis salada pfv", "xis salada"),
    ],
)
def test_agent_product_terms_are_source_of_truth_not_conversation_words(customer, product):
    intent = SearchIntent.from_prompt(
        f"Pedido do cliente: {customer}\nProduto desejado: {product}. Use estes termos na query."
    )
    assert intent.terms == frozenset(product.split())
    intent.validate_query(product)
    assert intent.matches(product)


def test_missing_product_line_is_generic_without_a_second_word_classifier():
    intent = SearchIntent.from_prompt("Pedido do cliente: tem algo mais barato?")
    assert intent.terms == frozenset()
    intent.validate_query("pizza")


def test_legacy_product_line_does_not_require_removed_ingredient_in_base_name():
    intent = SearchIntent.from_prompt(
        "Pedido do cliente: hamburguer sem cebola\nProduto desejado: hamburguer cebola."
    )
    assert intent.terms == frozenset({"hamburguer"})
    intent.validate_query("hamburguer")
    assert intent.customization_requested
