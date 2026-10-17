"""Serialização do envelope OfficeEvent no transporte SSE v1."""

from __future__ import annotations

from .models import OfficeEvent


def format_office_event(event: OfficeEvent) -> str:
    return (
        f"id: {event.seq}\n"
        "event: office_event\n"
        f"data: {event.model_dump_json(by_alias=True)}\n\n"
    )


def format_keepalive() -> str:
    return ": keepalive\n\n"
