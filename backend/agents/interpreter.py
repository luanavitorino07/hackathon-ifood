"""Intérprete: a IA entende a mensagem do cliente com o contexto da conversa.

Devolve o prato a buscar (com erros de digitação corrigidos), quantas pessoas, orçamento, restrições
(inclusive de só parte do grupo: "um amigo é vegano"), preferências e se é pedido, ajuste, confirmação
ou só conversa. As regras de `intent.py`/`chat.py` continuam como reserva e guarda-corpo: o que o cliente
escreveu explicitamente (R$, "N pessoas") vence a IA; restrições só acumulam; a busca precisa ser curta.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, replace
from typing import Any

from .ai import ask
from .chat import classify
from .intent import normalize_restriction, wants_repeat
from .models import (OPTION_SUFFIX, VEGETARIAN_ALL, VEGETARIAN_OPTION, Constraints, base_restriction,
                     restriction_label)
from .registry import AgentContext, AgentDefinition
from .relevance import food_terms

INTERPRETER_ID = "interpreter"

DEFINITION = AgentDefinition(
    INTERPRETER_ID, "Intérprete", "Entendimento do pedido (IA)",
    "Usa IA para entender prato, pessoas, orçamento e restrições com o contexto da conversa",
    ["intent_understanding"])

SYSTEM = (
    "Você é o Intérprete de um chatbot de pedidos de comida do iFood. Entenda a MENSAGEM do cliente usando "
    "o contexto e responda em JSON. intencao: 'pedido' (quer comida), 'ajuste' (muda o pedido em andamento: "
    "quantidade, orçamento, restrição, 'acha um montado', 'mais barato'), 'repetir' (quer o mesmo do último "
    "pedido do histórico), 'confirmar' (aceita a ÚLTIMA_SUGESTAO: 'sim', 'pode ser', 'fechado'), 'conversa' "
    "(saudação, agradecimento, dúvida, sem pedido). busca: termo curto para buscar no iFood (1 a 3 palavras, "
    "só o prato principal, sem quantidade, orçamento nem restrição; corrija erros de digitação); em 'ajuste', "
    "mantenha o prato do PEDIDO_ANTERIOR; null se não houver prato. complementos: itens extras pedidos junto "
    "(bebida, acompanhamento, sobremesa), cada um em 1 a 3 palavras (ex.: 'hambúrguer com coca zero' -> "
    "busca 'hambúrguer', complementos ['coca zero']); em 'ajuste', mantenha os do COMPLEMENTOS_ANTERIORES e "
    "acrescente os novos ('e a coca' -> mantém o prato e acrescenta 'coca'); [] se não houver. pessoas: total de pessoas que vão comer ('eu e 3 "
    "amigos' = 4); senão o do ESTADO; null se nunca disse. orcamento_reais: valor máximo em reais se o cliente "
    "disse; senão o do ESTADO; null se nunca disse. restricoes: restrições alimentares mencionadas na "
    "mensagem (vegetariano, vegano, sem glúten, sem lactose, sem açúcar, alergia a X), com para_todos=false "
    "quando é só de parte do grupo ('um deles é vegano'); entenda erros de digitação ('intelorancia'). "
    "remover_restricoes: restrições que o cliente desfez explicitamente agora ('não sou vegano, errei'); "
    "[] se nenhuma. preferencias: lista COMPLETA e atualizada dos detalhes do jeito de pedir que valem para o pedido atual "
    "(mantenha as do ESTADO que continuam valendo, tire as que não se aplicam mais), no máximo 3 (atenção: 'montado' ou 'pronto' = já montado "
    "pelo restaurante, o contrário de 'monte o seu'; ex.: 'poke já montado, não do tipo monte o seu'). "
    "resumo: o pedido completo entendido, numa frase curta para os outros agentes. resposta: só se "
    "intencao='conversa': resposta simpática em até 2 frases, terminando com uma pergunta sobre o que o "
    "cliente quer comer; pode citar o histórico do CLIENTE_JSON; sem preços; senão null. "
    "conflito_com_perfil: se o pedido contraria uma restrição do cadastro em CLIENTE_JSON, descreva numa "
    "frase; senão null. Não invente nada que o cliente não disse.")

SCHEMA: dict[str, Any] = {
    "type": "object", "required": ["intencao", "busca", "pessoas", "orcamento_reais", "restricoes", "resumo"],
    "properties": {
        "intencao": {"type": "string", "enum": ["pedido", "ajuste", "repetir", "confirmar", "conversa"]},
        "busca": {"type": ["string", "null"]},
        "pessoas": {"type": ["integer", "null"]},
        "orcamento_reais": {"type": ["integer", "null"]},
        "restricoes": {"type": "array", "items": {
            "type": "object", "required": ["tipo", "para_todos"],
            "properties": {"tipo": {"type": "string"}, "para_todos": {"type": "boolean"}}}},
        "preferencias": {"type": "array", "items": {"type": "string"}},
        "complementos": {"type": "array", "items": {"type": "string"}},
        "remover_restricoes": {"type": "array", "items": {"type": "string"}},
        "resumo": {"type": "string"},
        "resposta": {"type": ["string", "null"]},
        "conflito_com_perfil": {"type": ["string", "null"]},
    }}

_MONEY_WORDS = re.compile(r"\d|reais|real\b|conto|pila|\bcem\b|\bmil\b", re.I)


@dataclass(frozen=True)
class Reading:
    intent: str  # order | chat | repeat | confirm
    terms: tuple[str, ...]
    constraints: Constraints
    summary: str | None = None
    reply: str | None = None
    profile_conflict: str | None = None
    by_ai: bool = False
    extras: tuple[str, ...] = ()  # complementos pedidos junto (bebida, acompanhamento), um termo por item


def _restriction(kind: str, for_all: bool) -> str | None:
    n = normalize_restriction(kind)
    if not n or len(n) > 30:
        return None
    if n == VEGETARIAN_ALL:
        return VEGETARIAN_ALL if for_all else VEGETARIAN_OPTION
    return n if for_all else n + OPTION_SUFFIX


def _terms(value: Any) -> tuple[str, ...]:
    if not isinstance(value, str):
        return ()
    words = re.findall(r"[^\W\d_]+", value.lower())
    return tuple(words) if 1 <= len(words) <= 4 else ()


def rule_reading(text: str, rules: Constraints, stored_terms: tuple[str, ...], in_order: bool) -> Reading:
    """Reserva sem IA: o comportamento por regras de sempre."""
    intent = classify(text, in_order)
    terms = food_terms(text) or stored_terms
    if wants_repeat(text) and not food_terms(text):
        intent = "repeat"
    return Reading("order" if intent == "order" else "repeat" if intent == "repeat" else "chat", terms, rules)


def interpret(ctx: AgentContext, base: Constraints, rules: Constraints, stored_terms: tuple[str, ...],
              in_order: bool, last_shown: str | None, facts: dict[str, Any],
              stored_extras: tuple[str, ...] = ()) -> Reading:
    """`base`: restrições antes da mensagem; `rules`: depois das regras. A IA completa o que faltar."""
    text = ctx.session.message_text
    fallback = rule_reading(text, rules, stored_terms, in_order)
    state = {"pessoas": base.party_size,
             "orcamento_reais": None if base.budget_cents is None else base.budget_cents // 100,
             "restricoes": [restriction_label(r) for r in base.dietary], "preferencias": list(base.preferences)}
    prompt = (f"MENSAGEM: {text}\n"
              f"PEDIDO_ANTERIOR: {' '.join(stored_terms) or 'nenhum'}\n"
              f"COMPLEMENTOS_ANTERIORES: {json.dumps(list(stored_extras), ensure_ascii=False)}\n"
              f"ULTIMA_SUGESTAO: {last_shown or 'nenhuma'}\n"
              f"ESTADO: {json.dumps(state, ensure_ascii=False)}\n"
              f"CLIENTE_JSON: {json.dumps(facts, ensure_ascii=False)}")
    answer = ask(ctx, INTERPRETER_ID, SYSTEM, prompt, SCHEMA)
    if answer is None:
        return replace(fallback, extras=stored_extras if in_order else ())
    intent = {"pedido": "order", "ajuste": "order", "repetir": "repeat", "confirmar": "confirm",
              "conversa": "chat"}[answer["intencao"]]
    if intent == "confirm" and not last_shown:
        intent = "chat"
    c = rules
    if c.party_size == base.party_size and isinstance(answer["pessoas"], int) and 1 <= answer["pessoas"] <= 30:
        c = replace(c, party_size=answer["pessoas"])
    budget = answer["orcamento_reais"]
    if (c.budget_cents == base.budget_cents and isinstance(budget, int) and 1 <= budget <= 5000
            and _MONEY_WORDS.search(text)):
        c = replace(c, budget_cents=budget * 100)
    added = [r for r in (_restriction(x["tipo"], x["para_todos"]) for x in answer["restricoes"]) if r]
    # só o cliente desfaz restrição, e de forma explícita ("não sou vegano"); a IA nunca relaxa sozinha
    removed = {base_restriction(r) for r in (_restriction(x, True) for x in answer.get("remover_restricoes") or []
                                             if isinstance(x, str)) if r}
    if removed:
        c = replace(c, dietary=tuple(r for r in c.dietary if base_restriction(r) not in removed))
        added = [r for r in added if base_restriction(r) not in removed]
    if VEGETARIAN_ALL in c.dietary or VEGETARIAN_ALL in added:
        added = [r for r in added if r != VEGETARIAN_OPTION]
    prefs = [p.strip()[:60] for p in answer.get("preferencias") or [] if isinstance(p, str) and p.strip()][:3]
    # preferências: a IA devolve a lista atual (pode tirar as que não valem mais); restrições só acumulam
    c = replace(c, dietary=tuple(dict.fromkeys(c.dietary + tuple(added))), preferences=tuple(dict.fromkeys(prefs)))
    extras = tuple(dict.fromkeys(" ".join(t) for t in (_terms(x) for x in answer.get("complementos") or []) if t))[:2]
    terms = _terms(answer["busca"]) or fallback.terms
    if intent == "order" and not terms and not in_order and c.party_size is None and c.budget_cents is None:
        intent = "chat"  # "quero comer" sem prato, pessoas nem orçamento: pergunta o quê
    reply = answer.get("resposta")
    reply = " ".join(reply.split()) if isinstance(reply, str) else None
    if reply and (len(reply) > 400 or "R$" in reply or not reply.endswith("?")):
        reply = None  # fora do guarda-corpo: vale a resposta por regra
    conflict = answer.get("conflito_com_perfil")
    summary = " ".join(answer["resumo"].split())[:200] or None
    return Reading(intent, terms, c, summary, reply,
                   " ".join(conflict.split())[:200] if isinstance(conflict, str) and conflict.strip() else None,
                   True, extras)


def describe(reading: Reading) -> str:
    """Resumo do entendimento para o escritório."""
    c = reading.constraints
    parts = [f"busca '{' '.join(reading.terms)}'" if reading.terms else "sem prato"]
    if reading.extras:
        parts.append("com " + ", ".join(reading.extras))
    if c.party_size:
        parts.append(f"{c.party_size} pessoa(s)")
    if c.budget_cents is not None:
        parts.append(f"até R$ {c.budget_cents // 100}")
    if c.dietary:
        parts.append("restrições: " + ", ".join(restriction_label(r) for r in c.dietary))
    if c.preferences:
        parts.append("preferências: " + ", ".join(c.preferences))
    head = {"order": "Pedido", "repeat": "Repetir último pedido", "confirm": "Cliente aceitou a sugestão",
            "chat": "Conversa"}[reading.intent]
    origin = "" if reading.by_ai else " (por regras: IA indisponível)"
    return f"{head}{origin}: {reading.summary or ''} [{'; '.join(parts)}]".replace(":  [", ": [")
