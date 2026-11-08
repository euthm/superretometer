"""Portable, runner-reported test evidence. No commands execute on import.

Install the optional ``evidence`` extra to use this API.
"""

from .capture import record
from .contracts import EvidenceError, verify
from .workflow import Target, evaluate, export_bundle, import_receipt

__all__ = ["EvidenceError", "Target", "record", "verify", "import_receipt",
           "evaluate", "export_bundle"]
