"""Local storage for admin-uploaded site media.

Files are written under MEDIA_STORAGE_DIR and served read-only by FastAPI at
/media/<name>. In production this becomes an object-store adapter and a CDN;
the interface is these functions plus MediaAsset.storage_path.
"""

import hashlib
import re
import struct
from pathlib import Path

from app.core.config import settings

# Deliberately narrow. GIF is accepted because it was asked for, and is where
# animated background content usually arrives from, even though a silent MP4 is
# a far better format for the same effect.
IMAGE_TYPES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
    "image/avif": ".avif",
}
VIDEO_TYPES = {
    "video/mp4": ".mp4",
    "video/webm": ".webm",
}
ALLOWED = {**IMAGE_TYPES, **VIDEO_TYPES}

SAFE_NAME = re.compile(r"[^a-z0-9._-]+")


def media_root() -> Path:
    path = Path(settings.media_storage_dir)
    path.mkdir(parents=True, exist_ok=True)
    return path


def kind_for(content_type: str) -> str:
    if content_type == "image/gif":
        return "gif"
    if content_type in VIDEO_TYPES:
        return "video"
    return "image"


def content_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def safe_stem(filename: str) -> str:
    """Reduce a filename to a safe slug for the stored name.

    Path() drops any directory component, so traversal cannot survive. The
    leading/trailing strip matters for names like ".jpg", which would otherwise
    yield a stem of ".jpg" and write a hidden file.
    """
    stem = Path(filename).stem.lower().replace(" ", "-")
    stem = SAFE_NAME.sub("-", stem)
    stem = re.sub(r"-{2,}", "-", stem).strip(".-")[:48].strip(".-")
    return stem or "media"


def save(data: bytes, filename: str, content_type: str) -> str:
    """Write the file and return its storage path (the name under /media)."""
    extension = ALLOWED.get(content_type, Path(filename).suffix.lower() or ".bin")
    digest = content_hash(data)[:16]
    name = f"{safe_stem(filename)}-{digest}{extension}"
    (media_root() / name).write_bytes(data)
    return name


def delete(storage_path: str) -> None:
    # Never let a stored path escape the media directory.
    target = (media_root() / Path(storage_path).name).resolve()
    if target.is_relative_to(media_root().resolve()) and target.exists():
        target.unlink()


def image_dimensions(data: bytes) -> tuple[int, int] | None:
    """Read width/height from the file header without a decoding dependency.

    Only used to show the admin what they uploaded, so an unrecognised format
    returning None is fine.
    """
    try:
        if data[:8] == b"\x89PNG\r\n\x1a\n":
            width, height = struct.unpack(">II", data[16:24])
            return int(width), int(height)

        if data[:6] in (b"GIF87a", b"GIF89a"):
            width, height = struct.unpack("<HH", data[6:10])
            return int(width), int(height)

        if data[:2] == b"\xff\xd8":  # JPEG: walk the segment markers
            index = 2
            while index < len(data) - 9:
                if data[index] != 0xFF:
                    index += 1
                    continue
                marker = data[index + 1]
                if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB):
                    height, width = struct.unpack(">HH", data[index + 5 : index + 9])
                    return int(width), int(height)
                segment = struct.unpack(">H", data[index + 2 : index + 4])[0]
                index += 2 + segment

        if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
            if data[12:16] == b"VP8X":
                width = int.from_bytes(data[24:27], "little") + 1
                height = int.from_bytes(data[27:30], "little") + 1
                return width, height
    except (struct.error, IndexError, ValueError):
        return None
    return None
