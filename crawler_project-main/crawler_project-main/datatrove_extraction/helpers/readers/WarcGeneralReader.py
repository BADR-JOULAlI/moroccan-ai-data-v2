from typing import TYPE_CHECKING, Callable, Literal

from datatrove.io import DataFileLike, DataFolderLike
from datatrove.pipeline.readers.base import BaseDiskReader


if TYPE_CHECKING:
    from warcio.recordloader import ArcWarcRecord

class WarcGeneralReader(BaseDiskReader):
    """Read data from WARC files.
        Will read each record as a separate document.

    Args:
        data_folder: a str, tuple or DataFolder object representing a path/filesystem
        paths_file: optionally provide a file with one path per line (without the `data_folder` prefix) to read.
        compression: None, "infer" or "gzip"; Warcio detects raw/gzip records.
            Other codecs cannot provide physical archive offsets for replay.
        limit: limit the number of documents to read. Useful for debugging
        skip: skip the first n rows
        file_progress: show progress bar for files
        doc_progress: show progress bar for documents
        adapter: function to adapt the data dict from the source to a Document.
            Takes as input: (self, data: dict, path: str, id_in_file: int | str)
                self allows access to self.text_key and self.id_key
            Returns: a dict with at least a "text" and "id" keys
        text_key: the key containing the text data (default: "text").
        id_key: the key containing the id for each sample (default: "id").
        default_metadata: a dictionary with any data that should be added to all samples' metadata
        recursive: whether to search files recursively. Ignored if paths_file is provided
        glob_pattern: pattern that all files must match exactly to be included (relative to data_folder). Ignored if paths_file is provided
        shuffle_files: shuffle the files within the returned shard. Mostly used for data viz. purposes, do not use with dedup blocks
    """

    name = "🕷 Warc"
    _requires_dependencies = ["warcio"]

    def __init__(
        self,
        data_folder: DataFolderLike,
        paths_file: DataFileLike | None = None,
        compression: Literal["infer", "gzip"] | None = "infer",
        limit: int = -1,
        skip: int = 0,
        file_progress: bool = False,
        doc_progress: bool = False,
        adapter: Callable = None,
        text_key: str = "text",
        id_key: str = "id",
        default_metadata: dict = None,
        recursive: bool = True,
        glob_pattern: str | None = None,
        shuffle_files: bool = False,
    ):
        if compression not in {None, "infer", "gzip"}:
            raise ValueError("WARC compression must be None, 'infer' or 'gzip' to preserve physical archive offsets")
        self.compression = compression
        super().__init__(
            data_folder,
            paths_file,
            limit,
            skip,
            file_progress,
            doc_progress,
            adapter,
            text_key,
            id_key,
            default_metadata,
            recursive,
            glob_pattern,
            shuffle_files,
        )

    def read_file(self, filepath: str):
        from warcio.archiveiterator import ArchiveIterator

        # Warcio must see the original gzip members. Decompressing in fsspec
        # would turn offsets into positions in a virtual, uncompressed stream.
        with self.data_folder.open(filepath, "rb", compression=None) as f:
            archive_iterator = ArchiveIterator(f)
            for ri, record in enumerate(archive_iterator):
                offset = archive_iterator.offset
                with self.track_time():
                    name = filepath
                    extracted_data = process_record(record, offset, name)
                    # These accessors finish the current member and report its
                    # actual archive byte range, not its HTTP Content-Length.
                    offset = archive_iterator.get_record_offset()
                    length = archive_iterator.get_record_length()
                    if not extracted_data:
                        continue
                    extracted_data["media"][0].update(offset=offset, length=length)
                    document = self.get_document_from_dict(extracted_data, filepath, ri)
                    if not document:
                        continue
                yield document


def build_segment_reader(data_folder: DataFolderLike, segment: str) -> WarcGeneralReader:
    """Read the complete segment; sampling limits must not truncate a dataset run."""
    return WarcGeneralReader(
        data_folder=data_folder,
        glob_pattern="*/*.warc.gz",
        default_metadata={"segment": segment},
    )


def process_record(record: "ArcWarcRecord", offset: int, name: str) -> dict | None:
    """Process a WARC record to extract metadata for indexing.

    Args:
        record: The WARC record to process
        offset: The byte offset of the record in the WARC file
        name: The name/path of the WARC file
        
    Returns:
        A dictionary containing extracted metadata, or None if the record should be skipped.
        The returned dict includes:
        - text: Empty string (no content extracted for indexing)
        - id: WARC record ID
        - url: Target URI
        - fetch_status: HTTP status line
        - fetch_time: Date of the record
        - content_mime_type: Original MIME type from headers
        - content_mime_detected: Detected MIME type
        - content_truncated: Whether content was truncated (if >= 1MB)
        - warc_record_offset: Byte offset in the WARC file
        - warc_filename: Name of the WARC file
        - content_digest: Content digest hash if available
    """
    import base64
    # record type
    record_type = record.rec_type
    if record_type not in ["response", "conversion", "resource"]:  # wet files have "conversion" type
        return

    # content type filtering
    content_bytes = record.content_stream().read()
    
    # The WARC response envelope is application/http; the payload type belongs
    # to its HTTP headers. Keep explicit types usable without a native sniffer.
    http_content_type = record.http_headers.get_header("Content-Type") if record.http_headers else None
    original_mime_type = (http_content_type or record.content_type or "").split(";", 1)[0].strip().lower()
    detected_mime_type = record.rec_headers.get("WARC-Identified-Payload-Type")
    if detected_mime_type:
        detected_mime_type = detected_mime_type.split(";", 1)[0].strip().lower()
    elif original_mime_type not in {"", "application/http", "application/octet-stream", "binary/octet-stream"}:
        detected_mime_type = original_mime_type
    else:
        # libmagic is optional for records without a usable MIME header. If its
        # native library is unavailable, leave detection unknown rather than
        # treating arbitrary bytes as HTML.
        try:
            import magic

            detected_mime_type = magic.from_buffer(content_bytes, mime=True)
        except (ImportError, OSError):
            detected_mime_type = None

    id_ = record.rec_headers["WARC-Record-ID"]
    url = record.rec_headers.get("WARC-Target-URI", None)
    date = record.rec_headers.get("WARC-Date", None)
    if not url:
        url = dict(record.rec_headers.headers)["uri"]
    if not date:
        date = dict(record.rec_headers.headers)["archive-date"]

    # WARC headers normally contain strings; retain timestamp-like adapters
    # without importing pandas (and its native extensions) just to read WARC.
    if callable(getattr(date, "to_pydatetime", None)):
        date = date.to_pydatetime()

    ret = {
        "text": "<no content>",
        "id": id_,
        "url": url,
        "date": date,
        "metadata": {
            "index_file": name,
        },
        "media": [{
            "id": id_,
            "url": url,
            "type": 3, # 3 is the type for documents
            "path": name,
            "offset": offset,
            "length": record.length,
            "record_type": record_type,
            "metadata": {
                "fetch_time": date,
                "fetch_status": record.http_headers.statusline if record.http_headers else "",
                "content_mime_type": original_mime_type,
                "content_mime_detected": detected_mime_type,
                "content_languages": None,
                #"content_truncated": truncated,
                "content_digest": record.rec_headers.get("WARC-Payload-Digest", None),
                "content_bytes": base64.b64encode(content_bytes).decode("utf-8"), # to decode base64.b64decode(doc["media"][0]["metadata"]["content_bytes"])
            }
        }],
    }
    return ret
