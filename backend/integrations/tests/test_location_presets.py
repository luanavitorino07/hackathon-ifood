"""Configuração local de São Carlos sem rede nem alteração permanente do PC."""

import os

import pytest

from backend.api.run_local import configure_local_environment
from backend.integrations.config import SAO_CARLOS_TEST_COORDINATES, SandboxLocation


@pytest.fixture(autouse=True)
def clean_location(monkeypatch):
    monkeypatch.setattr(os, "environ", os.environ.copy())
    for name in (
        "IFOOD_SANDBOX_LATITUDE",
        "IFOOD_SANDBOX_LONGITUDE",
        "IFOOD_TEST_LOCATION",
        "IFOOD_FALLBACK_LOCATION_SOURCE",
        "APP_RUNTIME_MODE",
        "APP_ALLOW_LOCAL_DEMO_ADMIN",
    ):
        monkeypatch.delenv(name, raising=False)


def test_no_implicit_customer_location():
    assert SandboxLocation.from_env() is None


def test_sao_carlos_preset_is_public_test_not_verified_sandbox(monkeypatch):
    monkeypatch.setenv("IFOOD_TEST_LOCATION", "sao_carlos")
    location = SandboxLocation.from_env()
    assert (location.latitude, location.longitude) == SAO_CARLOS_TEST_COORDINATES
    assert location.source == "public_test"


def test_explicit_coordinates_take_precedence(monkeypatch):
    monkeypatch.setenv("IFOOD_TEST_LOCATION", "sao_carlos")
    monkeypatch.setenv("IFOOD_SANDBOX_LATITUDE", "-20")
    monkeypatch.setenv("IFOOD_SANDBOX_LONGITUDE", "-40")
    monkeypatch.setenv("IFOOD_FALLBACK_LOCATION_SOURCE", "sandbox")
    assert SandboxLocation.from_env() == SandboxLocation(-20, -40, source="sandbox")


def test_partial_coordinates_are_not_silently_replaced(monkeypatch):
    monkeypatch.setenv("IFOOD_TEST_LOCATION", "sao_carlos")
    monkeypatch.setenv("IFOOD_SANDBOX_LATITUDE", "-22")
    with pytest.raises(ValueError, match="definidos juntos"):
        SandboxLocation.from_env()


def test_invalid_preset_is_rejected(monkeypatch):
    monkeypatch.setenv("IFOOD_TEST_LOCATION", "typo")
    with pytest.raises(ValueError, match="desconhecida"):
        SandboxLocation.from_env()


def test_local_launcher_replaces_old_sao_paulo_only_in_its_process(monkeypatch):
    monkeypatch.setenv("IFOOD_SANDBOX_LATITUDE", "-23.5505")
    monkeypatch.setenv("IFOOD_SANDBOX_LONGITUDE", "-46.6333")
    monkeypatch.setenv("IFOOD_FALLBACK_LOCATION_SOURCE", "sandbox")
    configure_local_environment(real=True)
    assert SandboxLocation.from_env() == SandboxLocation(
        *SAO_CARLOS_TEST_COORDINATES, source="public_test"
    )


def test_local_launcher_stays_demo_without_real_option():
    configure_local_environment(real=False)
    assert os.environ["APP_RUNTIME_MODE"] == "demo"
    assert SandboxLocation.from_env() is None


def test_local_launcher_can_explicitly_enable_real_demo_admin():
    configure_local_environment(real=True, local_demo_admin=True)
    assert os.environ["APP_ALLOW_LOCAL_DEMO_ADMIN"] == "1"


def test_local_launcher_clears_inherited_demo_admin_option(monkeypatch):
    monkeypatch.setenv("APP_ALLOW_LOCAL_DEMO_ADMIN", "1")
    configure_local_environment(real=True)
    assert "APP_ALLOW_LOCAL_DEMO_ADMIN" not in os.environ


def test_other_city_is_not_silently_searched_in_sao_carlos():
    from backend.integrations.agent_runtime import _resolve_location

    fallback = SandboxLocation(*SAO_CARLOS_TEST_COORDINATES, source="public_test")
    assert _resolve_location({"location": "São Paulo, SP"}, fallback) is None
    assert _resolve_location({"location": "São Carlos, SC"}, fallback) is None
    assert _resolve_location({"location": "São Carlos, SP"}, fallback).source == "public_test"


def test_invalid_explicit_coordinates_do_not_fall_back_to_other_location():
    from backend.integrations.agent_runtime import _resolve_location

    fallback = SandboxLocation(*SAO_CARLOS_TEST_COORDINATES, source="public_test")
    assert _resolve_location({"location": {"latitude": 999, "longitude": 0}}, fallback) is None
