"""Auditor: verificação independente, por algoritmo, de cada proposta antes de chegar ao cliente."""
from __future__ import annotations

from typing import Any

from .models import (LIFESTYLE_RESTRICTIONS, VEGETARIAN_ALL, VEGETARIAN_OPTION, AgentResult, SessionContext, WorkingState,
                     filtered_mark, option_requirements, restriction_label, slug, soft_unverified,
                     tag_requirements)
from .registry import AgentContext, AgentDefinition
from .relevance import score


def _audit_totals(rec: dict[str, Any], st: WorkingState, issues: list[str]) -> None:
    """Conferências de dinheiro, desconto, origem e orçamento (comuns a pedido e cesta)."""
    items = rec["items"]
    subtotal = sum(i["quantity"] * i["unit_price_cents"] for i in items)
    if rec["subtotal_cents"] != subtotal:
        issues.append("Subtotal não confere com os itens")
    parts = (rec["delivery_fee_cents"], rec["other_fees_cents"])
    expected = subtotal + parts[0] + parts[1] - rec["discount_cents"] if None not in parts else None
    if rec["total_cents"] != expected:
        issues.append("Total não confere (ou preenchido com taxas desconhecidas)")
    if rec["discount_cents"] != 0:
        issues.append("Desconto aplicado sem autorização")
    if rec["data_origin"] != st.data_origin:
        issues.append("Origem dos dados divergente da pesquisa")
    shown = rec["total_cents"] if rec["total_cents"] is not None else rec["subtotal_cents"]
    if st.constraints.budget_cents is not None and shown > st.constraints.budget_cents:
        issues.append("Acima do orçamento informado")


def audit_basket(rec: dict[str, Any], st: WorkingState) -> list[str]:
    """Cesta de supermercado: cada produto veio da busca, é de um item da lista, do mesmo mercado,
    aprovado pelo Montador e respeita as restrições (com aviso quando só a IA avaliou ou ninguém verificou)."""
    from .grocery_basket import required_restrictions
    issues: list[str] = []
    by_id = {o.product_id: o for o in st.offers}
    listed = {i.name for i in st.shopping_list}
    seen_items: set[str] = set()
    if not rec["items"]:
        issues.append("Cesta sem itens")
    required = required_restrictions(st)
    ai_ran = bool(st.ai_fit)
    for it in rec["items"]:
        pid = it["product_id"]
        offer = by_id.get(pid)
        if offer is None:
            issues.append(f"Produto {pid} não consta na busca")
            continue
        if offer.unit_price_cents != it["unit_price_cents"]:
            issues.append(f"Preço de {pid} diverge da busca")
        if offer.merchant_id != rec["merchant_id"]:
            issues.append(f"Produto {pid} é de outro mercado")
        if offer.is_open is False:
            issues.append(f"Mercado de {pid} está fechado")
        item = st.grocery_of.get(pid)
        if item not in listed:
            issues.append(f"Produto {pid} não corresponde a item da lista")
        elif item in seen_items:
            issues.append(f"Item '{item}' repetido na cesta")
        else:
            seen_items.add(item)
        judged = st.ai_fit.get(pid)
        if judged is not None and judged[0] == "nao":
            issues.append(f"Produto {pid} rejeitado pelo Montador: {judged[1]}")
        if not 1 <= it["quantity"] <= 50:
            issues.append(f"Quantidade inválida em {pid}")
        tags = {slug(t) for t in offer.tags}
        for r in required:
            if r in tags:
                continue
            label = restriction_label(r)
            if not ai_ran or pid not in st.ai_fit:  # a IA não avaliou este produto: só passa com aviso
                if not any("Restrições não verificadas" in w for w in rec["warnings"]):
                    issues.append(f"Restrição '{label}' não verificada sem aviso ao cliente")
            elif r not in st.ai_restrictions.get(pid, ()):
                issues.append(f"Restrição '{label}' não atendida em {pid}")
            elif r not in LIFESTYLE_RESTRICTIONS and not any(f"'{label}' avaliada pela IA" in w for w in rec["warnings"]):
                issues.append(f"Restrição '{label}' avaliada pela IA sem aviso ao cliente")
    _audit_totals(rec, st, issues)
    return issues


def audit_recommendation(rec: dict[str, Any], st: WorkingState) -> list[str]:
    if st.shopping_list:
        return audit_basket(rec, st)
    issues: list[str] = []
    c = st.constraints
    by_id = {o.product_id: o for o in st.offers}
    items = rec["items"]
    if not items:
        issues.append("Proposta sem itens")
    for it in items:
        offer = by_id.get(it["product_id"])
        if offer is None:
            issues.append(f"Item {it['product_id']} não consta nas ofertas pesquisadas")
        elif offer.unit_price_cents != it["unit_price_cents"]:
            issues.append(f"Preço de {it['product_id']} diverge da oferta pesquisada")
        elif offer.merchant_id != rec["merchant_id"]:
            issues.append(f"Item {it['product_id']} pertence a outro restaurante")
        if offer is not None and offer.is_open is False:
            issues.append(f"Restaurante de {it['product_id']} está fechado")
        judged = st.ai_fit.get(it["product_id"])
        extra = it["product_id"] in st.extra_of  # complemento (bebida etc.): julgado contra o complemento
        if judged is not None and judged[0] == "nao":
            issues.append(f"Item {it['product_id']} rejeitado pelo Curador: {judged[1]}")
        elif (judged is None and not extra and offer is not None and st.query_terms
              and score(offer, st.query_terms) == 0):
            issues.append(f"Item {it['product_id']} não corresponde ao pedido")
        if it["quantity"] <= 0:
            issues.append(f"Quantidade inválida em {it['product_id']}")
    subtotal = sum(i["quantity"] * i["unit_price_cents"] for i in items)
    if rec["subtotal_cents"] != subtotal:
        issues.append("Subtotal não confere com os itens")
    parts = (rec["delivery_fee_cents"], rec["other_fees_cents"])
    expected = subtotal + parts[0] + parts[1] - rec["discount_cents"] if None not in parts else None
    if rec["total_cents"] != expected:
        issues.append("Total não confere (ou preenchido com taxas desconhecidas)")
    if rec["discount_cents"] != 0:
        issues.append("Desconto aplicado sem autorização")
    if rec["data_origin"] != st.data_origin:
        issues.append("Origem dos dados divergente da pesquisa")
    shown = rec["total_cents"] if rec["total_cents"] is not None else rec["subtotal_cents"]
    if c.budget_cents is not None and shown > c.budget_cents:
        issues.append("Acima do orçamento informado")
    if st.price_ceiling_cents is not None and shown >= st.price_ceiling_cents:
        issues.append("Não é mais barata que a opção anterior")
    ai_ran = bool(st.ai_fit)  # com o Curador (IA), restrições brandas também exigem tag ou avaliação da IA
    unverified = () if ai_ran else soft_unverified(c, st.offers)
    proven = ai_ran or "vegetarian" not in soft_unverified(c, st.offers)
    ok_veg = (lambda t: "vegetarian" in t) if proven else \
        (lambda t: "vegetarian" in t or filtered_mark("VEGETARIAN") in t)
    ai = st.ai_restrictions
    ids = [i["product_id"] for i in items if i["product_id"] in by_id]
    veg_ok = [ok_veg(by_id[pid].tags) or "vegetarian" in ai.get(pid, ()) for pid in ids]
    if VEGETARIAN_ALL in c.dietary and not all(veg_ok):
        issues.append("Contém item não vegetariano")
    if VEGETARIAN_OPTION in c.dietary and not any(veg_ok):
        issues.append("Sem opção vegetariana")

    def proof(pid: str, req: str) -> str | None:
        """'tag' (iFood comprova), 'ia' (Curador avaliou pelo nome) ou None."""
        if req in {slug(t) for t in by_id[pid].tags}:
            return "tag"
        return "ia" if req in ai.get(pid, ()) else None

    by_ai: set[str] = {"vegetarian"} if any(
        "vegetarian" in ai.get(pid, ()) and not ok_veg(by_id[pid].tags) for pid in ids) else set()
    for req in option_requirements(c):
        found = [proof(pid, req) for pid in ids if proof(pid, req)]
        if not found:
            issues.append(f"Sem opção {restriction_label(req)} para quem precisa")
        elif "tag" not in found:
            by_ai.add(req)
    for r in unverified:  # restrição branda sem tag: só passa se a proposta avisar o cliente
        if not any(f"'{r}' não comprovada" in w for w in rec["warnings"]):
            issues.append(f"Restrição '{r}' não comprovada sem aviso ao cliente")
    for req in tag_requirements(c, () if ai_ran else st.offers):  # sem tag nem avaliação da IA, reprova
        for it in items:
            kind = proof(it["product_id"], req) if it["product_id"] in by_id else None
            if kind is None:
                issues.append(f"Restrição '{req}' não verificada em {it['product_id']}")
                break
            if kind == "ia":
                by_ai.add(req)
    for req in by_ai - LIFESTYLE_RESTRICTIONS:  # saúde avaliada pela IA só passa com aviso ao cliente
        if not any(f"'{restriction_label(req)}' avaliada pela IA" in w for w in rec["warnings"]):
            issues.append(f"Restrição '{restriction_label(req)}' avaliada pela IA sem aviso ao cliente")
    served = sum(i["quantity"] * st.ai_serves.get(i["product_id"], 1) for i in items
                 if i["product_id"] not in st.extra_of)
    if c.party_size and served < c.party_size:
        issues.append("Quantidade insuficiente para o número de pessoas")
    return issues


class Auditor:
    definition = AgentDefinition(
        "auditor", "Auditor", "Verificação de consistência",
        "Confere restrições, totais e origem dos dados de cada proposta", ["audit"])
    order = 30

    def should_activate(self, session: SessionContext, state: WorkingState) -> bool:
        return bool(state.recommendations)

    def run(self, ctx: AgentContext) -> AgentResult:
        st = ctx.state
        st.issues = {r["recommendation_id"]: audit_recommendation(r, st) for r in st.recommendations}
        st.approved_ids = [rid for rid, problems in st.issues.items() if not problems]
        rejected = len(st.issues) - len(st.approved_ids)
        if rejected:  # devolve ao planejador o motivo, para o escritório ver a revisão entre os dois
            first = next(p for p in st.issues.values() if p)
            author = "grocery_basket" if st.shopping_list else "planner"
            ctx.events.agent_message("auditor", author, ctx.task_id, "review",
                                     f"Reprovei {rejected} proposta(s); ex.: {first[0]}")
        status = "done" if st.approved_ids else "needs_info"
        return AgentResult(
            "auditor", status, {"approved": len(st.approved_ids), "rejected": rejected},
            f"{len(st.approved_ids)} aprovada(s), {rejected} rejeitada(s) pelas verificações algorítmicas.",
            "high", [], [] if st.approved_ids else ["proposta válida"])
