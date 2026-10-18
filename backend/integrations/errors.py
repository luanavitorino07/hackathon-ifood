"""Erros normalizados para o contrato de runtime dos agentes."""

from __future__ import annotations


class IntegrationError(RuntimeError):
    """Falha conhecida de integração sem dados sensíveis na mensagem."""

    code = "unavailable"
    retryable = True

    def __init__(self, message: str, *, retryable: bool | None = None) -> None:
        super().__init__(message)
        if retryable is not None:
            self.retryable = retryable


class QuotaError(IntegrationError):
    code = "quota"


class RuntimeTimeoutError(IntegrationError):
    code = "timeout"


class InvalidOutputError(IntegrationError):
    code = "invalid_output"
    retryable = False


class UnavailableError(IntegrationError):
    code = "unavailable"
