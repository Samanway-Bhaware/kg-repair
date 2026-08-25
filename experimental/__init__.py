"""Constraint-mining sprint (CM), isolated from the core toolkit.

Everything under experimental/ imports FROM src/kgrepair but is never imported BY
it -- enforced by tests/test_experimental_isolation.py. Nothing here enters the
core toolkit, the CLI/viewer defaults, or the shipped v1/v2 constraint files. See
experimental/mining/__init__.py and docs/ml_mining.md for the sprint write-up.
"""
