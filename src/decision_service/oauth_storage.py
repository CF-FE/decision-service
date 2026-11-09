"""Bounded file storage for a single Decision Service OAuth instance.

Adapted from create-network-sh/fastmcp/task-mailbox/oauth_storage.py.
"""
import asyncio
import json
import os
import stat
from pathlib import Path

from key_value.aio.stores.filetree import (
    FileTreeStore,
    FileTreeV1CollectionSanitizationStrategy,
    FileTreeV1KeySanitizationStrategy,
)


class OAuthStorageFull(RuntimeError):
    """The dedicated OAuth store cannot admit a write."""


class BoundedOAuthFileTreeStore(FileTreeStore):
    def __init__(self, directory: Path, max_bytes: int, max_files: int):
        self.directory = directory.resolve()
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.max_bytes = max_bytes
        self.max_files = max_files
        self.write_lock = asyncio.Lock()
        super().__init__(
            data_directory=self.directory,
            key_sanitization_strategy=FileTreeV1KeySanitizationStrategy(self.directory),
            collection_sanitization_strategy=FileTreeV1CollectionSanitizationStrategy(self.directory),
        )

    def usage(self):
        files = allocated = 0
        pending = [self.directory]
        while pending:
            path = pending.pop()
            info = path.lstat()
            allocated += max(info.st_size, info.st_blocks * 512)
            if stat.S_ISDIR(info.st_mode):
                with os.scandir(path) as entries:
                    pending.extend(Path(entry.path) for entry in entries)
            elif stat.S_ISREG(info.st_mode):
                files += 1
            else:
                raise OAuthStorageFull("OAuth storage contains an unsupported entry.")
        return files, allocated

    async def admit(self, values):
        # The encryption wrapper supplies encrypted payloads. Reserve space for
        # both data and metadata, including filesystem blocks and directories.
        reserve = sum(
            2 * len(json.dumps(value, ensure_ascii=True, separators=(",", ":")).encode()) + 16384
            for value in values
        )
        files, allocated = await asyncio.to_thread(self.usage)
        if files + 2 * len(values) > self.max_files or allocated + reserve > self.max_bytes:
            raise OAuthStorageFull("OAuth storage capacity reached.")

    async def put(self, key, value, *, collection=None, ttl=None):
        snapshot = dict(value)
        async with self.write_lock:
            await self.admit([snapshot])
            await super().put(key, snapshot, collection=collection, ttl=ttl)

    async def put_many(self, keys, values, *, collection=None, ttl=None):
        snapshots = [dict(value) for value in values]
        async with self.write_lock:
            await self.admit(snapshots)
            await super().put_many(keys, snapshots, collection=collection, ttl=ttl)
