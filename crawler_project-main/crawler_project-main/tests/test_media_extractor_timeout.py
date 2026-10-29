"""Real spawn workers enforce deadlines and do not leak across media failures."""

import base64
import multiprocessing
import os
from pathlib import Path
import sys
import time

import pytest


EXTRACTION_ROOT = Path(__file__).resolve().parents[1] / "datatrove_extraction"
sys.path.insert(0, str(EXTRACTION_ROOT))

from datatrove.data import Document
from helpers.predictors.base_extractor import BaseMediaExtractor
from helpers.predictors.media_sandbox import MediaExtractionError, MediaExtractionSandbox, MediaWorkerCleanupError


class StatefulExtractor:
    def __init__(self):
        self.calls = 0

    def __call__(self, media_bytes, metadata):
        self.calls += 1
        if media_bytes == b"slow":
            time.sleep(10)
        if media_bytes == b"crash":
            os._exit(17)
        if media_bytes == b"error":
            raise ValueError("invalid fixture media")
        return media_bytes.decode(), {"worker_pid": os.getpid(), "worker_calls": self.calls}


class FixtureMediaExtractor(BaseMediaExtractor):
    name = "Fixture media extractor"

    def __init__(self, timeout=2, **kwargs):
        self.callback = StatefulExtractor()
        super().__init__(timeout=timeout, **kwargs)

    def extract(self, media_bytes, document_metadata):
        return self.callback(media_bytes, document_metadata)


class ParentWriter:
    def __init__(self):
        self.records = []
        self.entered = False
        self.closed = False

    def __enter__(self):
        self.entered = True
        return self

    def __exit__(self, *args):
        self.closed = True

    def write(self, document, **kwargs):
        self.records.append(document)


def document(identifier, payload):
    return Document(id=identifier, text="original", media=[{
        "id": identifier, "url": "https://example.test/fixture.pdf", "type": 3,
        "metadata": {"content_bytes": base64.b64encode(payload).decode()},
    }])


def active_pids():
    return {process.pid for process in multiprocessing.active_children()}


def test_worker_is_reused_without_running_callback_in_parent():
    callback = StatefulExtractor()
    before = active_pids()
    with MediaExtractionSandbox(2, callback) as sandbox:
        first = sandbox.process(b"first", {})
        second = sandbox.process(b"second", {})
        assert first[0] == "first"
        assert second[0] == "second"
        assert first[1]["worker_pid"] == second[1]["worker_pid"] != os.getpid()
        assert second[1]["worker_calls"] == 2
    assert callback.calls == 0
    assert active_pids() == before


def test_timeout_kills_owned_worker_and_next_request_restarts():
    before = active_pids()
    with MediaExtractionSandbox(1.5, StatefulExtractor()) as sandbox:
        # Start first, so the timing assertion measures the extraction deadline.
        old_pid = sandbox.process(b"first", {})[1]["worker_pid"]
        started = time.monotonic()
        with pytest.raises(TimeoutError, match="timed out"):
            sandbox.process(b"slow", {})
        assert time.monotonic() - started < 4
        assert old_pid not in active_pids()
        text, metadata = sandbox.process(b"recovered", {})
        assert text == "recovered"
        assert metadata["worker_pid"] != old_pid
        assert metadata["worker_calls"] == 1
    assert active_pids() == before


def test_worker_crash_is_distinct_from_timeout_and_can_recover():
    before = active_pids()
    with MediaExtractionSandbox(2, StatefulExtractor()) as sandbox:
        with pytest.raises((EOFError, BrokenPipeError)):
            sandbox.process(b"crash", {})
        assert sandbox.process(b"after crash", {})[0] == "after crash"
    assert active_pids() == before


def test_callback_error_is_reported_and_worker_stays_usable():
    before = active_pids()
    with MediaExtractionSandbox(2, StatefulExtractor()) as sandbox:
        with pytest.raises(MediaExtractionError, match="ValueError: invalid fixture media"):
            sandbox.process(b"error", {})
        assert sandbox.process(b"after error", {})[1]["worker_calls"] == 2
    assert active_pids() == before


def test_pipeline_drops_timed_out_media_and_writes_failure_in_parent():
    before = active_pids()
    writer = ParentWriter()
    extractor = FixtureMediaExtractor(timeout=1.5, exclusion_writer=writer)
    failed = document("slow", b"slow")
    good = document("good", b"good")

    forwarded = list(extractor.run([failed, good]))

    assert forwarded == [good]
    assert failed.media[0]["metadata"]["extraction_failed"] == "timeout"
    assert writer.records == [failed]
    assert writer.entered and writer.closed
    assert good.text == "good"
    assert good.media[0]["metadata"]["worker_pid"] != os.getpid()
    assert extractor.callback.calls == 0
    assert active_pids() == before


def test_pipeline_can_retry_a_previously_failed_document():
    recovered = document("retry", b"successful")
    recovered.media[0]["metadata"]["extraction_failed"] = "old failure"

    assert list(FixtureMediaExtractor().run([recovered])) == [recovered]
    assert "extraction_failed" not in recovered.media[0]["metadata"]


@pytest.mark.parametrize("timeout", [0, -1, float("nan"), float("inf")])
def test_invalid_timeout_is_rejected_without_starting_worker(timeout):
    with pytest.raises(ValueError, match="positive finite"):
        MediaExtractionSandbox(timeout, StatefulExtractor())


def test_unserializable_extractor_is_a_clear_configuration_error():
    class BrokenExtractor:
        def __getstate__(self):
            raise ValueError("fixture cannot be serialized")

        def __call__(self, media_bytes, metadata):
            return "", {}

    with pytest.raises(MediaExtractionError, match="Cannot serialize extraction callable"):
        MediaExtractionSandbox(2, BrokenExtractor())


def test_unstoppable_worker_remains_owned_and_cannot_be_replaced(monkeypatch):
    class UnstoppableWorker:
        pid = 12345
        alive = True
        closed = False

        def is_alive(self):
            return self.alive

        def terminate(self):
            pass

        def join(self, timeout):
            pass

        def kill(self):
            pass

        def close(self):
            self.closed = True

    class Connection:
        def close(self):
            pass

    sandbox = MediaExtractionSandbox(1, StatefulExtractor())
    worker = UnstoppableWorker()
    sandbox._process = worker
    sandbox._connection = Connection()
    monkeypatch.setattr(sandbox._context, "Process", lambda *args, **kwargs: pytest.fail("Must not start a replacement worker"))

    with pytest.raises(MediaWorkerCleanupError, match="Unable to stop extraction worker"):
        sandbox._stop_worker()
    assert sandbox._process is worker
    assert not worker.closed
    with pytest.raises(MediaWorkerCleanupError, match="sandbox cannot continue"):
        sandbox.process(b"do not run", {})
    assert sandbox._process is worker

    # Cleanup can still be retried if the worker eventually terminates.
    worker.alive = False
    sandbox._stop_worker()
    assert worker.closed
    assert sandbox._process is None


def test_channel_cleanup_failure_is_fatal_but_still_stops_the_worker():
    class Worker:
        pid = 12346
        alive = True
        closed = False

        def is_alive(self):
            return self.alive

        def terminate(self):
            self.alive = False

        def join(self, timeout):
            pass

        def close(self):
            self.closed = True

    class Connection:
        fail = True

        def close(self):
            if self.fail:
                raise OSError("fixture close failure")

    sandbox = MediaExtractionSandbox(1, StatefulExtractor())
    worker, connection = Worker(), Connection()
    sandbox._process, sandbox._connection = worker, connection

    with pytest.raises(MediaWorkerCleanupError, match="communication channel"):
        sandbox._stop_worker()
    assert not worker.alive
    assert worker.closed
    assert sandbox._process is None
    assert sandbox._connection is connection
    with pytest.raises(MediaWorkerCleanupError, match="sandbox cannot continue"):
        sandbox.process(b"do not run", {})

    connection.fail = False
    sandbox._stop_worker()
    assert sandbox._connection is None


class FatalCleanupSandbox:
    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def process(self, *args, **kwargs):
        raise MediaWorkerCleanupError("fixture worker could not be stopped")


def test_media_pipeline_does_not_convert_fatal_cleanup_to_a_rejection(monkeypatch):
    from helpers.predictors import base_extractor

    writer = ParentWriter()
    media = document("fatal", b"payload")
    monkeypatch.setattr(base_extractor, "MediaExtractionSandbox", FatalCleanupSandbox)

    with pytest.raises(MediaWorkerCleanupError, match="could not be stopped"):
        list(FixtureMediaExtractor(exclusion_writer=writer).run([media]))
    assert not writer.records
    assert "extraction_failed" not in media.media[0]["metadata"]
    assert writer.closed


def test_html_pipeline_does_not_convert_fatal_cleanup_to_a_rejection(monkeypatch):
    from helpers.extractor import html

    writer = ParentWriter()
    page = Document(id="fatal-html", text="<p>Fixture</p>")
    monkeypatch.setattr(html, "MediaExtractionSandbox", FatalCleanupSandbox)

    with pytest.raises(MediaWorkerCleanupError, match="could not be stopped"):
        list(html.HtmlTextExtractor(exclusion_writer=writer).run([page]))
    assert not writer.records
    assert "html_extraction_error" not in page.metadata
    assert writer.closed
