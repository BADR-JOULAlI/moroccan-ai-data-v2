#
# Copyright IBM Corp. 2024 - 2024
# SPDX-License-Identifier: MIT
#

"""Define the chunker types."""

from helpers.docling_code.docling_core.transforms.chunker.base import BaseChunk, BaseChunker, BaseMeta
from helpers.docling_code.docling_core.transforms.chunker.hierarchical_chunker import (
    DocChunk,
    DocMeta,
    HierarchicalChunker,
)
