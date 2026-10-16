"""Storage provider interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import BinaryIO


class StorageObjectMissing(Exception):
    """Raised when a stored object key does not exist."""


class StorageProvider(ABC):
    """Key/bytes object store with category-scoped keys and immutable writes.

    Categories (bucket-style prefixes) keep deployment mapping simple:
    answer-sheet ZIPs, original PDFs, answer-key files, rendered pages,
    question crops, student/key diagram crops, generated artifacts.
    """

    @abstractmethod
    def put(self, category: str, key: str, data: bytes, content_type: str | None = None) -> str:
        """Store bytes immutably; returns the canonical object key."""

    @abstractmethod
    def open(self, key: str) -> BinaryIO:
        """Open an object for reading."""

    @abstractmethod
    def get(self, key: str) -> bytes:
        """Read the full object."""

    @abstractmethod
    def exists(self, key: str) -> bool: ...

    @abstractmethod
    def delete(self, key: str) -> None: ...
