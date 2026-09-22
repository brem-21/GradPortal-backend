"""Local filesystem storage for uploaded originals.

Originals are kept so a document can be re-parsed and re-indexed after a
chunking or model change without asking the user to upload it again. Files are
namespaced per user and named by content hash.

In production this is an object-store adapter; the interface is these three
functions.
"""

import hashlib
from pathlib import Path

from doc_service.config import settings


def _user_dir(user_key: str) -> Path:
    # Hash the email so a filesystem path never leaks a personal address.
    bucket = hashlib.sha256(user_key.encode()).hexdigest()[:16]
    path = Path(settings.document_storage_dir) / bucket
    path.mkdir(parents=True, exist_ok=True)
    return path


def content_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def save(user_key: str, digest: str, filename: str, data: bytes) -> str:
    suffix = Path(filename).suffix.lower()[:10]
    destination = _user_dir(user_key) / f"{digest}{suffix}"
    destination.write_bytes(data)
    return str(destination)


def load(storage_path: str) -> bytes | None:
    path = Path(storage_path)
    return path.read_bytes() if path.exists() else None


def delete(storage_path: str) -> None:
    path = Path(storage_path)
    if path.exists():
        path.unlink()
