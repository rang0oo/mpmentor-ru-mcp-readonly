from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import install
import pytest


ROOT = Path(__file__).resolve().parents[1]


def test_install_app_copies_only_runtime_and_has_no_personal_paths(tmp_path):
    app = install.install_app(ROOT, tmp_path / "app")
    assert (app / "readonly_mcp" / "server.py").exists()
    assert (app / "core" / "network.py").exists()
    assert not (app / ".git").exists()
    assert not (app / "tests").exists()
    text = "\n".join(
        path.read_text(encoding="utf-8", errors="ignore")
        for path in app.rglob("*") if path.is_file()
    )
    assert "/Users/" not in text


def test_codex_add_command_is_secret_free_and_portable(tmp_path):
    python = tmp_path / "app" / ".venv" / "bin" / "python"
    command = install.codex_add_command(
        python, local_address="auto", interface="en0"
    )
    joined = " ".join(command)
    assert command[:4] == ["codex", "mcp", "add", "marketplaces-ru-readonly"]
    assert "MARKETPLACES_LOCAL_ADDRESS=auto" in command
    assert "MARKETPLACES_NETWORK_INTERFACE=en0" in command
    assert "WB_API_TOKEN" not in joined
    assert "OZON_API_KEY" not in joined
    assert command[-2:] == ["-m", "readonly_mcp.server"]


def test_claude_add_command_uses_user_scope_and_contains_no_secrets(tmp_path):
    python = tmp_path / "app" / ".venv" / "Scripts" / "python.exe"
    command = install.claude_add_command(
        python, local_address="auto", interface="Wi-Fi"
    )
    joined = " ".join(command)
    assert command[:4] == ["claude", "mcp", "add", "marketplaces-ru-readonly"]
    assert "--scope" in command and "user" in command
    assert "MARKETPLACES_NETWORK_INTERFACE=Wi-Fi" in command
    assert "WB_API_TOKEN" not in joined and "OZON_API_KEY" not in joined
    assert command[-2:] == ["-m", "readonly_mcp.server"]


def test_register_codex_replaces_its_existing_entry(tmp_path, monkeypatch):
    calls: list[tuple[list[str], dict]] = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(install.subprocess, "run", fake_run)
    install.register_codex(tmp_path / "python", local_address="off", interface="en0")
    assert calls[0][0] == ["codex", "mcp", "remove", "marketplaces-ru-readonly"]
    assert calls[0][1]["check"] is False
    assert calls[1][0][:4] == ["codex", "mcp", "add", "marketplaces-ru-readonly"]
    assert calls[1][1]["check"] is True
    assert all("WB_API" not in " ".join(command) for command, _ in calls)


def test_register_claude_code_replaces_user_scope_entry(tmp_path, monkeypatch):
    calls: list[tuple[list[str], dict]] = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(install.shutil, "which", lambda name: f"/bin/{name}")
    monkeypatch.setattr(install.subprocess, "run", fake_run)
    install.register_claude_code(
        tmp_path / "python", local_address="off", interface="auto"
    )
    assert calls[0][0] == [
        "claude", "mcp", "remove", "marketplaces-ru-readonly", "--scope", "user",
    ]
    assert calls[0][1]["check"] is False
    assert calls[1][0][:4] == ["claude", "mcp", "add", "marketplaces-ru-readonly"]
    assert calls[1][1]["check"] is True


def test_detect_clients_returns_every_installed_supported_client(monkeypatch):
    monkeypatch.setattr(
        install.shutil, "which", lambda name: f"/bin/{name}" if name in {"codex", "claude"} else None
    )
    assert install.detect_clients("auto") == ["codex", "claude-code"]
    assert install.detect_clients("claude-code") == ["claude-code"]


def test_windows_launcher_is_packaged():
    launcher = ROOT / "install.bat"
    assert launcher.exists()
    text = launcher.read_text(encoding="utf-8")
    assert "py -3" in text


def test_direct_network_validation_rejects_false_success(monkeypatch):
    monkeypatch.setattr("core.network.resolve_local_address", lambda _env: None)
    with pytest.raises(RuntimeError, match="physical network interface"):
        install.validate_network_mode("auto", "Wi-Fi")


def test_direct_network_validation_accepts_disabled_mode(monkeypatch):
    monkeypatch.setattr(
        "core.network.resolve_local_address",
        lambda _env: (_ for _ in ()).throw(AssertionError("must not inspect network")),
    )
    install.validate_network_mode("off", "auto")


def test_write_install_record_contains_no_credentials(tmp_path, monkeypatch):
    monkeypatch.setattr(install, "APP_HOME", tmp_path)
    record = install.write_install_record(
        app_dir=tmp_path / "app", network_mode="auto", interface="en0"
    )
    data = json.loads(record.read_text(encoding="utf-8"))
    assert data["mcp_server"] == "marketplaces-ru-readonly"
    assert data["read_only"] is True
    blob = record.read_text(encoding="utf-8")
    assert "api_key" not in blob.lower()
    assert "token" not in blob.lower()


def test_provision_uses_symlinks_on_posix_for_portable_python(monkeypatch, tmp_path):
    created: list[tuple[bool, Path]] = []

    class FakeBuilder:
        def __init__(self, *, with_pip, symlinks):
            assert with_pip is True
            created.append((symlinks, Path()))

        def create(self, destination):
            created[-1] = (created[-1][0], Path(destination))
            python = install.venv_python(tmp_path)
            python.parent.mkdir(parents=True)
            python.touch()

    monkeypatch.setattr(install.venv, "EnvBuilder", FakeBuilder)
    monkeypatch.setattr(install.subprocess, "run", lambda *a, **k: None)
    install.provision(tmp_path)
    assert created == [(install.os.name != "nt", tmp_path / ".venv")]
