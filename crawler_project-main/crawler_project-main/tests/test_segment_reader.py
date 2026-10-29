"""Read small local WARC archives with the production segment reader."""

import base64
import builtins
from io import BytesIO
from pathlib import Path

import pytest
from warcio.statusandheaders import StatusAndHeaders
from warcio.warcwriter import WARCWriter
from warcio.archiveiterator import ArchiveIterator


@pytest.fixture
def segment_reader(monkeypatch):
    extraction_root = Path(__file__).resolve().parents[1] / "datatrove_extraction"
    monkeypatch.syspath_prepend(str(extraction_root))
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


def test_gzip_byte_ranges_replay_each_original_record(tmp_path, segment_reader):
    archive = tmp_path / "site" / "pages.warc.gz"
    write_archive(archive, 3)

    documents = list(segment_reader(str(tmp_path), "test-segment")())

    offsets = [document.media[0]["offset"] for document in documents]
    lengths = [document.media[0]["length"] for document in documents]
    assert offsets[0] == 0
    assert offsets == sorted(set(offsets))
    assert all(length > 0 for length in lengths)
    assert offsets[-1] + lengths[-1] == archive.stat().st_size
    with archive.open("rb") as stream:
        for document in documents:
            media = document.media[0]
            stream.seek(media["offset"])
            compressed_record = stream.read(media["length"])
            records = list(ArchiveIterator(BytesIO(compressed_record)))
            # Reading the iterator consumes the payload; replay it independently.
            assert len(records) == 1
            replay = next(ArchiveIterator(BytesIO(compressed_record)))
            assert replay.rec_headers.get_header("WARC-Target-URI") == media["url"]
            assert replay.content_stream().read() == base64.b64decode(media["metadata"]["content_bytes"])


@pytest.mark.parametrize("content_type, payload", [
    ("Text/HTML; charset=utf-8", b"<html><body>A page.</body></html>"),
    ("application/pdf", b"%PDF-1.7\nfixture"),
])
def test_http_payload_mime_works_without_native_sniffers(tmp_path, segment_reader, monkeypatch, content_type, payload):
    archive = tmp_path / "site" / "pages.warc.gz"
    archive.parent.mkdir()
    with archive.open("wb") as stream:
        writer = WARCWriter(stream, gzip=True)
        record = writer.create_warc_record(
            "https://example.ma/content", "response", payload=BytesIO(payload),
            http_headers=StatusAndHeaders("200 OK", [("Content-Type", content_type)], protocol="HTTP/1.1"),
        )
        writer.write_record(record)
    original_import = builtins.__import__

    def no_native_sniffer(name, *args, **kwargs):
        if name in {"magic", "cchardet"}:
            pytest.fail("An explicit payload Content-Type must not require native sniffers")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_native_sniffer)
    document, = list(segment_reader(str(tmp_path), "test-segment")())

    metadata = document.media[0]["metadata"]
    expected = content_type.split(";", 1)[0].lower()
    assert metadata["content_mime_type"] == expected
    assert metadata["content_mime_detected"] == expected
    assert base64.b64decode(metadata["content_bytes"]) == payload


def test_warc_identified_payload_type_takes_precedence(tmp_path, segment_reader):
    archive = tmp_path / "site" / "pages.warc.gz"
    archive.parent.mkdir()
    with archive.open("wb") as stream:
        writer = WARCWriter(stream, gzip=True)
        record = writer.create_warc_record(
            "https://example.ma/content", "response", payload=BytesIO(b"%PDF-1.7\nfixture"),
            http_headers=StatusAndHeaders("200 OK", [("Content-Type", "application/octet-stream")], protocol="HTTP/1.1"),
            warc_headers_dict={"WARC-Identified-Payload-Type": "application/pdf"},
        )
        writer.write_record(record)

    document, = list(segment_reader(str(tmp_path), "test-segment")())

    assert document.media[0]["metadata"]["content_mime_type"] == "application/octet-stream"
    assert document.media[0]["metadata"]["content_mime_detected"] == "application/pdf"


def test_ambiguous_payload_stays_unknown_if_libmagic_is_missing(tmp_path, segment_reader, monkeypatch):
    archive = tmp_path / "site" / "pages.warc.gz"
    archive.parent.mkdir()
    with archive.open("wb") as stream:
        writer = WARCWriter(stream, gzip=True)
        record = writer.create_warc_record(
            "https://example.ma/content", "response", payload=BytesIO(b"arbitrary payload"),
            http_headers=StatusAndHeaders("200 OK", [("Content-Type", "application/octet-stream")], protocol="HTTP/1.1"),
        )
        writer.write_record(record)
    original_import = builtins.__import__

    def missing_libmagic(name, *args, **kwargs):
        if name == "magic":
            raise ImportError("No native libmagic installed")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", missing_libmagic)
    document, = list(segment_reader(str(tmp_path), "test-segment")())

    assert document.media[0]["metadata"]["content_mime_detected"] is None
    assert document.media[0]["metadata"]["content_mime_type"] == "application/octet-stream"


def test_unsupported_compression_cannot_claim_physical_offsets(tmp_path, segment_reader):
    from helpers.readers.WarcGeneralReader import WarcGeneralReader

    with pytest.raises(ValueError, match="preserve physical archive offsets"):
        WarcGeneralReader(str(tmp_path), compression="zstd")
