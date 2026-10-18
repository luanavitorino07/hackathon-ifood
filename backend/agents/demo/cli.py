"""Chat de terminal com os agentes, 100% offline e com dados FICTÍCIOS.

    python3 -m backend.agents.demo                  # conversa interativa
    python3 -m backend.agents.demo --escritorio     # mostra também a comunicação entre os agentes
    python3 -m backend.agents.demo --roteiro        # roda uma conversa pronta (bom para apresentar)
    python3 -m backend.agents.demo --sem-tags       # imita o iFood real (sem tags de dieta)
    python3 -m backend.agents.demo --falha quota    # demonstra o tratamento de falha do runtime
"""
from __future__ import annotations

import argparse
import sys
from typing import Any, Iterable, TextIO

from ..bootstrap import build_orchestrator
from ..models import SessionContext
from ..testing.fakes import InMemoryMemory
from .runtime import DemoCatalogRuntime

SCRIPT = [
    "oi eae bot",
    "quero comida pra 4 pessoas até R$ 150, com uma opção vegetariana",
    "tem algo mais barato?",
    "agora quero pizza para 2 pessoas até R$ 200",
    "valeu",
]


def _brl(cents: int | None) -> str:
    return "?" if cents is None else f"R$ {cents // 100},{cents % 100:02d}"


class PrintingSink:
    """EventSink que imprime a visão do 'escritório' (gestor) no terminal."""

    def __init__(self, out: TextIO, office: bool) -> None:
        self.out, self.office = out, office
        self.events: list[dict[str, Any]] = []

    def emit(self, *, session_id: str, type: str, actor: dict[str, str], recipient: dict[str, str] | None,
             visibility: str, payload: dict[str, Any]) -> None:
        self.events.append({"type": type, "actor": actor, "recipient": recipient, "payload": payload})
        if not self.office:
            return
        p, who = payload, actor["id"]
        line = {
            "agent_status": lambda: f"{p['agent_id']}: {p['status']} — {p['summary'] or ''}",
            "agent_message": lambda: f"{who} → {recipient['id'] if recipient else '?'} [{p['channel']}] {p['summary']}",
            "tool_activity": lambda: f"ferramenta {p['tool_name']} ({p['provider']}) {p['status']}: {p['summary']}",
            "conflict_detected": lambda: f"CONFLITO {p['status']}: {p['description']}",
            "decision_made": lambda: f"DECISÃO: {p['summary']}",
            "pattern_identified": lambda: f"PADRÃO ({p['basis']}): {p['description']}",
            "knowledge_retrieved": lambda: "CONSULTA: " + ", ".join(s["title"] for s in p["sources"]),
            "discount_proposed": lambda: (f"DESCONTO SUGERIDO (não aplicado): {_brl(p['discount_cents'])}, "
                                          f"lucro esperado {_brl(p['estimated_profit_delta_cents'])} — {p['reason']}"),
            "error": lambda: f"ERRO {p['code']} (retryable={p['retryable']}): {p['message']}",
        }.get(type)
        if line:
            print(f"      · {line()}", file=self.out)


def run_conversation(lines: Iterable[str], out: TextIO | None = None, office: bool = False,
                     with_tags: bool = True, fail: str | None = None, client_id: str = "client_demo_1",
                     initial_context: dict[str, Any] | None = None) -> PrintingSink:
    out = out or sys.stdout
    sink = PrintingSink(out, office)
    orch = build_orchestrator(DemoCatalogRuntime(with_tags, fail, None), InMemoryMemory(), sink)
    print("=== MODO DEMONSTRAÇÃO OFFLINE — dados fictícios, sem iFood/MCP/Gemini ===\n", file=out)
    for text in lines:
        print(f"Cliente: {text}", file=out)
        result = orch.handle_message(SessionContext("sess_demo", "tenant_demo", client_id, "demo", text,
                                                    initial_context=initial_context))
        print(f"Bot:     {result.reply_text}", file=out)
        for i, rec in enumerate(result.recommendations[1:3], start=2):
            items = ", ".join(f"{it['quantity']}x {it['name']}" for it in rec["items"])
            print(f"         opção {i}: {rec['merchant_name']} — {items} ({_brl(rec['total_cents'])})", file=out)
        print(file=out)
    return sink


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Chat offline com os agentes (dados fictícios).")
    ap.add_argument("--escritorio", action="store_true", help="mostra a comunicação entre os agentes")
    ap.add_argument("--roteiro", action="store_true", help="roda uma conversa pronta")
    ap.add_argument("--sem-tags", action="store_true", help="imita o iFood real, sem tags de dieta")
    ap.add_argument("--falha", choices=["quota", "timeout", "unavailable", "invalid_output"])
    ap.add_argument("--preferencia", action="append", default=[], help="ex.: --preferencia pizza")
    ap.add_argument("--restricao", action="append", default=[], help="ex.: --restricao vegetariana")
    args = ap.parse_args(argv)
    ic = {"name": None, "age": None, "location": None,
          "preferences": args.preferencia, "restrictions": args.restricao}
    opts = dict(office=args.escritorio, with_tags=not args.sem_tags, fail=args.falha, initial_context=ic)
    if args.roteiro:
        run_conversation(SCRIPT, **opts)
        return

    def typed() -> Iterable[str]:
        print("Digite sua mensagem (ou 'sair').")
        while True:
            try:
                text = input("> ").strip()
            except (EOFError, KeyboardInterrupt):
                return
            if text.lower() in {"sair", "exit", "quit"}:
                return
            if text:
                yield text

    run_conversation(typed(), **opts)


if __name__ == "__main__":
    main()
