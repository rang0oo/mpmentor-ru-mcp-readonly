#!/usr/bin/env python3
"""Portable installer for the read-only Codex marketplace MCP server."""
from __future__ import annotations

import argparse
import contextlib
import getpass
import json
import os
import shutil
import subprocess
import sys
import venv
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
APP_HOME = Path(os.environ.get("MARKETPLACE_MCP_HOME", Path.home() / ".marketplace-mcp"))
APP_DIR = APP_HOME / "readonly-app"
SERVER_NAME = "marketplaces-ru-readonly"
RUNTIME_ITEMS = [
    "core", "wb_mcp", "ozon_mcp", "ozon_perf_mcp", "readonly_mcp",
    "pyproject.toml", "LICENSE",
]


def install_app(source: Path, destination: Path) -> Path:
    """Copy a clean runtime to a stable user directory with an atomic swap."""
    source = source.resolve()
    destination = destination.resolve()
    if source == destination:
        return destination
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = destination.with_name(destination.name + ".new")
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir()
    ignore = shutil.ignore_patterns("__pycache__", "*.pyc", ".git", ".venv")
    for name in RUNTIME_ITEMS:
        src = source / name
        if not src.exists():
            continue
        dst = staging / name
        if src.is_dir():
            shutil.copytree(src, dst, ignore=ignore)
        else:
            shutil.copy2(src, dst)
    old_venv = destination / ".venv"
    if old_venv.is_dir():
        shutil.move(str(old_venv), str(staging / ".venv"))
    if destination.exists():
        shutil.rmtree(destination)
    os.replace(staging, destination)
    return destination


def venv_python(app_dir: Path) -> Path:
    return app_dir / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def provision(app_dir: Path) -> Path:
    python = venv_python(app_dir)
    if not python.exists():
        # POSIX copies can break relocatable/standalone Python distributions
        # (notably uv-managed Python) by losing their base-prefix.  A symlink
        # keeps the interpreter tied to its real standard library.
        venv.EnvBuilder(with_pip=True, symlinks=os.name != "nt").create(app_dir / ".venv")
    subprocess.run(
        [str(python), "-m", "pip", "install", "--disable-pip-version-check", "-e", str(app_dir)],
        check=True,
    )
    return python


def codex_add_command(
    python: Path, *, local_address: str = "off", interface: str = "auto"
) -> list[str]:
    command = ["codex", "mcp", "add", SERVER_NAME]
    if local_address.lower() not in {"", "off", "false", "0"}:
        command += ["--env", f"MARKETPLACES_LOCAL_ADDRESS={local_address}"]
        if local_address.lower() == "auto":
            command += ["--env", f"MARKETPLACES_NETWORK_INTERFACE={interface}"]
    command += ["--", str(python), "-m", "readonly_mcp.server"]
    return command


def claude_add_command(
    python: Path, *, local_address: str = "off", interface: str = "auto"
) -> list[str]:
    command = ["claude", "mcp", "add", SERVER_NAME, "--scope", "user"]
    if local_address.lower() not in {"", "off", "false", "0"}:
        command += ["--env", f"MARKETPLACES_LOCAL_ADDRESS={local_address}"]
        if local_address.lower() == "auto":
            command += ["--env", f"MARKETPLACES_NETWORK_INTERFACE={interface}"]
    command += ["--", str(python), "-m", "readonly_mcp.server"]
    return command


def detect_clients(requested: str) -> list[str]:
    if requested != "auto":
        return [requested]
    clients = []
    if shutil.which("codex"):
        clients.append("codex")
    if shutil.which("claude"):
        clients.append("claude-code")
    if not clients:
        raise RuntimeError("Neither Codex CLI nor Claude Code was found in PATH")
    return clients


def validate_network_mode(local_address: str, interface: str) -> None:
    if local_address.lower() in {"", "off", "false", "0"}:
        return
    from core.network import resolve_local_address

    resolved = resolve_local_address({
        "MARKETPLACES_LOCAL_ADDRESS": local_address,
        "MARKETPLACES_NETWORK_INTERFACE": interface,
    })
    if resolved is None:
        raise RuntimeError(
            "Could not find an IPv4 address for the physical network interface. "
            "Connect the adapter or pass --interface with its real name; use "
            "--direct-network off for normal VPN routing."
        )


def register_codex(
    python: Path, *, local_address: str = "off", interface: str = "auto"
) -> None:
    if shutil.which("codex") is None:
        raise RuntimeError("Codex CLI was not found in PATH")
    subprocess.run(
        ["codex", "mcp", "remove", SERVER_NAME],
        check=False,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        codex_add_command(python, local_address=local_address, interface=interface),
        check=True,
    )


def register_claude_code(
    python: Path, *, local_address: str = "off", interface: str = "auto"
) -> None:
    if shutil.which("claude") is None:
        raise RuntimeError("Claude Code was not found in PATH")
    subprocess.run(
        ["claude", "mcp", "remove", SERVER_NAME, "--scope", "user"],
        check=False,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        claude_add_command(python, local_address=local_address, interface=interface),
        check=True,
    )


def configure_credentials() -> list[str]:
    """Prompt without echo and store only complete credential sets."""
    from core.credentials import CredentialStore

    store = CredentialStore(APP_HOME / "cabinets.json")
    saved: list[str] = []
    wb = getpass.getpass("WB read-only token (Enter to skip): ").strip()
    if wb:
        store.add_cabinet("wb", "main", {"token": wb}, make_active=True)
        saved.append("WB")
    ozon_id = getpass.getpass("Ozon Seller Client-Id (Enter to skip): ").strip()
    ozon_key = getpass.getpass("Ozon Seller Api-Key (Enter to skip): ").strip() if ozon_id else ""
    if ozon_id and ozon_key:
        store.add_cabinet(
            "ozon", "main", {"client_id": ozon_id, "api_key": ozon_key}, make_active=True
        )
        saved.append("Ozon Seller")
    perf_id = getpass.getpass("Ozon Performance Client-Id (Enter to skip): ").strip()
    perf_secret = getpass.getpass("Ozon Performance Client-Secret (Enter to skip): ").strip() if perf_id else ""
    if perf_id and perf_secret:
        store.add_cabinet(
            "ozon_perf", "main",
            {"client_id": perf_id, "client_secret": perf_secret},
            make_active=True,
        )
        saved.append("Ozon Performance")
    return saved


def write_install_record(*, app_dir: Path, network_mode: str, interface: str) -> Path:
    APP_HOME.mkdir(parents=True, exist_ok=True)
    record = APP_HOME / "readonly-install.json"
    record.write_text(json.dumps({
        "installed_at": datetime.now().isoformat(timespec="seconds"),
        "mcp_server": SERVER_NAME,
        "app_dir": str(app_dir),
        "read_only": True,
        "network_mode": network_mode,
        "network_interface": interface if network_mode == "auto" else None,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    with contextlib.suppress(OSError):
        os.chmod(record, 0o600)
    return record


def main() -> None:
    if sys.version_info < (3, 10):
        raise SystemExit("Python 3.10+ is required")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--direct-network", default="off", metavar="off|auto|IP")
    parser.add_argument("--interface", default="auto")
    parser.add_argument(
        "--client", choices=["auto", "codex", "claude-code"], default="auto",
        help="AI client to configure; auto configures every supported client found",
    )
    parser.add_argument("--skip-keys", action="store_true")
    parser.add_argument("--skip-register", action="store_true")
    args = parser.parse_args()

    validate_network_mode(args.direct_network, args.interface)
    app = install_app(HERE, APP_DIR)
    python = provision(app)
    clients = [] if args.skip_register else detect_clients(args.client)
    for client in clients:
        register = register_codex if client == "codex" else register_claude_code
        register(python, local_address=args.direct_network, interface=args.interface)
    saved = [] if args.skip_keys else configure_credentials()
    record = write_install_record(
        app_dir=app, network_mode=args.direct_network, interface=args.interface
    )
    print(f"Installed read-only MCP: {SERVER_NAME}")
    print(f"Configured clients: {', '.join(clients) if clients else 'registration skipped'}")
    print(f"Credentials saved locally for: {', '.join(saved) if saved else 'none'}")
    print(f"Install record: {record}")
    print("Restart Codex, then check /mcp. API credentials were not printed.")


if __name__ == "__main__":
    main()
