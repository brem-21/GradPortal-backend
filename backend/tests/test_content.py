"""Consent and slot rules for admin-managed site content."""

import pytest

from app.models import MediaSlot, SuccessStory


class TestMediaSlots:
    def test_every_slot_has_a_label(self):
        for slot in MediaSlot.ALL:
            assert slot in MediaSlot.LABELS
            assert MediaSlot.LABELS[slot]

    def test_slot_names_are_unique(self):
        assert len(MediaSlot.ALL) == len(set(MediaSlot.ALL))

    def test_gallery_is_a_slot(self):
        # The gallery strip shares the upload pipeline with the backgrounds.
        assert MediaSlot.GALLERY in MediaSlot.ALL


class TestStoryInitials:
    @pytest.mark.parametrize(
        ("name", "expected"),
        [
            ("Ama Boateng", "AB"),
            ("Kwesi", "K"),
            ("Jane Mary Okonkwo", "JM"),
            ("", "?"),
            ("   ", "?"),
        ],
    )
    def test_initials(self, name: str, expected: str):
        assert SuccessStory(name=name, outcome="x", quote="y").initials == expected


class TestPhotoUrl:
    def test_none_without_a_photo(self):
        assert SuccessStory(name="A", outcome="x", quote="y").photo_url is None

    def test_served_under_media(self):
        story = SuccessStory(name="A", outcome="x", quote="y", photo_path="a-1234.jpg")
        assert story.photo_url == "/media/a-1234.jpg"


class TestConsentGuard:
    """The publish guard is the point of the feature; assert its exact shape."""

    def test_published_without_consent_is_rejected(self):
        from fastapi import HTTPException

        from app.api.v1.content import _guard_publish

        story = SuccessStory(
            name="A", outcome="x", quote="y", published=True, consent_confirmed=False
        )
        with pytest.raises(HTTPException) as info:
            _guard_publish(story)
        assert info.value.status_code == 422
        assert "consent" in info.value.detail.lower()

    def test_published_with_consent_is_allowed(self):
        from app.api.v1.content import _guard_publish

        _guard_publish(
            SuccessStory(
                name="A", outcome="x", quote="y", published=True, consent_confirmed=True
            )
        )

    def test_draft_without_consent_is_allowed(self):
        from app.api.v1.content import _guard_publish

        _guard_publish(
            SuccessStory(
                name="A", outcome="x", quote="y", published=False, consent_confirmed=False
            )
        )
