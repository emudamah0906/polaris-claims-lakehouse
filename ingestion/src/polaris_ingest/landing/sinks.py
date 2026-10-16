"""Sinks: the only code that knows where bytes physically go.

Everything above this layer works in keys like
"claims/year=2026/month=10/day=16/part-00000.csv". A sink turns a key into a
real file. LocalSink writes to a folder, for development and tests. AdlsSink
(Azure Data Lake Storage) arrives in step 6 with the same two methods, so the
landing code doesn't change when the target does.
"""

from __future__ import annotations

import os
import tempfile
from abc import ABC, abstractmethod
from pathlib import Path


class Sink(ABC):
    @abstractmethod
    def write(self, key: str, data: bytes) -> str:
        """Write `data` at `key`, replacing anything there. Returns where it went."""

    @abstractmethod
    def delete(self, key: str) -> None:
        """Remove `key` if it exists. No error if it doesn't."""


class LocalSink(Sink):
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).expanduser().resolve()

    def write(self, key: str, data: bytes) -> str:
        path = self.root / key
        path.parent.mkdir(parents=True, exist_ok=True)
        # Write to a temp file, then rename over the target. The rename is
        # atomic, so a crash mid-write never leaves a half-written CSV behind.
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-")
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(data)
            os.replace(tmp, path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise
        return str(path)

    def delete(self, key: str) -> None:
        (self.root / key).unlink(missing_ok=True)


def make_sink(backend: str, root: str | Path) -> Sink:
    if backend == "local":
        return LocalSink(root)
    raise ValueError(f"unknown backend {backend!r} (only 'local' until step 6)")
