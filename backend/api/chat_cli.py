"""Cliente de terminal para testar o chatbot pela mesma API usada pelo frontend.

Uso offline (catálogo de demonstração)::

    python -m backend.api.chat_cli

Uso real (requer o OpenCode Server em 127.0.0.1:4096)::

    python -m backend.api.chat_cli --real
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import Sequence
from importlib import import_module
from typing import Any
from uuid import uuid4

import httpx

DEFAULT_RESPONSE_TIMEOUT_S = 90.0


class ChatCLIError(RuntimeError):
    """Erro público e sanitizado que pode ser mostrado no terminal."""


class APIChatClient:
    def __init__(
        self,
        client: httpx.AsyncClient,
        *,
        response_timeout_s: float = DEFAULT_RESPONSE_TIMEOUT_S,
        poll_interval_s: float = 0.2,
    ) -> None:
        self._client = client
        self._response_timeout_s = response_timeout_s
        self._poll_interval_s = poll_interval_s
        self.session_id: str | None = None
        self.mode: str | None = None
        self._last_recommendations: list[dict[str, Any]] = []
        self._last_tool_activity: list[dict[str, Any]] = []

    async def start(
        self,
        *,
        client_id: str | None = None,
        location: str | None = None,
        preferences: Sequence[str] = (),
        restrictions: Sequence[str] = (),
    ) -> dict[str, Any]:
        initial_context = {
            "name": None,
            "age": None,
            "location": location,
            "preferences": list(preferences),
            "restrictions": list(restrictions),
        }
        response = await self._client.post(
            "/api/v1/sessions",
            json={"client_id": client_id, "initial_context": initial_context},
        )
        payload = _response_json(response)
        self.session_id = str(payload["session_id"])
        self.mode = str(payload["mode"])
        return payload

    async def send(self, text: str) -> tuple[str, list[dict[str, Any]]]:
        if self.session_id is None:
            raise ChatCLIError("A sessão de chat ainda não foi iniciada.")
        before = await self.snapshot()
        known_assistant_ids = {
            message["message_id"]
            for message in before.get("messages", [])
            if message.get("role") == "assistant"
        }
        after_seq = int(before.get("last_seq", 0))
        response = await self._client.post(
            "/api/v1/chat/messages",
            json={
                "session_id": self.session_id,
                "client_message_id": f"cli_{uuid4().hex}",
                "text": text,
                "input_mode": "text",
                "transcription_id": None,
            },
        )
        _response_json(response)

        deadline = asyncio.get_running_loop().time() + self._response_timeout_s
        while True:
            snapshot = await self.snapshot()
            new_replies = [
                message
                for message in snapshot.get("messages", [])
                if message.get("role") == "assistant"
                and message.get("message_id") not in known_assistant_ids
            ]
            if new_replies:
                self._last_recommendations = list(snapshot.get("recommendations", []))
                self._last_tool_activity = await self._tool_activity(after_seq)
                return str(new_replies[-1]["text"]), self._last_recommendations

            error = await self._latest_error(after_seq)
            if error is not None:
                raise ChatCLIError(error)
            if asyncio.get_running_loop().time() >= deadline:
                raise ChatCLIError(
                    "A resposta demorou além do limite. O processamento pode continuar no servidor."
                )
            await asyncio.sleep(self._poll_interval_s)

    async def snapshot(self) -> dict[str, Any]:
        if self.session_id is None:
            raise ChatCLIError("A sessão de chat ainda não foi iniciada.")
        return _response_json(
            await self._client.get(f"/api/v1/sessions/{self.session_id}/snapshot")
        )

    async def _latest_error(self, after_seq: int) -> str | None:
        if self.session_id is None:
            return None
        payload = await self._admin_history(after_seq)
        errors = [event for event in payload.get("events", []) if event.get("type") == "error"]
        if not errors:
            return None
        detail = errors[-1].get("payload", {})
        message = detail.get("message") or "Não foi possível processar a mensagem."
        code = detail.get("code")
        return f"{message} ({code})" if code else str(message)

    async def _tool_activity(self, after_seq: int) -> list[dict[str, Any]]:
        payload = await self._admin_history(after_seq)
        return [
            event
            for event in payload.get("events", [])
            if event.get("type") == "tool_activity"
        ]

    async def _admin_history(self, after_seq: int) -> dict[str, Any]:
        if self.session_id is None:
            return {"events": []}
        response = await self._client.get(
            f"/api/v1/sessions/{self.session_id}/history",
            params={"after_seq": after_seq, "limit": 200},
            headers={"X-Demo-Role": "admin"},
        )
        return _response_json(response)

    @property
    def recommendations(self) -> list[dict[str, Any]]:
        return list(self._last_recommendations)

    @property
    def tool_activity(self) -> list[dict[str, Any]]:
        return list(self._last_tool_activity)


def _response_json(response: httpx.Response) -> dict[str, Any]:
    try:
        payload = response.json()
    except json.JSONDecodeError as exc:
        raise ChatCLIError(f"A API respondeu HTTP {response.status_code} sem JSON válido.") from exc
    if response.is_error:
        error = payload.get("error", {}) if isinstance(payload, dict) else {}
        message = error.get("message") or f"A API respondeu HTTP {response.status_code}."
        code = error.get("code")
        details = error.get("details") or []
        suffix = f" ({code})" if code else ""
        if details:
            suffix += ": " + "; ".join(str(item) for item in details)
        raise ChatCLIError(f"{message}{suffix}")
    if not isinstance(payload, dict):
        raise ChatCLIError("A API respondeu em um formato inesperado.")
    return payload


def _money(cents: Any) -> str:
    if not isinstance(cents, int) or isinstance(cents, bool):
        return "não informado"
    return f"R$ {cents / 100:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def format_recommendations(recommendations: Sequence[dict[str, Any]]) -> str:
    if not recommendations:
        return "Nenhuma recomendação disponível nesta resposta."
    lines = ["Recomendações:"]
    for index, recommendation in enumerate(recommendations, start=1):
        items = ", ".join(
            f"{item.get('quantity', '?')}x {item.get('name', 'item')}"
            for item in recommendation.get("items", [])
        )
        total = recommendation.get("total_cents")
        if total is None:
            total = recommendation.get("subtotal_cents")
        details = [_money(total)]
        eta_min = recommendation.get("eta_min_minutes")
        eta_max = recommendation.get("eta_minutes")
        if isinstance(eta_min, int) and isinstance(eta_max, int):
            details.append(f"entrega {eta_min}-{eta_max} min")
        elif isinstance(eta_max, int):
            details.append(f"entrega até {eta_max} min")
        distance = recommendation.get("distance_km")
        if isinstance(distance, (int, float)) and not isinstance(distance, bool):
            details.append(f"{distance:g} km")
        rating = recommendation.get("merchant_rating")
        if isinstance(rating, (int, float)) and not isinstance(rating, bool):
            details.append(f"nota {rating:g}")
        lines.append(
            f"  {index}. {recommendation.get('merchant_name', 'Restaurante')}: "
            f"{items} ({' | '.join(details)})"
        )
    return "\n".join(lines)


def format_tool_activity(events: Sequence[dict[str, Any]]) -> str:
    terminal_events: dict[str, tuple[dict[str, Any], str | None]] = {}
    for event in events:
        payload = event.get("payload", {})
        call_id = str(payload.get("call_id", ""))
        if payload.get("status") in {"succeeded", "failed"}:
            recipient = event.get("recipient") or {}
            agent_id = recipient.get("id") if recipient.get("kind") == "agent" else None
            terminal_events[call_id or str(len(terminal_events))] = (payload, agent_id)
    if not terminal_events:
        return "Ferramentas usadas: nenhuma atividade de ferramenta foi registrada nesta mensagem."

    provider_names = {
        "demo": "simulação local, sem rede",
        "ifood_mcp": "MCP oficial do iFood",
        "internal": "OpenCode/modelo de IA",
    }
    status_names = {"succeeded": "concluída", "failed": "falhou"}
    lines = ["Ferramentas usadas nesta mensagem:"]
    for payload, agent_id in terminal_events.values():
        provider = str(payload.get("provider", "desconhecido"))
        status = str(payload.get("status", "desconhecido"))
        agent = f" → agente {agent_id}" if agent_id else ""
        lines.append(
            f"  - {payload.get('tool_name', 'ferramenta')} "
            f"[{provider_names.get(provider, provider)}]{agent}: "
            f"{status_names.get(status, status)} — {payload.get('summary', 'sem resumo')}"
        )
    return "\n".join(lines)


def format_runtime_stack(*, real: bool, memory_backend: str = "SQLiteMemory") -> str:
    if not real:
        return "\n".join(
            (
                "Ferramentas configuradas:",
                "  - API FastAPI executada localmente dentro deste processo",
                f"  - agentes do backend e memória {memory_backend}",
                "  - offer_search e raciocinio_ia simulados pelo catálogo demo",
                "  - OpenCode, Gemini e MCP iFood: NÃO utilizados no modo demo",
            )
        )

    from backend.integrations import OpenCodeSettings

    settings = OpenCodeSettings.from_env()
    variant = f" ({settings.model_variant})" if settings.model_variant else ""
    return "\n".join(
        (
            "Ferramentas configuradas:",
            "  - API FastAPI executada localmente dentro deste processo",
            f"  - agentes do backend e memória {memory_backend}",
            f"  - OpenCode Server: {settings.base_url}",
            f"  - modelo de IA: {settings.provider_id}/{settings.model_id}{variant}",
            f"  - MCP iFood: {settings.mcp_server_name}, ferramenta {settings.search_tool_id}",
            "  - busca real somente leitura; carrinho, pedido e pagamento não são usados",
        )
    )


def _csv(value: str) -> tuple[str, ...]:
    return tuple(part.strip() for part in value.split(",") if part.strip())


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Conversa com o chatbot pelo fluxo completo da API."
    )
    parser.add_argument(
        "--real", action="store_true", help="usa OpenCode, Gemini e iFood MCP reais"
    )
    parser.add_argument(
        "--include-closed-restaurants",
        action="store_true",
        help="inclui lojas fechadas somente para teste local; exige --real",
    )
    parser.add_argument("--client-id", help="identificador fictício opcional do cliente")
    parser.add_argument("--preferences", default="", help="preferências separadas por vírgula")
    parser.add_argument("--restrictions", default="", help="restrições separadas por vírgula")
    parser.add_argument(
        "--once",
        metavar="MENSAGEM",
        help="envia uma mensagem, mostra a resposta e encerra",
    )
    parser.add_argument(
        "--response-timeout",
        type=float,
        default=DEFAULT_RESPONSE_TIMEOUT_S,
        help="segundos para aguardar a resposta do bot",
    )
    return parser


async def _run(args: argparse.Namespace) -> int:
    if args.response_timeout <= 0:
        raise ChatCLIError("--response-timeout precisa ser maior que zero.")
    from .run_local import configure_local_environment

    configure_local_environment(
        real=args.real,
        local_demo_admin=args.real,
        include_closed_restaurants=args.include_closed_restaurants,
    )
    api_main = import_module("backend.api.main")
    transport = httpx.ASGITransport(app=api_main.app)
    timeout = httpx.Timeout(args.response_timeout + 10)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://127.0.0.1",
        timeout=timeout,
    ) as http_client:
        chat = APIChatClient(http_client, response_timeout_s=args.response_timeout)
        started = await chat.start(
            client_id=args.client_id,
            location="São Carlos, SP" if args.real else None,
            preferences=_csv(args.preferences),
            restrictions=_csv(args.restrictions),
        )
        print(
            f"Chat iniciado em modo {started['mode']} (sessão {started['session_id']}).\n"
            "Comandos: /recomendacoes, /estado, /ajuda e /sair."
        )
        print(
            format_runtime_stack(
                real=args.real,
                memory_backend=api_main.app.state.memory_backend,
            )
        )
        if args.real:
            print(
                "Localização pública de teste: São Carlos/SP; "
                "não representa endereço de entrega."
            )

        if args.once:
            await _send_and_print(chat, args.once)
            return 0

        while True:
            text = (await asyncio.to_thread(input, "\nVocê: ")).strip()
            if not text:
                continue
            command = text.casefold()
            if command in {"/sair", "/exit", "/quit"}:
                print("Chat encerrado.")
                return 0
            if command == "/ajuda":
                print("Digite normalmente para conversar. Use /recomendacoes, /estado ou /sair.")
                continue
            if command == "/recomendacoes":
                print(format_recommendations(chat.recommendations))
                continue
            if command == "/estado":
                snapshot = await chat.snapshot()
                print(
                    f"Estado: {snapshot['session']['status']} | "
                    f"mensagens: {len(snapshot['messages'])} | "
                    f"recomendações: {len(snapshot['recommendations'])}"
                )
                continue
            await _send_and_print(chat, text)


async def _send_and_print(chat: APIChatClient, text: str) -> None:
    print("Bot está consultando os agentes...")
    try:
        reply, recommendations = await chat.send(text)
    except ChatCLIError as exc:
        print(f"Erro: {exc}")
        return
    print(f"\nBot: {reply}")
    print(format_tool_activity(chat.tool_activity))
    if recommendations:
        print(format_recommendations(recommendations))


def main(argv: Sequence[str] | None = None) -> int:
    _configure_stdio()
    parser = _parser()
    args = parser.parse_args(argv)
    if args.include_closed_restaurants and not args.real:
        parser.error("--include-closed-restaurants exige --real")
    try:
        return asyncio.run(_run(args))
    except KeyboardInterrupt:
        print("\nChat encerrado.")
        return 130
    except (ChatCLIError, httpx.HTTPError, ValueError) as exc:
        print(f"Não foi possível iniciar o chat: {exc}", file=sys.stderr)
        return 1


def _configure_stdio() -> None:
    """Mantém acentos legíveis também quando o terminal do Windows usa outra página de código."""
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
