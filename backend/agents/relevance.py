"""Relevância por regras: a oferta corresponde ao prato que o cliente pediu?

O iFood pode devolver itens soltos (ex.: "2 Tortas" para "marmita parmegiana"). Sem esta checagem o
planejador escolheria o mais barato mesmo sem relação com o pedido.
"""
from __future__ import annotations

import re
import unicodedata

from .models import Offer

# Palavras que não descrevem o prato: pedido, quantidade, dinheiro, preço, conversa, restrições.
_NOT_FOOD = {
    "quero", "queria", "gostaria", "pedir", "pedido", "comer", "comida", "fome", "hoje", "agora", "favor",
    "pra", "para", "por", "com", "sem", "uma", "uns", "umas", "dois", "duas", "tres", "quatro", "cinco",
    "seis", "sete", "oito", "nove", "dez", "pessoa", "pessoas", "gente", "reais", "real", "conto", "contos",
    "pila", "maximo", "minimo", "ate", "valor", "orcamento", "preco", "precos", "barato", "barata",
    "baratos", "baratas", "caro", "cara", "mais", "menos", "melhor", "melhores", "busque", "buscar",
    "procure", "procurar", "encontre", "ache", "achar", "tem", "algo", "alguma", "algum", "opcao",
    "opcoes", "coisa", "tipo", "esse", "essa", "isso", "aqui", "ali", "voce", "voces", "vcs", "pode",
    "poderia", "ser", "seria", "uma", "pro", "pros", "pras", "das", "dos", "nas", "nos", "que", "qual",
    "vegetariano", "vegetariana", "vegetarianos", "vegetarianas", "vegano", "vegana", "veganos", "veganas",
    "gluten", "lactose", "alergia", "restricao", "jantar", "janta", "almoco", "almocar", "lanche",
    "entrega", "delivery", "rapido", "rapida", "perto", "proximo", "aberto", "abertos", "agr", "oi",
    "ola", "obrigado", "obrigada", "valeu", "bom", "boa", "dia", "tarde", "noite", "entao", "tambem",
    # conversa, verbos e conectivos comuns em follow-ups ("agora são 3 pessoas", "na verdade quero...")
    "sao", "sou", "somos", "estou", "esta", "estamos", "vamos", "vai", "verdade", "mudar", "mudei",
    "mude", "troca", "trocar", "troque", "prefiro", "preferia", "acho", "talvez", "mesmo", "ainda",
    "nao", "sim", "certo", "beleza", "blz", "olha", "outra", "outro", "outras", "outros", "vez", "mim",
    "galera", "familia", "amigos", "casa", "manda", "mande", "traz", "traga", "quanto", "custa", "custam",
    "saber", "horario", "funciona", "entregam", "aceita", "aceitam", "pagamento", "cartao", "pix",
    "dinheiro", "troco", "endereco", "rua", "faz", "fazem", "tenho", "temos", "precisa", "preciso",
    "quer", "queremos", "seja", "fosse", "tudo", "todo", "toda", "cada", "muito", "pouco", "bem",
    "show", "top", "legal", "massa", "fechou", "ok", "okay", "aqui", "agorinha", "logo", "dps", "depois",
}
_PREFIX = 5  # "marmita" casa com "marmitaria"; "pizza" com "pizzaria"


def _words(text: str) -> list[str]:
    plain = unicodedata.normalize("NFKD", text.lower()).encode("ascii", "ignore").decode()
    return re.findall(r"[a-z]+", plain)


def food_terms(text: str) -> tuple[str, ...]:
    """Termos que descrevem o prato pedido; vazio se o texto não citar um prato ("quero comida")."""
    seen: dict[str, None] = {}
    for w in _words(text):
        if len(w) >= 3 and w not in _NOT_FOOD:
            seen.setdefault(w, None)
    return tuple(seen)


def _matches(term: str, words: list[str]) -> bool:
    key = term[:_PREFIX]
    return any(w.startswith(key) for w in words)


def score(offer: Offer, terms: tuple[str, ...]) -> int:
    """2 pontos por termo no nome do item, 1 no nome do restaurante."""
    item, merchant = _words(offer.name), _words(offer.merchant_name)
    return sum(2 if _matches(t, item) else 1 if _matches(t, merchant) else 0 for t in terms)


def covered_terms(offer: Offer, terms: tuple[str, ...]) -> set[str]:
    words = _words(offer.name) + _words(offer.merchant_name)
    return {t for t in terms if _matches(t, words)}


def relevant(offers: list[Offer], terms: tuple[str, ...]) -> tuple[list[Offer], set[str]]:
    """Ofertas mais aderentes ao pedido e os termos que nenhuma delas cobre.

    Sem termos (pedido genérico), devolve tudo. Sem nenhuma oferta aderente, devolve lista vazia.
    """
    if not terms:
        return list(offers), set()
    scored = [(score(o, terms), o) for o in offers]
    best = max((s for s, _ in scored), default=0)
    if best == 0:
        return [], set(terms)
    kept = [o for s, o in scored if s == best]
    covered = set().union(*(covered_terms(o, terms) for o in kept))
    return kept, set(terms) - covered
