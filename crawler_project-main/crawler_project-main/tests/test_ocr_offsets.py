"""Exercise OCR page assembly and the real downstream page filter offline."""

from dataclasses import dataclass
import importlib.util
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace

import pytest


@pytest.fixture
def ocr_pipeline(monkeypatch):
    """Replace inference/storage plumbing, keeping the processing code real.

    These tests need neither Datatrove's inference server nor PDF models. Stubs
    are scoped to this fixture so other test modules keep their own imports.
    """
    extraction_root = Path(__file__).resolve().parents[1] / "datatrove_extraction"

    @dataclass
    class InferenceResult:
        text: str
        finish_reason: str = "stop"

    class PipelineStep:
        def stat_update(self, *args, **kwargs):
            pass

    rejected = []

    class JsonlWriter:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def write(self, document, **kwargs):
            rejected.append(document)

    def stub_module(name, **attributes):
        module = ModuleType(name)
        module.__dict__.update(attributes)
        monkeypatch.setitem(sys.modules, name, module)
        return module

    stub_module("datatrove", __path__=[])
    stub_module("datatrove.data", Document=object, DocumentsPipeline=list, MediaType=object)
    stub_module("datatrove.pipeline", __path__=[])
    stub_module("datatrove.pipeline.base", PipelineStep=PipelineStep)
    stub_module("datatrove.pipeline.inference", __path__=[])
    stub_module(
        "datatrove.pipeline.inference.run_inference",
        InferenceRunner=object,
        InferenceResult=InferenceResult,
    )
    stub_module("datatrove.pipeline.writers", __path__=[])
    stub_module("datatrove.pipeline.writers.jsonl", JsonlWriter=JsonlWriter)
    stub_module("datatrove.utils", __path__=[])
    stub_module("datatrove.utils.typeshelper", StatHints=SimpleNamespace(dropped="dropped", forwarded="forwarded"))
    stub_module("pymupdf")
    stub_module("helpers", __path__=[])
    stub_module("helpers.main_helpers", __path__=[])
    stub_module("_ocr_regression_pipeline", __path__=[])

    def load_module(name, relative_path):
        spec = importlib.util.spec_from_file_location(name, extraction_root / relative_path)
        module = importlib.util.module_from_spec(spec)
        monkeypatch.setitem(sys.modules, name, module)
        spec.loader.exec_module(module)
        return module

    page_reader = load_module("helpers.main_helpers.utils", "helpers/main_helpers/utils.py")
    extraction = load_module("_ocr_regression_pipeline.extract_utils", "helpers/pipeline_utils/extract_utils.py")
    filtering = load_module("_ocr_regression_pipeline.postprocess_utils", "helpers/pipeline_utils/postprocess_utils.py")
    return SimpleNamespace(
        extract=extraction.postprocess_extract,
        filter=filtering.CoallesceFailedPages("unused-offline-output"),
        iter_pages=page_reader.iter_pages,
        result=InferenceResult,
        rejected=rejected,
    )


def make_document(results, num_pages=None):
    return SimpleNamespace(
        text="",
        metadata={"inference_results": results, "num_pages": len(results) if num_pages is None else num_pages},
        media=[{"metadata": {"content_bytes": "unused"}}],
    )


@pytest.mark.parametrize(
    "pages",
    [
        ["AAAA", "BBBB", "CCCC"],
        ["صفحة أولى", "دارجة مغربية", "نهاية النص"],
        ["single page ending"],
        ["", "middle", "last"],
        ["first", "", "last"],
        ["first", "last", ""],
        ["line one\nline two", "last character Ω"],
    ],
)
def test_pages_survive_assembly_and_downstream_filter(ocr_pipeline, pages):
    document = make_document([ocr_pipeline.result(page) for page in pages])

    assert ocr_pipeline.extract(document) is document
    assert document.text == "\n".join(pages)
    assert document.media[0]["metadata"]["page_offsets"][-1] == len(document.text)
    assert [page.strip() for page in ocr_pipeline.iter_pages(document)] == pages
    assert "inference_results" not in document.metadata

    filtered = list(ocr_pipeline.filter.run([document]))

    assert filtered == [document]
    assert document.text == "".join(page + "\n" for page in pages)
    assert document.media[0]["metadata"]["page_offsets"][-1] == len(document.text)
    assert not ocr_pipeline.rejected


def test_missing_page_is_marked_without_truncating_following_pages(ocr_pipeline):
    document = make_document([ocr_pipeline.result("first"), None, ocr_pipeline.result("last Ω")])

    ocr_pipeline.extract(document)
    assert [page.strip() for page in ocr_pipeline.iter_pages(document)] == [
        "first", "<--- failed_to_process_page --->", "last Ω"
    ]

    assert list(ocr_pipeline.filter.run([document])) == [document]
    assert document.text == "first\n<failed_page></failed_page>\nlast Ω\n"


def test_unreturned_last_page_keeps_the_placeholder(ocr_pipeline):
    document = make_document([ocr_pipeline.result("first"), ocr_pipeline.result("second")], num_pages=3)

    ocr_pipeline.extract(document)

    assert [page.strip() for page in ocr_pipeline.iter_pages(document)] == [
        "first", "second", "<--- failed_to_process_page --->"
    ]
    assert list(ocr_pipeline.filter.run([document])) == [document]
    assert document.text == "first\nsecond\n<failed_page></failed_page>\n"


def test_failed_generation_keeps_later_page_intact(ocr_pipeline):
    document = make_document([
        ocr_pipeline.result("first"),
        ocr_pipeline.result("partial response", finish_reason="length"),
        ocr_pipeline.result("last complete page"),
    ])

    ocr_pipeline.extract(document)
    assert list(ocr_pipeline.filter.run([document])) == [document]
    assert document.text == "first\n<failed_page></failed_page>\nlast complete page\n"


def test_all_failed_pages_are_rejected(ocr_pipeline):
    document = make_document([None, ocr_pipeline.result("partial", finish_reason="length")])

    ocr_pipeline.extract(document)

    assert list(ocr_pipeline.filter.run([document])) == []
    assert ocr_pipeline.rejected == [document]


def test_no_results_returns_no_document(ocr_pipeline):
    document = make_document([], num_pages=3)

    assert ocr_pipeline.extract(document) is None
