"""Local filesystem storage (development default).

Keys are sandboxed under the configured root; traversal outside the root is
rejected. Objects are content-addressed by callers, so `put` refuses to
overwrite existing bytes (immutability).
"""

from __future__ import annotations

import hashlib
import hmac
import os
from pathlib import Path
from typing import BinaryIO

from answer_eval.storage.base import StorageObjectMissing, StorageProvider


class LocalStorageProvider(StorageProvider):
    def __init__(self, root: str | os.PathLike[str]) -> None:
        self._root = Path(root).resolve()
        self._root.mkdir(parents=True, exist_ok=True)

    # -- helpers -------------------------------------------------------------

    def _resolve(self, key: str) -> Path:
        candidate = (self._root / key).resolve()
        if not candidate.is_relative_to(self._root):
            raise ValueError(f"Storage key escapes sandbox: {key!r}")
        return candidate

    # -- StorageProvider -----------------------------------------------------

    def put(self, category: str, key: str, data: bytes, content_type: str | None = None) -> str:
        full_key = f"{category.strip('/')}/{key.lstrip('/')}"
        target = self._resolve(full_key)
        if target.exists():
            existing = hashlib.sha256(target.read_bytes()).hexdigest()
            incoming = hashlib.sha256(data).hexdigest()
            if existing != incoming:
                raise ValueError(f"Refusing to overwrite immutable object {full_key}")
            return full_key
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(target.suffix + ".part")
        tmp.write_bytes(data)
        os.replace(tmp, target)
        return full_key

    def open(self, key: str) -> BinaryIO:
        path = self._resolve(key)
        if not path.is_file():
            raise StorageObjectMissing(key)
        return path.open("rb")

    def get(self, key: str) -> bytes:
        with self.open(key) as handle:
            return handle.read()

    def exists(self, key: str) -> bool:
        return self._resolve(key).is_file()

    def delete(self, key: str) -> None:
        path = self._resolve(key)
        if path.is_file():
            path.unlink()


def signing_secret_from_env(secret: str) -> bytes:
    """Helper used by signed-download token generation."""
    return hmac.digest(secret.encode(), b"evalai-storage", "sha256")
