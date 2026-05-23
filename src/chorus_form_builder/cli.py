"""CLI entry point — argparse + exit-code mapping.

Maps each exception class from the library to a stable exit code:
    0 — success
    1 — spec validation failure (or general IO problem on the spec file)
    2 — binding (fetch / JSONPath) failure
    3 — emit failure
    4 — unexpected IO failure
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from chorus_form_builder import (
    BindingError,
    EmitError,
    HttpxFetcher,
    NoFetchFetcher,
    SpecValidationError,
    build_form,
)


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="chorus-form-build",
        description="Generate Chorus forms (.csd + UXB JSON) from a declarative YAML spec.",
    )
    p.add_argument("--spec", type=Path, required=True, help="Path to the form-spec YAML file")
    p.add_argument("--output", type=Path, required=True, help="Output directory (created if missing)")
    p.add_argument(
        "--no-fetch",
        action="store_true",
        help="Skip OpenAPI fetches — static `values:` only. Errors if any binding is present.",
    )
    verbosity = p.add_mutually_exclusive_group()
    verbosity.add_argument("--quiet", "-q", action="store_true", help="Errors only")
    verbosity.add_argument("--verbose", "-v", action="store_true", help="Show per-field resolution")
    return p


def main(argv: list[str] | None = None) -> int:
    """CLI entry point. Returns exit code; sys.exit-style usage in __main__."""
    parser = _build_parser()
    args = parser.parse_args(argv)

    fetcher = NoFetchFetcher() if args.no_fetch else HttpxFetcher()

    try:
        result = build_form(args.spec, args.output, fetcher=fetcher)
    except SpecValidationError as e:
        print(f"spec validation error: {e}", file=sys.stderr)
        return 1
    except BindingError as e:
        print(f"binding error: {e}", file=sys.stderr)
        return 2
    except EmitError as e:
        print(f"emit error: {e}", file=sys.stderr)
        return 3
    except OSError as e:
        print(f"IO error: {e}", file=sys.stderr)
        return 4

    if not args.quiet:
        rel_out = result.csd_path.parent
        print(
            f"Wrote {result.csd_path.name} + .uxb.json + _manifest.json -> {rel_out}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
