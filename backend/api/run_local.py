"""Inicia a API local; --real seleciona a referência pública de São Carlos.

Não altera ambiente permanente do Windows. Sem --real continua em demo sem rede.
Uso: python -m backend.api.run_local [--real] [--local-demo-admin]
       [--include-closed-restaurants] [--port 8000]
"""

from __future__ import annotations

import argparse
import os

import uvicorn


def configure_local_environment(
    *,
    real: bool,
    local_demo_admin: bool = False,
    include_closed_restaurants: bool = False,
) -> None:
    os.environ["APP_RUNTIME_MODE"] = "real" if real else "demo"
    if local_demo_admin:
        os.environ["APP_ALLOW_LOCAL_DEMO_ADMIN"] = "1"
    else:
        os.environ.pop("APP_ALLOW_LOCAL_DEMO_ADMIN", None)
    if include_closed_restaurants:
        os.environ["IFOOD_INCLUDE_CLOSED_FOR_TESTS"] = "1"
    else:
        os.environ.pop("IFOOD_INCLUDE_CLOSED_FOR_TESTS", None)
    if real:
        # Este launcher é explicitamente para testes locais em São Carlos.
        # Descarta coordenadas antigas herdadas somente neste processo.
        os.environ.pop("IFOOD_SANDBOX_LATITUDE", None)
        os.environ.pop("IFOOD_SANDBOX_LONGITUDE", None)
        os.environ["IFOOD_TEST_LOCATION"] = "sao_carlos"
        os.environ["IFOOD_FALLBACK_LOCATION_SOURCE"] = "public_test"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--real", action="store_true", help="MCP real; pode consumir cota de IA")
    parser.add_argument(
        "--local-demo-admin",
        action="store_true",
        help="libera gestor fictício somente em localhost (não usar em produção)",
    )
    parser.add_argument(
        "--include-closed-restaurants",
        action="store_true",
        help="inclui lojas fechadas como opções indisponíveis, somente para testes locais",
    )
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    if args.local_demo_admin and not args.real:
        parser.error("--local-demo-admin só é necessário junto com --real")
    if args.include_closed_restaurants and not args.real:
        parser.error("--include-closed-restaurants exige --real")
    configure_local_environment(
        real=args.real,
        local_demo_admin=args.local_demo_admin,
        include_closed_restaurants=args.include_closed_restaurants,
    )
    uvicorn.run("backend.api.main:app", host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
