"""Shared dataclasses used across modules — no chorus_forms imports
to avoid pulling the heavy lazy-load chain into spec.py."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class DomainValue:
    """A single (value, description) pair for a combobox."""
    value: str
    description: str = ""


@dataclass(frozen=True)
class EmitResult:
    """Returned by build_form — the three written file paths."""
    csd_path: Path
    uxb_path: Path
    manifest_path: Path
