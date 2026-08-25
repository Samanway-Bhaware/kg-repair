"""
CM sprint hard isolation rule: experimental/ imports FROM src/kgrepair but is
never imported BY it. Enforced here rather than assumed -- a future change that
adds a stray `import experimental...` inside the core library fails this test
immediately instead of silently coupling an exploratory experiment to the
shipped toolkit.
"""
from __future__ import annotations

import os
import re

_ROOT = os.path.join(os.path.dirname(__file__), "..")
_SRC_KGREPAIR = os.path.join(_ROOT, "src", "kgrepair")
_IMPORT_EXPERIMENTAL = re.compile(r"^\s*(import\s+experimental\b|from\s+experimental\b)",
                                  re.MULTILINE)


def _all_py_files(root: str):
    for dirpath, _dirs, files in os.walk(root):
        for name in files:
            if name.endswith(".py"):
                yield os.path.join(dirpath, name)


def test_core_library_never_imports_experimental():
    offenders = []
    for path in _all_py_files(_SRC_KGREPAIR):
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
        if _IMPORT_EXPERIMENTAL.search(text):
            offenders.append(os.path.relpath(path, _ROOT))
    assert offenders == [], (
        f"src/kgrepair must never import experimental/: found imports in {offenders}")


def test_experimental_mining_package_exists_and_is_isolated():
    mining_dir = os.path.join(_ROOT, "experimental", "mining")
    assert os.path.isdir(mining_dir)
    assert os.path.exists(os.path.join(_ROOT, "experimental", "__init__.py"))
    assert os.path.exists(os.path.join(mining_dir, "__init__.py"))
