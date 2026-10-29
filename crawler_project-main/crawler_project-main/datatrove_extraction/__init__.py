"""Extraction package with optional inspection dependencies loaded on demand."""

__all__ = ["DocumentStructureInspector"]


def __getattr__(name):
    if name == "DocumentStructureInspector":
        from .helpers.main_helpers.document_inspector import DocumentStructureInspector
        return DocumentStructureInspector
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
