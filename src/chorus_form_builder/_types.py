"""Shared dataclasses used across modules — no chorus_forms imports
to avoid pulling the heavy lazy-load chain into spec.py."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


class FormBuilderError(Exception):
    """Base for all chorus_form_builder errors.

    SpecValidationError, BindingError, and EmitError all subclass this so
    callers can do `except FormBuilderError` for catch-all handling while
    still being able to discriminate on the specific subclass.
    """


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
