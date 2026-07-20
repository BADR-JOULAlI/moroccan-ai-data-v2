"""
DocumentStructureInspector — a datatrove PipelineStep that reveals the
structure (attributes, types, nested keys) of every Document flowing through
the pipeline **without printing any actual content**.

Drop it anywhere in a pipeline list to see what your documents look like:

    from helpers.main_helpers.document_inspector import DocumentStructureInspector

    pipeline = [
        WarcGeneralReader(...),
        DocumentStructureInspector(output_folder="inspect_output"),  # <-- inspect here
        Trafilatura(...),
        DocumentStructureInspector(output_folder="inspect_output"),  # <-- and/or here
        JsonlWriter(...),
    ]

    # Or print to terminal (no output_folder):
    DocumentStructureInspector()

It is a pure passthrough — every document is yielded unchanged.
"""

from __future__ import annotations

import json
import logging
import os
from collections import OrderedDict
from datetime import datetime
from typing import Any

from datatrove.data import Document, DocumentsPipeline, Media
from datatrove.pipeline.base import PipelineStep

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _type_label(value: Any) -> str:
    """Return a concise human-readable type label for *value*."""
    if value is None:
        return "None"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, str):
        return f"str(len={len(value)})"
    if isinstance(value, bytes):
        return f"bytes(len={len(value)})"
    if isinstance(value, list):
        if len(value) == 0:
            return "list(empty)"
        inner = _type_label(value[0])
        return f"list(len={len(value)}, item_type={inner})"
    if isinstance(value, dict):
        return f"dict(keys={len(value)})"
    return type(value).__name__


def _build_schema(obj: Any, *, depth: int = 0, max_depth: int = 10) -> Any:
    """Recursively build a lightweight schema tree for *obj*.

    Returns nested ``OrderedDict`` / ``list`` / ``str`` where every leaf is a
    type description string.  Values are never included.
    """
    if depth > max_depth:
        return "...max_depth_reached..."

    if isinstance(obj, dict):
        schema: OrderedDict[str, Any] = OrderedDict()
        for key in sorted(obj.keys()):
            schema[key] = _build_schema(obj[key], depth=depth + 1, max_depth=max_depth)
        return schema

    if isinstance(obj, (list, tuple)):
        if len(obj) == 0:
            return f"{type(obj).__name__}(empty)"
        # Show schema of the first element as representative
        first_schema = _build_schema(obj[0], depth=depth + 1, max_depth=max_depth)
        return {
            "__list_length__": len(obj),
            "__item_schema__": first_schema,
        }

    # Leaf value — just report type (never content)
    return _type_label(obj)


def _merge_schemas(base: Any, incoming: Any) -> Any:
    """Merge *incoming* schema tree into *base* so that the result is the
    union of all keys ever seen.  For leaves it keeps the latest type label.
    """
    if isinstance(base, dict) and isinstance(incoming, dict):
        merged = OrderedDict(base)
        for key, val in incoming.items():
            if key in merged:
                merged[key] = _merge_schemas(merged[key], val)
            else:
                merged[key] = val
        return merged
    # For non-dict nodes just take the incoming value
    return incoming


def _pretty_tree(schema: Any, *, indent: int = 0) -> str:
    """Render a schema tree as an indented, readable string."""
    pad = "  " * indent
    lines: list[str] = []

    if isinstance(schema, dict):
        for key, val in schema.items():
            if isinstance(val, dict):
                lines.append(f"{pad}{key}:")
                lines.append(_pretty_tree(val, indent=indent + 1))
            else:
                lines.append(f"{pad}{key}: {val}")
    else:
        lines.append(f"{pad}{schema}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Pipeline step
# ---------------------------------------------------------------------------

class DocumentStructureInspector(PipelineStep):
    """Inspect and log the structure of documents in a datatrove pipeline.

    Parameters
    ----------
    output_folder : str | None
        Directory to write the report file(s) into.  If ``None`` (default),
        output goes to the terminal (stdout).  When set, a ``.txt`` file is
        written inside that folder.
    output_filename : str | None
        Template for the output file name.  Supports ``${rank}`` and
        ``${timestamp}`` placeholders.  If ``None`` (default), a
        timestamped name is generated automatically.
        Example: ``"inspector_${rank}.txt"``
    max_docs : int
        Inspect at most this many documents (schema is accumulated).
        After *max_docs* the step still yields every remaining document
        but stops inspecting.  ``0`` means inspect ALL documents.
    log_per_doc : bool
        If ``True``, write the schema of every inspected document.
        If ``False`` (default), only write a merged summary after all
        inspected documents have been seen.
    """

    name: str = "🔍 DocumentStructureInspector"
    type: str = "🔍 - INSPECT"

    def __init__(
        self,
        output_folder: str | None = None,
        output_filename: str | None = None,
        max_docs: int = 0,
        log_per_doc: bool = False,
    ):
        super().__init__()
        self.output_folder = output_folder
        self.output_filename = output_filename
        self.max_docs = max_docs
        self.log_per_doc = log_per_doc

        # Accumulated state (reset on each run call)
        self._merged_schema: Any = None
        self._docs_inspected: int = 0
        self._all_metadata_keys: dict[str, int] = {}
        self._all_media_keys: dict[str, int] = {}
        self._output_lines: list[str] = []

    # -----------------------------------------------------------------
    # Internal
    # -----------------------------------------------------------------

    def _inspect_document(self, document: Document) -> dict:
        """Build the full structure dict for one document."""
        structure: OrderedDict[str, Any] = OrderedDict()

        # --- top-level dataclass fields ---
        structure["id"] = _type_label(document.id)
        structure["text"] = _type_label(document.text)

        # --- media ---
        if document.media:
            media_schemas = []
            for idx, media_item in enumerate(document.media):
                if isinstance(media_item, dict):
                    ms = _build_schema(media_item)
                    # Track media-level keys
                    for k in media_item.keys():
                        self._all_media_keys[k] = self._all_media_keys.get(k, 0) + 1
                elif isinstance(media_item, Media):
                    ms = OrderedDict()
                    ms["type"] = _type_label(media_item.type)
                    ms["url"] = _type_label(media_item.url)
                    ms["alt"] = _type_label(media_item.alt)
                    ms["local_path"] = _type_label(media_item.local_path)
                else:
                    ms = _type_label(media_item)
                media_schemas.append(ms)

            structure["media"] = {
                "__list_length__": len(document.media),
                "__item_schema__": media_schemas[0] if len(media_schemas) == 1 else media_schemas,
            }
        else:
            structure["media"] = "list(empty)"

        # --- metadata ---
        if document.metadata:
            structure["metadata"] = _build_schema(document.metadata)
            for k in document.metadata.keys():
                self._all_metadata_keys[k] = self._all_metadata_keys.get(k, 0) + 1
        else:
            structure["metadata"] = "dict(keys=0)"

        return structure

    def _format_report(self, schema: Any, doc_count: int, *, is_summary: bool = False) -> str:
        """Format a pretty report string."""
        sep = "=" * 70
        header = "DOCUMENT STRUCTURE SUMMARY" if is_summary else "DOCUMENT STRUCTURE"
        lines = [
            "",
            sep,
            f"  {header}  (inspected {doc_count} document{'s' if doc_count != 1 else ''})",
            sep,
            "",
            _pretty_tree(schema),
            "",
        ]

        if is_summary and self._all_metadata_keys:
            lines.append(f"  metadata keys seen (key: count/{doc_count} docs):")
            for key in sorted(self._all_metadata_keys):
                count = self._all_metadata_keys[key]
                pct = count / doc_count * 100 if doc_count else 0
                marker = "✅" if count == doc_count else "⚠️"
                lines.append(f"    {marker} {key}: {count}/{doc_count} ({pct:.0f}%)")
            lines.append("")

        if is_summary and self._all_media_keys:
            lines.append(f"  media[0] keys seen (key: count/{doc_count} docs):")
            for key in sorted(self._all_media_keys):
                count = self._all_media_keys[key]
                pct = count / doc_count * 100 if doc_count else 0
                marker = "✅" if count == doc_count else "⚠️"
                lines.append(f"    {marker} {key}: {count}/{doc_count} ({pct:.0f}%)")
            lines.append("")

        lines.append(sep)
        return "\n".join(lines)

    # -----------------------------------------------------------------
    # Output helpers
    # -----------------------------------------------------------------

    def _emit(self, text: str):
        """Buffer text for file output, or print immediately to terminal."""
        if self.output_folder is not None:
            self._output_lines.append(text)
        else:
            print(text)

    def _flush_to_file(self, rank: int):
        """Write all buffered output to a file inside *output_folder*."""
        if self.output_folder is None or not self._output_lines:
            return
        os.makedirs(self.output_folder, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        if self.output_filename:
            # Support ${rank} and ${timestamp} placeholders
            filename = (
                self.output_filename
                .replace("${rank}", str(rank))
                .replace("${timestamp}", timestamp)
            )
        else:
            filename = f"document_structure_rank{rank}_{timestamp}.txt"
        filepath = os.path.join(self.output_folder, filename)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write("\n".join(self._output_lines))
            f.write("\n")
        print(f"[DocumentStructureInspector] Report written to: {filepath}")

    # -----------------------------------------------------------------
    # Pipeline interface
    # -----------------------------------------------------------------

    def run(self, data: DocumentsPipeline, rank: int = 0, world_size: int = 1) -> DocumentsPipeline:
        """Yield every document unchanged while inspecting up to *max_docs*."""
        # Reset state for this run
        self._merged_schema = None
        self._docs_inspected = 0
        self._all_metadata_keys = {}
        self._all_media_keys = {}
        self._output_lines = []

        for document in data:
            should_inspect = (self.max_docs == 0) or (self._docs_inspected < self.max_docs)

            if should_inspect:
                schema = self._inspect_document(document)
                self._docs_inspected += 1

                if self._merged_schema is None:
                    self._merged_schema = schema
                else:
                    self._merged_schema = _merge_schemas(self._merged_schema, schema)

                if self.log_per_doc:
                    report = self._format_report(schema, self._docs_inspected, is_summary=False)
                    self._emit(report)

                self.stat_update("inspected")

            self.stat_update("forwarded")
            yield document

        # Write final summary
        if self._merged_schema is not None:
            report = self._format_report(
                self._merged_schema,
                self._docs_inspected,
                is_summary=True,
            )
            self._emit(report)

        if self._docs_inspected == 0:
            self._emit("[DocumentStructureInspector] No documents received.")

        # Flush to file if output_folder is set
        self._flush_to_file(rank)
