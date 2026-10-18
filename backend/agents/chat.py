"""Conversa amigável por regras (sem LLM): decide se a mensagem é pedido ou só papo.

Só mensagens de pedido acionam a esteira de agentes (e gastam cota do runtime). O resto
recebe uma resposta direta que sempre devolve a pergunta "o que você quer comer?".
"""
from __future__ import annotations

import re
import unicodedata
from typing import Literal

Intent = Literal["order", "greeting", "thanks", "bye", "vague", "question", "unclear"]

_MONEY_OR_PARTY = re.compile(r"r\$|\d+\s*reais|\bate\s+\d|\b(?:\d+|um|uma|dois|duas|tres|quatro|cinco|seis|sete|oito|nove|dez)\s+pessoas?\b")
_FOOD = re.compile(
    r"\b(pizza|hamburg|burger|lanche|sanduiche|sushi|japones|pastel|marmita|comida|jantar|janta|"
    r"almoc|sobremesa|doce|acai|salada|churrasco|massa|macarrao|lasanha|frango|carne|vegetarian|"
    r"vegan|combo|prato|bebida|refrigerante|suco|cafe da manha|esfiha|coxinha|salgad|pao)")
_VAGUE = re.compile(r"\b(fome|comer|pedir|pedido|quero|queria|gostaria|bora|cardapio|opcoes)\b")
_THANKS = re.compile(r"\b(obrigad|brigad|valeu|vlw|agradec)")
_BYE = re.compile(r"\b(tchau|ate mais|ate logo|flw|falou|xau)\b")
_GREETING = re.compile(r"\b(oi|oie|ola|eae|eai|e ai|opa|salve|fala|hey|hello|bom dia|boa tarde|boa noite|tudo bem|blz|beleza)\b")
_QUESTION = re.compile(r"\?|^(qual|quais|quando|como|onde|quanto|que horas|voces|vcs)\b")

REPLIES: dict[str, tuple[str, ...]] = {
    "greeting": (
        "Oi! 😊 Eu sou o assistente de pedidos. O que você está com vontade de comer hoje?",
        "E aí! Tudo bem? Me conta o que você quer pedir hoje que eu te ajudo a achar uma boa opção.",
    ),
    "thanks": (
        "Imagina, fico feliz em ajudar! Quer pedir mais alguma coisa? O que você gostaria?",
        "Por nada! Quer montar outro pedido? Me diz o que você está a fim de comer.",
    ),
    "bye": ("Até mais! Quando quiser fazer um pedido, é só me chamar. 😊",),
    "vague": (
        "Bora! O que você está a fim de comer? Se puder, me diz também quantas pessoas são, "
        "o orçamento e se tem alguma restrição.",
    ),
    "question": (
        "Ainda não consigo responder esse tipo de dúvida por aqui, mas posso te ajudar a escolher "
        "um pedido. O que você gostaria de comer?",
    ),
    "unclear": (
        "Não entendi muito bem. O que você gostaria de pedir? Pode me dizer o prato, quantas "
        "pessoas são e o orçamento.",
    ),
}


def _plain(text: str) -> str:
    return unicodedata.normalize("NFKD", text.lower()).encode("ascii", "ignore").decode().strip()


def classify(text: str, in_order: bool = False) -> Intent:
    """`in_order`: já existe um pedido em andamento na sessão (follow-ups contam como pedido)."""
    t = _plain(text)
    if _MONEY_OR_PARTY.search(t) or _FOOD.search(t):
        return "order"
    if _VAGUE.search(t):
        # "quero feijoada": verbo de pedido + algo que parece um prato vira pedido; "quero comer" segue vago.
        from .relevance import food_terms
        return "order" if food_terms(text) else "vague"
    if _THANKS.search(t):
        return "thanks"
    if _BYE.search(t):
        return "bye"
    if _GREETING.search(t) and len(t.split()) <= 6:
        return "greeting"
    if in_order:
        return "order"
    if _QUESTION.search(t):
        return "question"
    return "unclear"


def reply_for(intent: str, text: str) -> str:
    options = REPLIES[intent]
    return options[len(text) % len(options)]  # variação determinística, sem aleatoriedade
