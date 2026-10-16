"""Object storage abstraction.

`StorageProvider` lets deployments swap between local-disk development storage
and Supabase Storage/S3/MinIO later without touching business logic.
Originals are written immutably (sha256-addressed keys).
"""

from answer_eval.storage.base import StorageObjectMissing, StorageProvider
from answer_eval.storage.local import LocalStorageProvider

__all__ = ["StorageProvider", "StorageObjectMissing", "LocalStorageProvider"]
