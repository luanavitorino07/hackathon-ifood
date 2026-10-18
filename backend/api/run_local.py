"""Inicia a API local; --real seleciona a referência pública de São Carlos.

Não altera ambiente permanente do Windows. Sem --real continua em demo sem rede.
Uso: python -m backend.api.run_local [--real] [--port 8000]
"""

from __future__ import annotations

import argparse
import os

import uvicorn


def configure_local_environment(*, real: bool) -> None:
    os.environ["APP_RUNTIME_MODE"] = "real" if real else "demo"
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
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    configure_local_environment(real=args.real)
    uvicorn.run("backend.api.main:app", host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
