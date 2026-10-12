from __future__ import annotations

import os

import httpx

from core.network import client_transport, resolve_local_address


def test_explicit_ipv4_is_used_without_discovery():
    assert resolve_local_address({"MARKETPLACES_LOCAL_ADDRESS": "192.0.2.10"}) == "192.0.2.10"


def test_disabled_binding_uses_normal_routing():
    for value in ("", "off", "false", "0"):
        assert resolve_local_address({"MARKETPLACES_LOCAL_ADDRESS": value}) is None


def test_auto_prefers_configured_interface(monkeypatch):
    calls: list[list[str]] = []

    def fake_check_output(command, **_kwargs):
        calls.append(command)
        return "192.0.2.25\n"

    monkeypatch.setattr("core.network.subprocess.check_output", fake_check_output)
    env = {
        "MARKETPLACES_LOCAL_ADDRESS": "auto",
        "MARKETPLACES_NETWORK_INTERFACE": "en7",
    }
    assert resolve_local_address(env, platform="darwin") == "192.0.2.25"
    assert calls == [["/usr/sbin/ipconfig", "getifaddr", "en7"]]


def test_auto_failure_falls_back_to_normal_routing(monkeypatch):
    def fail(*_args, **_kwargs):
        raise OSError("not available")

    monkeypatch.setattr("core.network.subprocess.check_output", fail)
    assert resolve_local_address(
        {"MARKETPLACES_LOCAL_ADDRESS": "auto"}, platform="darwin"
    ) is None


def test_windows_auto_uses_powershell_physical_adapter(monkeypatch):
    calls = []

    def fake_check_output(command, **kwargs):
        calls.append((command, kwargs))
        return "192.0.2.40\n"

    monkeypatch.setattr("core.network.subprocess.check_output", fake_check_output)
    assert resolve_local_address(
        {"MARKETPLACES_LOCAL_ADDRESS": "auto", "MARKETPLACES_NETWORK_INTERFACE": "auto"},
        platform="win32",
    ) == "192.0.2.40"
    assert calls[0][0][0].lower() == "powershell.exe"
    assert "Get-NetAdapter" in calls[0][0][-1]


def test_linux_auto_uses_named_interface(monkeypatch):
    calls = []

    def fake_check_output(command, **_kwargs):
        calls.append(command)
        return "2: eth0    inet 192.0.2.41/24 brd 192.0.2.255 scope global eth0\n"

    monkeypatch.setattr("core.network.subprocess.check_output", fake_check_output)
    assert resolve_local_address(
        {"MARKETPLACES_LOCAL_ADDRESS": "auto", "MARKETPLACES_NETWORK_INTERFACE": "eth0"},
        platform="linux",
    ) == "192.0.2.41"
    assert calls == [["ip", "-4", "-o", "addr", "show", "dev", "eth0"]]


def test_transport_is_only_created_when_binding_is_enabled(monkeypatch):
    monkeypatch.delenv("MARKETPLACES_LOCAL_ADDRESS", raising=False)
    assert client_transport() is None

    monkeypatch.setenv("MARKETPLACES_LOCAL_ADDRESS", "192.0.2.30")
    transport = client_transport()
    assert isinstance(transport, httpx.AsyncHTTPTransport)
