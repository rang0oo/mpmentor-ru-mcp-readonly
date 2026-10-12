#!/usr/bin/env python3
"""Download the public project and run its portable installer."""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath

DEFAULT_ARCHIVE = (
    "https://github.com/rang0oo/mpmentor-ru-mcp-readonly/"
    "archive/refs/heads/main.zip"
)


def safe_member(name: str) -> bool:
    path = PurePosixPath(name)
    return not path.is_absolute() and ".." not in path.parts


def main() -> None:
    archive_url = os.environ.get("MARKETPLACES_MCP_ARCHIVE_URL", DEFAULT_ARCHIVE)
    with tempfile.TemporaryDirectory(prefix="marketplaces-readonly-") as temp:
        temp_path = Path(temp)
        archive = temp_path / "source.zip"
        print("Downloading the read-only marketplace integration…")
        urllib.request.urlretrieve(archive_url, archive)
        with zipfile.ZipFile(archive) as package:
            unsafe = [item.filename for item in package.infolist() if not safe_member(item.filename)]
            if unsafe:
                raise RuntimeError("The downloaded archive contains unsafe paths")
            package.extractall(temp_path / "source")
        installers = list((temp_path / "source").glob("*/install.py"))
        if len(installers) != 1:
            raise RuntimeError("The downloaded package does not contain exactly one installer")
        subprocess.run([sys.executable, str(installers[0]), *sys.argv[1:]], check=True)


if __name__ == "__main__":
    main()
