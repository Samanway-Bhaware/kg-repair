"""
Test-suite path setup.

`kgrepair` itself is NOT put on `sys.path` here: the package is pip-installed
(`pip install -e .` from the repo root, see README), so the tests import it the
same way any user does, with no path manipulation. If `import kgrepair` fails,
the package is not installed and that is the thing to fix.

What this file does add are the repo directories that are deliberately not part
of the distribution and so can never be installed: `app/` (the Streamlit viewer),
`experimental/` (the constraint-mining sprint), `scripts/` (the evaluation
report builder), and `bench/` (the corpus builders and size-ladder runners).
Tests that exercise those import them from the working tree.
"""
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

for _p in (_ROOT, os.path.join(_ROOT, "scripts"), os.path.join(_ROOT, "bench")):
    if _p not in sys.path:
        sys.path.insert(0, _p)
