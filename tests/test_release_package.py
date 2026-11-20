import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('release_package', ROOT / 'scripts/package_release.py')
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


def test_release_includes_readonly_runtime_and_installed_skill():
    files = {p.relative_to(ROOT).as_posix() for p in release.collect()}
    required = {'readonly_mcp/server.py', 'readonly_mcp/rnp.py', 'readonly_mcp/rnp.html',
                'readonly_mcp/analytics.py', 'readonly_mcp/finance.py',
                'readonly_mcp/skills/product-rnp/SKILL.md', 'MANIFEST.in'}
    assert required <= files


def test_skill_zip_is_minimal_and_portable(tmp_path, monkeypatch):
    import zipfile
    monkeypatch.setattr(release, 'ROOT', ROOT)
    path = release.build_skill(tmp_path)
    with zipfile.ZipFile(path) as archive:
        assert set(archive.namelist()) == {'marketplaces-readonly/SKILL.md',
                                        'marketplaces-readonly/scripts/install.py'}
        assert archive.testzip() is None
        for name in archive.namelist():
            assert b'/Users/' not in archive.read(name)
