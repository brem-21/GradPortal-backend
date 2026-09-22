"""Media storage: type gating, path safety and header parsing."""

import pathlib

import pytest

from app.services import media_storage


class TestTypeGating:
    def test_accepts_the_formats_the_admin_ui_offers(self):
        for content_type in (
            "image/jpeg",
            "image/png",
            "image/webp",
            "image/gif",
            "image/avif",
            "video/mp4",
            "video/webm",
        ):
            assert content_type in media_storage.ALLOWED

    def test_rejects_arbitrary_types(self):
        for content_type in ("application/pdf", "text/html", "image/svg+xml"):
            assert content_type not in media_storage.ALLOWED

    def test_gif_is_classified_separately_from_still_images(self):
        # The slideshow treats an animated GIF as motion, like a video.
        assert media_storage.kind_for("image/gif") == "gif"
        assert media_storage.kind_for("image/jpeg") == "image"
        assert media_storage.kind_for("video/mp4") == "video"


class TestSafeNaming:
    @pytest.mark.parametrize(
        ("given", "expected"),
        [
            ("Campus Walk.jpg", "campus-walk"),
            # Path() drops directory components, so traversal cannot survive.
            ("../../etc/passwd", "passwd"),
            ("wei®d ch@rs!.png", "wei-d-ch-rs"),
            # Would otherwise write a hidden file named ".jpg-<hash>.jpg".
            (".jpg", "jpg"),
            (" .png", "media"),
            ("....", "media"),
        ],
    )
    def test_stem_is_sanitised(self, given: str, expected: str):
        assert media_storage.safe_stem(given) == expected

    def test_saved_name_is_deterministic_for_identical_bytes(self):
        data = b"same bytes"
        a = media_storage.safe_stem("x.jpg"), media_storage.content_hash(data)[:16]
        b = media_storage.safe_stem("x.jpg"), media_storage.content_hash(data)[:16]
        assert a == b


class TestDeleteIsConfined:
    def test_traversal_outside_the_media_root_is_ignored(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            media_storage.settings, "media_storage_dir", str(tmp_path / "media")
        )
        outside = tmp_path / "secret.txt"
        outside.write_text("do not delete me")

        media_storage.delete("../secret.txt")

        assert outside.exists(), "delete() escaped the media directory"


class TestImageDimensions:
    def test_reads_a_real_jpeg(self):
        sample = (
            pathlib.Path(__file__).resolve().parents[1] / "seed_media" / "campus-walk.jpg"
        )
        if not sample.exists():
            pytest.skip("sample image not present")
        assert media_storage.image_dimensions(sample.read_bytes()) == (1600, 1066)

    def test_unknown_format_returns_none_rather_than_raising(self):
        assert media_storage.image_dimensions(b"not an image at all") is None

    def test_truncated_header_returns_none(self):
        assert media_storage.image_dimensions(b"\x89PNG\r\n\x1a\n") is None
