"""
Packaging gate: the installed distribution exposes a documented public API.

These tests deliberately import `kgrepair` the way a user does, from the
installed package, with no `sys.path` manipulation (see `tests/conftest.py`).
If they fail with ImportError, the package is not installed: run
`pip install -e .` from the repo root.
"""
import ast
import os
import subprocess
import sys

import pytest

import kgrepair

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "src", "kgrepair")

# The documented public surface. Adding a name here without documenting it in
# `kgrepair/api.py` is the mistake this list exists to make visible.
EXPECTED_PUBLIC = {
    "__version__",
    "DataGraph", "load_graph", "load_graph_string", "load_ntriples",
    "load_ntriples_file", "to_ntriples", "write_ntriples", "DEFAULT_TYPE_PREDICATES",
    "Constraint", "ConstraintSet", "constraints", "load_constraint_file",
    "save_constraint_file",
    "Validator", "ValidationReport", "Violation", "validate",
    "subset_repair", "SubsetRepairResult", "superset_repair", "SupersetRepairResult",
    "ChangeRecord",
    "check_cap", "CapDecision", "subset_witness_fraction",
    "superset_addition_fraction", "SUBSET_CAP_DEFAULT", "SUPERSET_CAP_DEFAULT",
    "ABORTED_BY_CAP",
    "extract_neighbourhood", "NeighbourhoodView", "NVNode", "NVEdge",
    "change_record_center", "DEFAULT_K", "DEFAULT_NODE_CAP",
    "report_envelope",
    # quality metrics (P8b, Objective 5); definitions in docs/quality_metrics.md
    "compute_metrics", "GraphMetrics", "compare_metrics", "MetricComparison",
    "MetricChange", "repair_metrics_block", "metric_field_names",
    "split_type_predicates", "DEFAULT_INSTANCE_OF", "DEFAULT_SUBCLASS_OF",
    "write_bundle", "zip_bundle", "diff_lines", "reconstruct_input",
    "bundle_summary",
    "RunContext", "constraints_meta", "slice_meta_from_graph", "code_revision",
    "apply_allowlist", "load_allowlist_file", "AllowList",
    # constraint derivation and the review airlock
    "derive_candidate_file", "fill_impact", "read_candidate_file",
    "write_canonical",
    "merge_candidates", "set_status", "seal_candidates", "reviewed_constraint_set",
    "graph_content_hash", "attach_review_attestations",
    "Candidate", "CandidateFile", "CandidateGateError", "NotSealed",
    "ReviewIncomplete", "SealMismatch", "SourceDrift", "OutOfFragment",
    "BoundaryNotRepairable", "NothingAccepted",
}


def test_every_documented_symbol_is_exported():
    for name in EXPECTED_PUBLIC:
        assert hasattr(kgrepair, name), f"kgrepair.{name} is missing"
    assert set(kgrepair.__all__) == EXPECTED_PUBLIC


def test_public_symbols_are_docstringed():
    """Every exported symbol carries a real docstring. A dataclass's auto-generated
    `ClassName(field: type, ...)` signature does not count as one."""
    undocumented = []
    for name in sorted(kgrepair.__all__):
        obj = getattr(kgrepair, name)
        if name == "__version__" or isinstance(obj, frozenset):
            continue
        doc = (getattr(obj, "__doc__", None) or "").strip()
        if not doc or doc.startswith(f"{name}("):
            undocumented.append(name)
    assert undocumented == [], f"public symbols with no docstring: {undocumented}"


def test_api_module_docstring_lists_the_surface():
    doc = kgrepair.api.__doc__
    assert doc and "Public surface" in doc
    assert "internal and unstable" in doc
    for name in ("load_constraint_file", "apply_allowlist", "superset_repair"):
        assert name in doc


def test_version_is_a_nonempty_string():
    assert isinstance(kgrepair.__version__, str) and kgrepair.__version__.strip()


def test_version_matches_the_installed_distribution():
    """pyproject reads the version dynamically from `kgrepair.__version__`, so the
    installed metadata and the attribute cannot drift apart."""
    from importlib import metadata
    assert metadata.version("kgrepair") == kgrepair.__version__


def test_pyproject_declares_no_third_party_core_dependencies():
    try:
        import tomllib                      # stdlib, Python 3.11+
    except ModuleNotFoundError:             # 3.10, the declared floor
        import tomli as tomllib
    with open(os.path.join(ROOT, "pyproject.toml"), "rb") as fh:
        cfg = tomllib.load(fh)
    assert cfg["project"]["dependencies"] == []
    extras = cfg["project"]["optional-dependencies"]
    assert any("matplotlib" in d for d in extras["eval"])
    assert any("streamlit" in d for d in extras["viewer"])
    assert any("pytest" in d for d in extras["dev"])
    assert cfg["project"]["requires-python"] == ">=3.10"
    assert cfg["tool"]["setuptools"]["dynamic"]["version"] == {"attr": "kgrepair.__version__"}


def test_public_import_pulls_in_no_optional_extra():
    """A fresh interpreter that imports kgrepair and walks the whole public API must
    not have loaded matplotlib or streamlit. Run out of process so that an extra
    already imported by another test cannot mask the result."""
    code = (
        "import sys, kgrepair\n"
        "[getattr(kgrepair, n) for n in kgrepair.__all__]\n"
        "bad = [m for m in ('matplotlib', 'streamlit') if m in sys.modules]\n"
        "print(','.join(bad))\n"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                         cwd=os.sep)
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "", f"optional extra imported by core: {out.stdout}"


def test_no_core_module_imports_an_optional_extra():
    """Static belt for the runtime check: no source file under src/kgrepair may
    name matplotlib or streamlit in an import statement."""
    offenders = []
    for dirpath, _dirs, files in os.walk(SRC):
        for name in files:
            if not name.endswith(".py"):
                continue
            path = os.path.join(dirpath, name)
            tree = ast.parse(open(path, encoding="utf-8").read())
            for node in ast.walk(tree):
                mods = []
                if isinstance(node, ast.Import):
                    mods = [a.name for a in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module:
                    mods = [node.module]
                for m in mods:
                    if m.split(".")[0] in ("matplotlib", "streamlit"):
                        offenders.append(f"{os.path.relpath(path, ROOT)}: {m}")
    assert offenders == [], offenders


def test_core_imports_are_stdlib_only():
    """Every top-level module a core file imports is either stdlib or kgrepair's
    own. This is the packaging rule that keeps `dependencies = []` honest."""
    stdlib = set(sys.stdlib_module_names)
    offenders = []
    for dirpath, _dirs, files in os.walk(SRC):
        for name in files:
            if not name.endswith(".py"):
                continue
            path = os.path.join(dirpath, name)
            tree = ast.parse(open(path, encoding="utf-8").read())
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    names = [a.name.split(".")[0] for a in node.names]
                elif isinstance(node, ast.ImportFrom):
                    if node.level:            # relative: kgrepair's own
                        continue
                    names = [node.module.split(".")[0]] if node.module else []
                else:
                    continue
                for m in names:
                    if m not in stdlib and m != "kgrepair":
                        offenders.append(f"{os.path.relpath(path, ROOT)}: {m}")
    assert offenders == [], offenders


# ---------- constraint-file round trip --------------------------------------

def test_constraint_file_roundtrip_is_identical(tmp_path):
    cs = kgrepair.constraints.get("geography", "wikidata")
    path = str(tmp_path / "geo.json")
    assert kgrepair.save_constraint_file(cs, path) == path

    back = kgrepair.load_constraint_file(path)
    assert back.to_dict() == cs.to_dict()
    assert [c.to_dict() for c in back] == [c.to_dict() for c in cs]
    assert back.name == cs.name


def test_constraint_file_roundtrip_is_byte_stable(tmp_path):
    """Writing, reading and writing again yields identical bytes, so a constraint
    file is a stable artifact rather than something that churns per run."""
    cs = kgrepair.constraints.get("anatomy", "wikidata")
    first, second = str(tmp_path / "a.json"), str(tmp_path / "b.json")
    kgrepair.save_constraint_file(cs, first)
    kgrepair.save_constraint_file(kgrepair.load_constraint_file(first), second)
    assert open(first, "rb").read() == open(second, "rb").read()


def test_loaded_constraint_file_drives_validation(tmp_path):
    """A set that has been through a file is usable by the validator unchanged."""
    fx = os.path.join(ROOT, "fixtures", "synthetic_geography_wd.nt")
    g = kgrepair.load_graph(fx)
    cs = kgrepair.constraints.get("geography", "wikidata")
    path = str(tmp_path / "geo.json")
    kgrepair.save_constraint_file(cs, path)

    direct = kgrepair.validate(g, cs)
    from_file = kgrepair.validate(g, kgrepair.load_constraint_file(path))
    assert {v.constraint.cid: sorted(v.witnesses) for v in direct.failing()} == \
           {v.constraint.cid: sorted(v.witnesses) for v in from_file.failing()}


def test_compile_now_rejects_an_expression_outside_the_fragment(tmp_path):
    from kgrepair.gxpath import ParseError
    bad = kgrepair.ConstraintSet("custom@mine", [
        kgrepair.Constraint(cid="x", domain="d", kg="k", kind="typing_existence",
                            tier="ptime_core", provenance="derived", direction="superset",
                            antecedent="< down(:p) >", consequent='! val("C")'),
    ])
    path = str(tmp_path / "bad.json")
    kgrepair.save_constraint_file(bad, path)
    kgrepair.load_constraint_file(path)                       # lazy: no parse yet
    with pytest.raises(ParseError):
        kgrepair.load_constraint_file(path, compile_now=True)
