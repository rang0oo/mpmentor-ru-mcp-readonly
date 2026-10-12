from __future__ import annotations

import runpy
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "marketplaces-readonly" / "SKILL.md"
BOOTSTRAP = ROOT / "skills" / "marketplaces-readonly" / "scripts" / "install.py"


def test_skill_has_valid_minimal_frontmatter():
    text = SKILL.read_text(encoding="utf-8")
    front = yaml.safe_load(text.split("---", 2)[1])
    assert set(front) == {"name", "description"}
    assert front["name"] == "marketplaces-readonly"
    assert len(front["description"]) <= 1024


def test_skill_package_contains_bootstrap_and_no_personal_paths():
    assert BOOTSTRAP.exists()
    blob = "\n".join(
        p.read_text(encoding="utf-8", errors="ignore")
        for p in SKILL.parent.rglob("*") if p.is_file()
    )
    assert "/Users/" not in blob
    assert "WBOZON Agent" not in blob


def test_bootstrap_zip_member_guard():
    namespace = runpy.run_path(str(BOOTSTRAP), run_name="skill_bootstrap_test")
    safe_member = namespace["safe_member"]
    assert safe_member("repo-main/core/client.py")
    assert not safe_member("../../private.txt")
    assert not safe_member("/absolute/private.txt")


def test_bootstrap_downloads_from_mpmentor_repository():
    text = BOOTSTRAP.read_text(encoding="utf-8")
    assert "rang0oo/mpmentor-ru-mcp-readonly" in text
    assert "rang0oo/marketplaces-mcp-ru-readonly" not in text
