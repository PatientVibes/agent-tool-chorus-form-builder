"""chorus-form-builder — generate Chorus forms from declarative YAML.

Public API:
    build_form(spec_path, output_dir, *, fetcher=None) -> EmitResult

Exceptions:
    FormBuilderError (base)
    SpecValidationError
    BindingError
    EmitError
    FormBuilderIOError

Both are populated in later tasks; this is just the package marker.
"""
__version__ = "0.1.0"
