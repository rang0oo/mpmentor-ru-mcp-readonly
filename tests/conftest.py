"""Keep all offline tests away from the user's real marketplace credentials."""

import os
import tempfile


# conftest is loaded before test modules import core.credentials, whose default
# store path is bound at import time. Use a fresh empty directory per test run.
_credential_home = tempfile.TemporaryDirectory(prefix="marketplace-mcp-test-")
os.environ["MARKETPLACE_MCP_HOME"] = _credential_home.name


def pytest_sessionfinish(session, exitstatus):
    _credential_home.cleanup()
