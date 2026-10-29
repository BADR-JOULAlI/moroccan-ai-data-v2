"""Read small local WARC archives with the production segment reader."""

import base64
from importlib.machinery import ModuleSpec
from io import BytesIO
from pathlib import Path
import sys
from types import ModuleType

import pytest
from warcio.statusandheaders import StatusAndHeaders
from warcio.warcwriter import WARCWriter


@pytest.fixture
def segment_reader(monkeypatch):
    extraction_root = Path(__file__).resolve().parents[1] / "datatrove_extraction"
    monkeypatch.syspath_prepend(str(extraction_root))
    # The fixture declares its MIME type in the WARC headers. libmagic is not
    # needed for these records, and its native library is not bundled on Windows.
    try:
        import magic  # noqa: F401
    except ImportError:
        header_only_magic = ModuleType("magic")
        header_only_magic.__spec__ = ModuleSpec("magic", loader=None)

        def unexpected_sniff(*args, **kwargs):
            raise AssertionError("Fixture records must declare their MIME type")

        header_only_magic.from_buffer = unexpected_sniff
        monkeypatch.setitem(sys.modules, "magic", header_only_magic)
    from helpers.readers.WarcGeneralReader import build_segment_reader

    return build_segment_reader


def write_archive(path, count, prefix="page"):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as stream:
        writer = WARCWriter(stream, gzip=True)
        for index in range(count):
            payload = f"<html><body>{prefix}-{index}</body></html>".encode()
            record = writer.create_warc_record(
                f"https://example.ma/{prefix}/{index}",
                "response",
                payload=BytesIO(payload),
                http_headers=StatusAndHeaders(
                    "200 OK", [("Content-Type", "text/html")], protocol="HTTP/1.1"
                ),
                warc_headers_dict={"WARC-Identified-Payload-Type": "text/html"},
            )
            writer.write_record(record)


def test_complete_segment_keeps_records_beyond_fifteen(tmp_path, segment_reader):
    write_archive(tmp_path / "site" / "pages.warc.gz", 24)

    documents = list(segment_reader(str(tmp_path), "test-segment")())

    assert len(documents) == 24
    assert {doc.media[0]["url"] for doc in documents} == {
        f"https://example.ma/page/{index}" for index in range(24)
    }
    assert all(doc.metadata["segment"] == "test-segment" for doc in documents)
    assert base64.b64decode(documents[-1].media[0]["metadata"]["content_bytes"]) == (
        b"<html><body>page-23</body></html>"
    )


def test_sharded_segment_does_not_truncate_each_worker(tmp_path, segment_reader):
    write_archive(tmp_path / "first" / "pages.warc.gz", 20, "first")
    write_archive(tmp_path / "second" / "pages.warc.gz", 20, "second")

    shards = [
        list(segment_reader(str(tmp_path), "test-segment")(rank=rank, world_size=2))
        for rank in range(2)
    ]
    urls = [doc.media[0]["url"] for shard in shards for doc in shard]

    assert [len(shard) for shard in shards] == [20, 20]
    assert len(urls) == len(set(urls)) == 40
