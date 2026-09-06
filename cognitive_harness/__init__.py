# FILE: cognitive-harness/__init__.py
"""Cognitive Harness — structural reasoning and epistemic warrant.

Version is derived from installed package metadata.
"""
from __future__ import annotations

from importlib.metadata import version, PackageNotFoundError

try:
    __version__ = version("cognitive-harness")
except PackageNotFoundError:
    __version__ = "0+unknown"
