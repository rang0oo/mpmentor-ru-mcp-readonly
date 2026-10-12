from pathlib import Path

from core.credentials import CredentialStore


def test_tests_never_use_live_credential_store():
    live_store = Path.home() / ".marketplace-mcp" / "cabinets.json"
    assert CredentialStore().path != live_store
