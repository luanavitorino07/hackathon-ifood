"""Tradução de falhas do runtime em mensagens honestas ao cliente e eventos `error`.

O `detail` do runtime só escolhe a mensagem; ele nunca é copiado para eventos ou para o cliente.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class Failure:
    code: str  # vai para o evento `error`
    retryable: bool
    session_status: Literal["active", "waiting_customer", "error"]
    customer_text: str
    admin_text: str  # resumo operacional para o gestor, sem dados do runtime


_UNAVAILABLE = Failure(
    "IFOOD_UNAVAILABLE", True, "active",
    "Não estou conseguindo acessar o catálogo do iFood agora. Pode tentar de novo daqui a pouco?",
    "Runtime/MCP indisponível no momento.")

_BY_DETAIL: dict[str, Failure] = {
    "auth_required": Failure(
        "IFOOD_AUTH_REQUIRED", False, "active",
        "No momento não consigo acessar o catálogo do iFood. Repetir agora não vai resolver; "
        "a equipe precisa reconectar a integração.",
        "Integração iFood sem autorização (OAuth). Repetir não resolve."),
    "location_required": Failure(
        "LOCATION_REQUIRED", False, "active",
        "Ainda não consigo buscar restaurantes porque não tenho uma localização configurada para você.",
        "Busca sem localização (coordenadas) disponível."),
    "invalid_query": Failure(
        "SEARCH_QUERY_INVALID", False, "waiting_customer",
        "Não consegui transformar seu pedido em uma busca. Pode me dizer o prato de forma mais direta? "
        "Por exemplo: \"pizza margherita\" ou \"hambúrguer\".",
        "Consulta de busca inválida; pedido de esclarecimento ao cliente."),
    "tool_unavailable": Failure(
        "IFOOD_TOOL_UNAVAILABLE", False, "active",
        "A busca do iFood não está disponível agora. Repetir agora não vai resolver.",
        "Ferramenta de busca MCP não encontrada/configurada."),
    "tool_ambiguous": Failure(
        "IFOOD_TOOL_UNAVAILABLE", False, "active",
        "A busca do iFood não está disponível agora. Repetir agora não vai resolver.",
        "Configuração MCP ambígua para a ferramenta de busca."),
}

_BY_ERROR: dict[str, Failure] = {
    "quota": Failure(
        "LLM_QUOTA", True, "active",
        "Estou recebendo muitos pedidos agora. Pode tentar de novo em instantes?",
        "Cota do runtime de IA esgotada."),
    "timeout": Failure(
        "LLM_TIMEOUT", True, "active",
        "A busca demorou mais que o esperado. Pode tentar de novo?",
        "Tempo limite do runtime excedido."),
    "invalid_output": Failure(
        "LLM_INVALID_OUTPUT", True, "active",
        "Tive um problema ao ler as ofertas encontradas. Pode tentar de novo?",
        "Resposta do runtime fora do contrato."),
    "unavailable": _UNAVAILABLE,
}

AGENT_FAILURE = Failure(
    "AGENT_ERROR", False, "error",
    "Tive um problema ao preparar sua recomendação. Pode reformular o pedido?",
    "Falha interna de um agente.")


def classify_failure(error: object, detail: object, retry_after_s: object = None) -> Failure:
    failure = _BY_DETAIL.get(str(detail)) or _BY_ERROR.get(str(error)) or AGENT_FAILURE
    if failure.code == "LLM_QUOTA" and isinstance(retry_after_s, int) and 0 < retry_after_s <= 600:
        return Failure(failure.code, True, failure.session_status,
                       f"Estou recebendo muitos pedidos agora. Pode tentar de novo em uns {retry_after_s} segundos?",
                       failure.admin_text)
    return failure
