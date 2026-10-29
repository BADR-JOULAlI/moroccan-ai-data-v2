"""Bound media extraction in an owned, reusable worker on Windows and POSIX."""

from __future__ import annotations

import math
import multiprocessing
from time import monotonic

import dill


class MediaExtractionError(RuntimeError):
    """The worker could not initialize or the extraction callable failed."""


class MediaWorkerCleanupError(RuntimeError):
    """An owned worker could not be stopped; processing must not continue."""


def _media_worker(connection, callback_payload: bytes) -> None:
    """Top-level spawn target; only the worker owns the extraction callable."""
    try:
        callback = dill.loads(callback_payload)
        connection.send(("ready", None))
        while True:
            request = connection.recv()
            if request is None:
                break
            media_bytes, metadata = request
            try:
                result = callback(media_bytes, metadata)
            except Exception as exc:
                connection.send(("error", f"{type(exc).__name__}: {exc}"))
            else:
                connection.send(("result", result))
    except (EOFError, BrokenPipeError, OSError):
        pass
    except Exception as exc:
        try:
            connection.send(("error", f"{type(exc).__name__}: {exc}"))
        except (BrokenPipeError, OSError):
            pass
    finally:
        connection.close()


class MediaExtractionSandbox:
    """Execute a callable with a deadline and restart after timeout or crash.

    The deadline includes worker initialization for the first document. The
    callable is serialized once before extraction starts; model state created
    inside the worker is reused between documents. No synthetic warmup input is
    sent to the callable.
    """

    def __init__(self, timeout: float, extract_fn):
        self.timeout = float(timeout)
        if not math.isfinite(self.timeout) or self.timeout <= 0:
            raise ValueError("Extraction timeout must be a positive finite number")
        try:
            self._callback_payload = dill.dumps(extract_fn)
        except Exception as exc:
            raise MediaExtractionError(f"Cannot serialize extraction callable: {exc}") from exc
        self._context = multiprocessing.get_context("spawn")
        self._process = None
        self._connection = None
        self._cleanup_failed = False

    def _stop_worker(self) -> None:
        process, connection = self._process, self._connection
        connection_error = None
        if connection is not None:
            try:
                connection.close()
            except Exception as exc:
                connection_error = exc
            else:
                self._connection = None
        if process is not None:
            pid = process.pid
            try:
                if process.is_alive():
                    process.terminate()
                process.join(timeout=1)
                if process.is_alive():
                    process.kill()
                    process.join(timeout=1)
                if process.is_alive():
                    raise MediaWorkerCleanupError(f"Unable to stop extraction worker {pid}")
                process.close()
            except Exception as exc:
                # Keep ownership so __exit__ or an explicit cleanup can retry.
                # Starting another worker would otherwise orphan this one.
                self._cleanup_failed = True
                if isinstance(exc, MediaWorkerCleanupError):
                    raise
                raise MediaWorkerCleanupError(
                    f"Unable to clean up extraction worker {pid}: {exc}"
                ) from exc
            else:
                self._process = None
        if connection_error is not None:
            self._cleanup_failed = True
            raise MediaWorkerCleanupError(
                f"Unable to close extraction worker communication channel: {connection_error}"
            ) from connection_error
        self._cleanup_failed = False

    def _receive(self, deadline: float):
        while True:
            remaining = deadline - monotonic()
            if remaining <= 0:
                raise TimeoutError("Media extraction timed out")
            if self._connection.poll(min(remaining, 0.05)):
                return self._connection.recv()
            if not self._process.is_alive():
                raise EOFError("Extraction worker exited before returning a result")

    def _ensure_worker(self, deadline: float) -> None:
        if self._cleanup_failed:
            raise MediaWorkerCleanupError(
                "A previous extraction worker could not be stopped; sandbox cannot continue"
            )
        if self._process is not None and self._process.is_alive():
            return
        self._stop_worker()
        parent, child = self._context.Pipe()
        process = self._context.Process(
            target=_media_worker, args=(child, self._callback_payload), daemon=True,
        )
        try:
            process.start()
        except Exception as exc:
            parent.close()
            child.close()
            process.close()
            raise MediaExtractionError(f"Cannot start extraction worker: {exc}") from exc
        child.close()
        self._process, self._connection = process, parent
        status, payload = self._receive(deadline)
        if status != "ready":
            self._stop_worker()
            raise MediaExtractionError(f"Extraction worker initialization failed: {payload}")

    def process(self, media_bytes: bytes | None, metadata: dict) -> tuple[str, dict]:
        deadline = monotonic() + self.timeout
        try:
            self._ensure_worker(deadline)
            self._connection.send((media_bytes, metadata))
            status, payload = self._receive(deadline)
            if status == "error":
                raise MediaExtractionError(payload)
            if status != "result":
                raise MediaExtractionError(f"Unexpected extraction worker message: {status}")
            return payload
        except (TimeoutError, EOFError, BrokenPipeError, OSError):
            self._stop_worker()
            raise

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self._stop_worker()
