"""Sinks: the only code that knows where bytes physically go.

Everything above this layer works in keys like
"claims/year=2026/month=10/day=16/part-00000.csv". A sink turns a key into a
real file. LocalSink writes to a folder, for development and tests. AdlsSink
writes to Azure Data Lake Storage Gen2. Both have the same two methods, so the
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

    @abstractmethod
    def read(self, key: str) -> bytes | None:
        """The bytes at `key`, or None if nothing is there. Stage 2b reads its watermark file."""


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

    def read(self, key: str) -> bytes | None:
        path = self.root / key
        return path.read_bytes() if path.is_file() else None


class AdlsSink(Sink):
    """Writes to one ADLS Gen2 container, e.g. abfss://bronze@<account>.dfs.core.windows.net/.

    Logs in with DefaultAzureCredential, which tries environment variables,
    then managed identity, then your `az login` session. So the same code runs
    on a laptop (az login), in CI (OIDC) and in production (managed identity)
    with no keys anywhere (ADR-0008).
    """

    def __init__(self, account: str, container: str, file_system_client=None) -> None:
        self.account = account
        self.container = container
        if file_system_client is None:
            # Imported here so local runs and tests don't load the Azure SDK
            from azure.identity import DefaultAzureCredential
            from azure.storage.filedatalake import DataLakeServiceClient

            service = DataLakeServiceClient(
                account_url=f"https://{account}.dfs.core.windows.net",
                credential=DefaultAzureCredential(),
            )
            file_system_client = service.get_file_system_client(container)
        self.fs = file_system_client

    def write(self, key: str, data: bytes) -> str:
        file = self.fs.get_file_client(key)
        if not data:
            # The SDK's upload_data returns early on 0 bytes and creates
            # nothing, with no error. That silently dropped every _SUCCESS
            # marker. create_file makes the empty file and replaces any old one.
            file.create_file()
        else:
            # upload_data creates, appends and then flushes. The file only
            # changes on the final flush, so readers see the old file or the
            # new one, never half of one. Same guarantee as LocalSink's rename.
            file.upload_data(data, overwrite=True)
        return f"abfss://{self.container}@{self.account}.dfs.core.windows.net/{key}"

    def delete(self, key: str) -> None:
        from azure.core.exceptions import ResourceNotFoundError

        try:
            self.fs.get_file_client(key).delete_file()
        except ResourceNotFoundError:
            pass  # already gone is fine

    def read(self, key: str) -> bytes | None:
        from azure.core.exceptions import ResourceNotFoundError

        try:
            return self.fs.get_file_client(key).download_file().readall()
        except ResourceNotFoundError:
            return None


def make_sink(
    backend: str, root: str | Path = "data/bronze", account: str | None = None,
    container: str = "bronze",
) -> Sink:
    if backend == "local":
        return LocalSink(root)
    if backend == "azure":
        if not account:
            raise ValueError(
                "azure backend needs a storage account: pass --account or set "
                "ADLS_ACCOUNT_NAME (terraform output storage_account_name)"
            )
        return AdlsSink(account, container)
    raise ValueError(f"unknown backend {backend!r}")
