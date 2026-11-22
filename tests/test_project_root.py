import json
from pathlib import Path
import os
import subprocess
import sys


def test_root_override_applies_to_ui_and_both_temporary_stores(tmp_path):
    env = dict(os.environ, NEXDATA_ROOT=str(tmp_path))
    code = ('import json; from app.ui.main import ROOT, SETTINGS; from app.pipeline import TMP; '
            'from app.parsers.chrome import TMP as CHROME_TMP; '
            'print(json.dumps([str(p) for p in (ROOT, SETTINGS, TMP, CHROME_TMP)]))')
    result = subprocess.run([sys.executable, '-c', code], env=env, capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr
    assert [Path(p) for p in json.loads(result.stdout)] == [tmp_path, tmp_path / '.cache/settings.json',
                                                          tmp_path / '.cache/tmp', tmp_path / '.cache/tmp']


def test_default_root_uses_package_location(monkeypatch):
    from app.paths import project_root
    monkeypatch.delenv('NEXDATA_ROOT', raising=False)
    assert project_root() == Path(__file__).resolve().parents[1]
