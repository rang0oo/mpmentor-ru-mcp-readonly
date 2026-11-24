#!/usr/bin/env python3
"""Download the public project and run its portable installer."""
from __future__ import annotations

import os
import shutil
import stat
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath

DEFAULT_ARCHIVE = (
    "https://github.com/rang0oo/mpmentor-ru-mcp-readonly/"
    "archive/refs/tags/v0.3.0.zip"
)


def safe_member(name: str) -> bool:
    if not name or any(char in name for char in ('\\', ':', '\x00')):
        return False
    path = PurePosixPath(name)
    return not path.is_absolute() and ".." not in path.parts


def main() -> None:
    archive_url = os.environ.get("MARKETPLACES_MCP_ARCHIVE_URL", DEFAULT_ARCHIVE)
    with tempfile.TemporaryDirectory(prefix="marketplaces-readonly-") as temp:
        temp_path = Path(temp)
        archive = temp_path / "source.zip"
        bundled = Path(__file__).resolve().parents[1] / 'assets' / 'server.zip'
        if bundled.is_file() and not os.environ.get('MARKETPLACES_MCP_ARCHIVE_URL'):
            print('Using the bundled read-only marketplace integration…')
            shutil.copyfile(bundled, archive)
        else:
            print("Downloading the read-only marketplace integration…")
            urllib.request.urlretrieve(archive_url, archive)
        with zipfile.ZipFile(archive) as package:
            members = package.infolist()
            unsafe = [item.filename for item in members
                      if not safe_member(item.filename)
                      or stat.S_ISLNK(item.external_attr >> 16)]
            if unsafe:
                raise RuntimeError("The downloaded archive contains unsafe paths")
            if len(members) > 5000 or sum(item.file_size for item in members) > 128 * 1024 * 1024:
                raise RuntimeError('The downloaded archive exceeds the installation size limit')
            package.extractall(temp_path / "source")
        installers = list((temp_path / "source").glob("*/install.py"))
        if len(installers) != 1:
            raise RuntimeError("The downloaded package does not contain exactly one installer")
        subprocess.run([sys.executable, str(installers[0]), *sys.argv[1:]], check=True)


if __name__ == "__main__":
    main()
