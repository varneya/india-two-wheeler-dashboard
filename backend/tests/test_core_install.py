"""Core installations must boot without optional clustering/forecast packages."""

from pathlib import Path
import re
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[2]
# Run in a fresh interpreter so optional packages cannot hide in sys.modules.
BLOCK_OPTIONAL = '''
import importlib.abc
import sys
class NoML(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'sklearn', 'hdbscan', 'umap', 'prophet', 'torch', 'sentence_transformers'}:
            raise ModuleNotFoundError(f"Optional package unavailable: {fullname}")
sys.meta_path.insert(0, NoML())
'''


@pytest.mark.parametrize("installer", ["install_backend.sh", "install_backend.ps1"])
def test_installer_smoke_command_uses_only_core_packages(installer):
    text = (ROOT / 'scripts' / installer).read_text()
    smoke = re.search(r'-c "(import [^"\n]+)"', text)
    assert smoke is not None, 'Installer must include a Python import smoke check'
    result = subprocess.run(
        [sys.executable, '-c', BLOCK_OPTIONAL + '\n' + smoke.group(1)],
        cwd=ROOT, capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr


def test_api_import_does_not_require_ml_or_open_database():
    code = BLOCK_OPTIONAL + '''
import sqlite3
def forbidden(*args, **kwargs):
    raise AssertionError('Importing the app must not open a database')
sqlite3.connect = forbidden
import main
assert main.app.title
assert not any(name in sys.modules for name in ['hdbscan', 'umap', 'prophet'])
'''
    result = subprocess.run(
        [sys.executable, '-c', code], cwd=ROOT / 'backend',
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr
