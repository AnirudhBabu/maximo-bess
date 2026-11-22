"""Data-quality checks.

Importing this package registers every check.  Call :func:`run_checks` with any
:class:`mxbess.repository.Repository`.
"""

from __future__ import annotations

from . import assets as _assets  # noqa: F401  (import registers checks)
from . import pm as _pm  # noqa: F401
from . import workorders as _workorders  # noqa: F401
from ._core import (
    ALL_CODES,
    REGISTRY,
    SEVERITY_BY_CODE,
    Finding,
    Severity,
    check,
    make_finding,
    run_checks,
)

__all__ = [
    "ALL_CODES",
    "REGISTRY",
    "SEVERITY_BY_CODE",
    "Finding",
    "Severity",
    "check",
    "make_finding",
    "run_checks",
]
