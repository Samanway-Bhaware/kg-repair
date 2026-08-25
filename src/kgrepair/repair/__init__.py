"""
Repair engines (D5/D6).

D5 SubsetRepair (Algorithm 1) -- implemented in `subset.py`: the deterministic
canonical witness-deletion repair by monotone node deletion for ptime_core/subset
constraints.

D6 SupersetRepair (Algorithm 2) -- implemented in `superset.py`: the deterministic
canonical addition repair with redundancy pruning, addition-only over the bounded
value pool for all ptime_core constraints. RDF export planned (`export_rdf.py`).
"""
from .subset import ChangeRecord, SubsetRepairResult, eligible_constraints, subset_repair
from .superset import (NoSupersetPlan, SupersetRepairResult, core_constraints,
                       named_constants, superset_repair)

__all__ = [
    "subset_repair",
    "SubsetRepairResult",
    "ChangeRecord",
    "eligible_constraints",
    "superset_repair",
    "SupersetRepairResult",
    "core_constraints",
    "named_constants",
    "NoSupersetPlan",
]
