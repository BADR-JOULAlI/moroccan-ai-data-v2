"""HTML text extraction with a portable deadline and explicit rejected records."""

import contextlib
from functools import partial

from datatrove.pipeline.base import PipelineStep
from datatrove.utils.typeshelper import StatHints

from helpers.predictors.media_sandbox import MediaExtractionSandbox, MediaWorkerCleanupError


def _extract_html(content: bytes, metadata: dict, *, favour_precision: bool) -> tuple[str, dict]:
    from trafilatura import extract

    text = extract(
        content.decode("utf-8"), favor_precision=favour_precision,
        include_comments=False, deduplicate=True,
    )
    return text or "", {}


class HtmlTextExtractor(PipelineStep):
    name = "HTML text extraction"
    type = "EXTRACTOR"
    _requires_dependencies = ["trafilatura"]

    def __init__(self, favour_precision=True, timeout=30, exclusion_writer=None):
        super().__init__()
        self.favour_precision = favour_precision
        self.timeout = timeout
        self.exclusion_writer = exclusion_writer

    def run(self, data, rank=0, world_size=1):
        extract_fn = partial(_extract_html, favour_precision=self.favour_precision)
        with (
            MediaExtractionSandbox(self.timeout, extract_fn) as sandbox,
            self.exclusion_writer if self.exclusion_writer else contextlib.nullcontext() as rejected,
        ):
            for document in data:
                self.stat_update(StatHints.total)
                try:
                    text, _ = sandbox.process(document.text.encode("utf-8"), {})
                    error = "empty_text" if not text.strip() else ""
                except TimeoutError:
                    text, error = "", "timeout"
                except MediaWorkerCleanupError:
                    raise
                except Exception as exc:
                    text, error = "", f"extraction_error: {exc}"
                if error:
                    document.metadata["html_extraction_error"] = error
                    self.stat_update(StatHints.dropped)
                    if rejected is not None:
                        rejected.write(document, rank=rank, world_size=world_size)
                    continue
                document.text = text
                self.stat_update(StatHints.forwarded)
                self.update_doc_stats(document)
                yield document
