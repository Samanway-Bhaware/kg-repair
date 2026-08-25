# Installation

[← Manual index](README.md)

## Requirements

| | |
|---|---|
| Python | ≥ 3.10 |
| Runtime dependencies | **none** — the core is standard-library only |
| Operating system | any that runs CPython; developed and tested on macOS and Linux |
| Disk | the package itself is small; committed fixtures add a few tens of MB |

The zero-dependency core is a project rule, not an accident. Nothing under
`src/kgrepair/` may import a third-party package. This keeps the toolkit
installable in restricted environments and makes the repair path auditable
without vendoring anything.

## Installing

From the repository root:

```bash
pip install -e .
```

This puts the `kgrepair` package on the import path and the `kgrepair` command
on your `PATH`. `python -m kgrepair` works identically.

### Optional extras

Three extras exist. None of them is imported by anything under
`src/kgrepair/`, so the core stays stdlib-only whichever you install.

```bash
pip install -e ".[dev]"      # pytest — to run the test suite
pip install -e ".[viewer]"   # streamlit — for the browser inspection viewer
pip install -e ".[eval]"     # matplotlib — for the evaluation figures in scripts/
```

| Extra | Package | Needed for |
|---|---|---|
| `dev` | `pytest>=7.0` | `python -m pytest tests/` |
| `viewer` | `streamlit>=1.30` | `streamlit run app/main.py` — see [Viewer](viewer.md) |
| `eval` | `matplotlib>=3.5` | `scripts/build_evaluation.py`, which regenerates the figures in `docs/evaluation.md` |

Combine them as usual: `pip install -e ".[dev,viewer]"`.

## Verifying the install

```bash
python -c "import kgrepair; print(kgrepair.__version__)"
# 0.5.0

kgrepair --help
```

## Running the test suite

The suite is fully offline. It imports `kgrepair` the way a user does, from the
installed package, so **you must install before running it**:

```bash
pip install -e ".[dev]"
python -m pytest tests/ -q
# 578 passed in ~155s
```

Run a single test:

```bash
python -m pytest tests/test_toolkit.py::test_isect_shared_endpoint -q
```

`tests/conftest.py` adds only the repository directories that are deliberately
*not* part of the distribution and therefore can never be installed: the repo
root (for `app/` and `experimental/`) and `scripts/`. The standalone runners
under `app/`, `bench/` and `scripts/` keep their own `sys.path` inserts, so they
still run from a bare checkout without installing.

## What gets installed

Only `src/kgrepair/` and its subpackages are packaged
(`[tool.setuptools.packages.find] where = ["src"]`). These directories are part
of the repository but **not** part of the distribution:

| Directory | Contents | Why it is not packaged |
|---|---|---|
| `app/` | the Streamlit viewer | a demonstration skin, run from a checkout |
| `bench/` | benchmark and ladder runners | measurement tooling |
| `scripts/` | evaluation and reporting scripts | reporting tooling; uses matplotlib |
| `experimental/` | the constraint-mining sprint | isolated, never promoted |
| `fixtures/`, `results/`, `eval/` | committed data and measurements | research artefacts |
| `tests/` | the pytest suite | — |

## Licence

The toolkit is **MIT-licensed**. Copyright © 2026 Samanway Bhaware and Nina
Pardal. `pyproject.toml` declares the SPDX expression under
[PEP 639](https://peps.python.org/pep-0639/):

```toml
license = "MIT"
license-files = ["LICENSE"]
```

which is why the build requires `setuptools>=77`. The licence file is packaged
into both distribution formats — `kgrepair-<version>.dist-info/licenses/LICENSE`
in the wheel, and the repository root in the sdist — so a downstream user
always receives the terms with the code.

### The code licence does not cover the data

This is the part worth reading before you redistribute anything. MIT covers the
toolkit's **own source code and documentation**. It does not cover the
knowledge-graph **datasets** the toolkit reads, nor the slices committed under
`fixtures/`, `data/` and `eval/`, which derive from third-party sources under
separate terms:

| Source | Terms | Consequence |
|---|---|---|
| **Wikidata** | CC0 1.0 (public domain dedication) | no conditions on reuse |
| **DBpedia** | CC BY-SA 3.0 | attribution **and** share-alike, which **propagates into derived material** — including a graph this toolkit repaired |
| **YAGO 4.5** | see the YAGO project's own terms | verify before redistributing |

The share-alike propagation is the trap: a repaired graph derived from a DBpedia
slice inherits CC BY-SA, regardless of the MIT licence on the code that produced
it. Attaching per-source licence metadata to released bundles is tracked as its
own deliverable.

If you only ever run the toolkit against **your own** graphs, none of this
applies — you take the code under MIT and your data stays yours.

---

Next: [Quickstart](quickstart.md)
