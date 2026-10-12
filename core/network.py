"""Optional source-address binding for marketplace API requests.

Normal routing is the safe default.  Set ``MARKETPLACES_LOCAL_ADDRESS`` to an
IPv4/IPv6 address, or to ``auto`` on macOS, to bind outbound HTTP connections
to the physical interface.  This can help when a VPN route breaks WB/Ozon, but
it is not a VPN or Kill Switch bypass guarantee.
"""
from __future__ import annotations

import ipaddress
import os
import subprocess
import sys
from typing import Mapping, Optional

import httpx

_DISABLED = {"", "0", "false", "no", "off", "disabled"}


def _validated_address(value: str) -> Optional[str]:
    value = value.strip()
    if not value:
        return None
    return str(ipaddress.ip_address(value))


def _macos_address(interface: str) -> Optional[str]:
    interface = "en0" if interface == "auto" else interface
    value = subprocess.check_output(
        ["/usr/sbin/ipconfig", "getifaddr", interface],
        text=True,
        stderr=subprocess.DEVNULL,
        timeout=3,
    )
    return _validated_address(value)


def _windows_address(interface: str, env: Mapping[str, str]) -> Optional[str]:
    process_env = dict(os.environ)
    process_env.update(env)
    process_env["MARKETPLACES_NETWORK_INTERFACE"] = interface
    script = (
        "$name=$env:MARKETPLACES_NETWORK_INTERFACE;"
        "if (-not $name -or $name -eq 'auto') {"
        "$name=(Get-NetAdapter -Physical | Where-Object Status -eq 'Up' | "
        "Sort-Object ifIndex | Select-Object -First 1 -ExpandProperty Name)};"
        "Get-NetIPAddress -InterfaceAlias $name -AddressFamily IPv4 "
        "-AddressState Preferred | Where-Object {$_.IPAddress -notlike '169.254.*'} | "
        "Select-Object -First 1 -ExpandProperty IPAddress"
    )
    value = subprocess.check_output(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
        text=True,
        stderr=subprocess.DEVNULL,
        timeout=5,
        env=process_env,
    )
    return _validated_address(value)


def _linux_address(interface: str) -> Optional[str]:
    if interface == "auto":
        command = ["ip", "-4", "-o", "addr", "show", "up", "scope", "global"]
    else:
        command = ["ip", "-4", "-o", "addr", "show", "dev", interface]
    output = subprocess.check_output(
        command, text=True, stderr=subprocess.DEVNULL, timeout=3
    )
    for line in output.splitlines():
        fields = line.split()
        if "inet" not in fields:
            continue
        name = fields[1].rstrip(":") if len(fields) > 1 else ""
        if interface == "auto" and name.lower().startswith(
            ("lo", "tun", "tap", "wg", "docker", "veth", "br-")
        ):
            continue
        value = fields[fields.index("inet") + 1].split("/", 1)[0]
        return _validated_address(value)
    return None


def resolve_local_address(
    env: Optional[Mapping[str, str]] = None, *, platform: Optional[str] = None
) -> Optional[str]:
    env = os.environ if env is None else env
    raw = (env.get("MARKETPLACES_LOCAL_ADDRESS") or "").strip()
    if raw.lower() in _DISABLED:
        return None
    if raw.lower() != "auto":
        try:
            return str(ipaddress.ip_address(raw))
        except ValueError as exc:
            raise ValueError(
                "MARKETPLACES_LOCAL_ADDRESS must be 'auto', 'off', or a valid IP address"
            ) from exc

    current_platform = sys.platform if platform is None else platform
    interface = (env.get("MARKETPLACES_NETWORK_INTERFACE") or "auto").strip()
    if not interface or any(ord(ch) < 32 for ch in interface):
        raise ValueError("MARKETPLACES_NETWORK_INTERFACE contains invalid characters")
    try:
        if current_platform == "darwin":
            return _macos_address(interface)
        if current_platform.startswith("win"):
            return _windows_address(interface, env)
        if current_platform.startswith("linux"):
            return _linux_address(interface)
        return None
    except (OSError, subprocess.SubprocessError, ValueError):
        return None


def client_transport(env: Optional[Mapping[str, str]] = None) -> Optional[httpx.AsyncHTTPTransport]:
    """Return a bound transport, or ``None`` to preserve normal HTTP routing."""
    address = resolve_local_address(env)
    if address is None:
        return None
    return httpx.AsyncHTTPTransport(local_address=address)


def async_client_kwargs(env: Optional[Mapping[str, str]] = None) -> dict:
    transport = client_transport(env)
    return {"transport": transport} if transport is not None else {}
