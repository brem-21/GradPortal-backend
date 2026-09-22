"""Admin-managed site content: background media and success stories.

The public read endpoints are deliberately unauthenticated — the landing page
renders them to signed-out visitors, and requiring a token there would mean the
marketing page could not show its own backgrounds.
"""

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import require_admin
from app.core.db import get_db
from app.models import MediaAsset, MediaSlot, SuccessStory, User
from app.schemas.common import Message
from app.schemas.content import (
    MediaAssetList,
    MediaAssetRead,
    MediaAssetUpdate,
    SiteMedia,
    Slide,
    SlideSet,
    SlotOption,
    SuccessStoryCreate,
    SuccessStoryList,
    SuccessStoryPublic,
    SuccessStoryRead,
    SuccessStoryUpdate,
)
from app.services import media_storage

router = APIRouter(tags=["content"])
admin_router = APIRouter(prefix="/admin", tags=["admin:content"])

# Per-slot presentation defaults. An asset can override the overlay.
SLOT_DEFAULTS: dict[str, tuple[int, float]] = {
    MediaSlot.HERO: (8000, 0.60),
    MediaSlot.CLOSING: (10000, 0.66),
    MediaSlot.MENTOR_CARD: (11000, 0.58),
    MediaSlot.FOOTER: (13000, 0.78),
    MediaSlot.SIGNIN: (9000, 0.55),
    MediaSlot.COMMUNITY: (12000, 0.70),
    MediaSlot.GALLERY: (0, 0.0),
}


def _to_slide(asset: MediaAsset) -> Slide:
    return Slide(
        id=asset.id,
        src=asset.url,
        # A video needs a still to show while it buffers and for reduced-motion
        # visitors; we do not generate one, so fall back to the file itself.
        poster=asset.url if asset.kind != "video" else None,
        kind=asset.kind,
        alt=asset.alt_text or asset.title or "",
        credit=asset.credit,
        overlay=asset.overlay,
    )


# ---------------------------------------------------------------- public


@router.get("/site/media", response_model=SiteMedia)
def site_media(db: Session = Depends(get_db)) -> SiteMedia:
    """Every enabled asset, grouped by slot. Public."""
    assets = list(
        db.scalars(
            select(MediaAsset)
            .where(MediaAsset.enabled.is_(True))
            .order_by(MediaAsset.position, MediaAsset.created_at)
        ).all()
    )

    sets: dict[str, SlideSet] = {}
    for slot in MediaSlot.ALL:
        if slot == MediaSlot.GALLERY:
            continue
        interval, overlay = SLOT_DEFAULTS[slot]
        slides = [_to_slide(a) for a in assets if slot in (a.slots or [])]
        sets[slot] = SlideSet(
            slot=slot,
            label=MediaSlot.LABELS[slot],
            slides=slides,
            interval_ms=interval,
            overlay=overlay,
        )

    gallery = [_to_slide(a) for a in assets if MediaSlot.GALLERY in (a.slots or [])]
    return SiteMedia(sets=sets, gallery=gallery)


@router.get("/site/stories", response_model=list[SuccessStoryPublic])
def site_stories(
    limit: int = Query(12, ge=1, le=50), db: Session = Depends(get_db)
) -> list[SuccessStoryPublic]:
    """Published stories. Unpublished and unconsented ones are never returned."""
    rows = db.scalars(
        select(SuccessStory)
        .where(
            SuccessStory.published.is_(True),
            SuccessStory.consent_confirmed.is_(True),
        )
        .order_by(SuccessStory.position, SuccessStory.created_at.desc())
        .limit(limit)
    ).all()
    return [SuccessStoryPublic.model_validate(row) for row in rows]


# ---------------------------------------------------------------- admin: media


@admin_router.get("/media/slots", response_model=list[SlotOption])
def media_slots(
    _: User = Depends(require_admin), db: Session = Depends(get_db)
) -> list[SlotOption]:
    counts = {
        slot: db.scalar(
            select(func.count())
            .select_from(MediaAsset)
            .where(MediaAsset.slots.any(slot), MediaAsset.enabled.is_(True))
        )
        or 0
        for slot in MediaSlot.ALL
    }
    return [
        SlotOption(value=slot, label=MediaSlot.LABELS[slot], asset_count=counts[slot])
        for slot in MediaSlot.ALL
    ]


@admin_router.get("/media", response_model=MediaAssetList)
def list_media(
    slot: str | None = None,
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> MediaAssetList:
    statement = select(MediaAsset).order_by(MediaAsset.position, MediaAsset.created_at.desc())
    if slot:
        statement = statement.where(MediaAsset.slots.any(slot))
    rows = list(db.scalars(statement).all())
    return MediaAssetList(
        items=[MediaAssetRead.model_validate(row) for row in rows], total=len(rows)
    )


@admin_router.post("/media", response_model=MediaAssetRead, status_code=status.HTTP_201_CREATED)
async def upload_media(
    file: UploadFile = File(...),
    alt_text: str = Form(...),
    slots: list[str] = Form(default=[]),
    title: str | None = Form(None),
    credit: str | None = Form(None),
    position: int = Form(0),
    overlay: float | None = Form(None),
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> MediaAssetRead:
    """Upload a background image, GIF or silent video loop."""
    from app.core.config import settings

    content_type = (file.content_type or "").split(";")[0]
    if content_type not in media_storage.ALLOWED:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "Unsupported file type. Upload a JPEG, PNG, WebP, AVIF, GIF, MP4 or WebM."
            ),
        )

    data = await file.read()
    if not data:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="The file is empty."
        )
    if len(data) > settings.max_media_upload_bytes:
        limit = settings.max_media_upload_bytes // (1024 * 1024)
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"That file is larger than the {limit}MB limit.",
        )

    cleaned_alt = alt_text.strip()
    if not cleaned_alt:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Alt text is required — the gallery shows these as content.",
        )

    # Multipart repeats the key per value; also accept one comma-joined string.
    wanted_slots: list[str] = []
    for entry in slots:
        wanted_slots.extend(part.strip() for part in entry.split(",") if part.strip())
    unknown = [s for s in wanted_slots if s not in MediaSlot.ALL]
    if unknown:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unknown slot(s): {', '.join(unknown)}",
        )

    digest = media_storage.content_hash(data)
    existing = db.scalar(select(MediaAsset).where(MediaAsset.sha256 == digest))
    if existing is not None:
        # Same bytes already uploaded: extend its slots rather than duplicate.
        merged = sorted({*(existing.slots or []), *wanted_slots})
        existing.slots = merged
        existing.enabled = True
        if title:
            existing.title = title
        if cleaned_alt:
            existing.alt_text = cleaned_alt
        db.flush()
        return MediaAssetRead.model_validate(existing)

    storage_path = media_storage.save(data, file.filename or "upload", content_type)
    dimensions = media_storage.image_dimensions(data)

    asset = MediaAsset(
        filename=(file.filename or "upload")[:300],
        content_type=content_type,
        size_bytes=len(data),
        sha256=digest,
        storage_path=storage_path,
        kind=media_storage.kind_for(content_type),
        width=dimensions[0] if dimensions else None,
        height=dimensions[1] if dimensions else None,
        title=(title or None),
        alt_text=cleaned_alt[:500],
        credit=(credit or None),
        slots=sorted(set(wanted_slots)),
        position=position,
        overlay=overlay,
        uploaded_by_user_id=user.id,
    )
    db.add(asset)
    db.flush()
    return MediaAssetRead.model_validate(asset)


@admin_router.patch("/media/{asset_id}", response_model=MediaAssetRead)
def update_media(
    asset_id: uuid.UUID,
    payload: MediaAssetUpdate,
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> MediaAssetRead:
    asset = db.get(MediaAsset, asset_id)
    if asset is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Media not found")

    data = payload.model_dump(exclude_unset=True)
    if "slots" in data and data["slots"] is not None:
        unknown = [s for s in data["slots"] if s not in MediaSlot.ALL]
        if unknown:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Unknown slot(s): {', '.join(unknown)}",
            )
        data["slots"] = sorted(set(data["slots"]))
    if "alt_text" in data and data["alt_text"] is not None and not data["alt_text"].strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Alt text cannot be empty."
        )

    for key, value in data.items():
        setattr(asset, key, value)
    db.flush()
    return MediaAssetRead.model_validate(asset)


@admin_router.delete("/media/{asset_id}", response_model=Message)
def delete_media(
    asset_id: uuid.UUID,
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> Message:
    asset = db.get(MediaAsset, asset_id)
    if asset is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Media not found")
    media_storage.delete(asset.storage_path)
    db.delete(asset)
    return Message(detail="Media deleted.")


# ---------------------------------------------------------------- admin: stories


@admin_router.get("/stories", response_model=SuccessStoryList)
def list_stories(
    _: User = Depends(require_admin), db: Session = Depends(get_db)
) -> SuccessStoryList:
    rows = list(
        db.scalars(
            select(SuccessStory).order_by(SuccessStory.position, SuccessStory.created_at.desc())
        ).all()
    )
    return SuccessStoryList(
        items=[SuccessStoryRead.model_validate(row) for row in rows], total=len(rows)
    )


def _guard_publish(story: SuccessStory) -> None:
    if story.published and not story.consent_confirmed:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "A story cannot be published until consent is confirmed. Publishing an "
                "invented or unconsented testimonial as genuine is deceptive advertising, "
                "and using someone's name or photo without permission is a likeness issue."
            ),
        )


@admin_router.post(
    "/stories", response_model=SuccessStoryRead, status_code=status.HTTP_201_CREATED
)
def create_story(
    payload: SuccessStoryCreate,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> SuccessStoryRead:
    story = SuccessStory(**payload.model_dump(), created_by_user_id=user.id)
    _guard_publish(story)
    if story.consent_confirmed:
        story.consent_recorded_at = datetime.now(UTC)
    db.add(story)
    db.flush()
    return SuccessStoryRead.model_validate(story)


@admin_router.patch("/stories/{story_id}", response_model=SuccessStoryRead)
def update_story(
    story_id: uuid.UUID,
    payload: SuccessStoryUpdate,
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> SuccessStoryRead:
    story = db.get(SuccessStory, story_id)
    if story is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Story not found")

    was_consented = story.consent_confirmed
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(story, key, value)
    _guard_publish(story)
    if story.consent_confirmed and not was_consented:
        story.consent_recorded_at = datetime.now(UTC)
    db.flush()
    return SuccessStoryRead.model_validate(story)


@admin_router.delete("/stories/{story_id}", response_model=Message)
def delete_story(
    story_id: uuid.UUID,
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> Message:
    story = db.get(SuccessStory, story_id)
    if story is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Story not found")
    if story.photo_path:
        media_storage.delete(story.photo_path)
    db.delete(story)
    return Message(detail="Story deleted.")


@admin_router.post("/stories/photo", response_model=dict)
async def upload_story_photo(
    file: UploadFile = File(...),
    _: User = Depends(require_admin),
) -> dict:
    """Upload a photograph for a story and return its path.

    Kept separate from the story record so the admin can see the image before
    committing the story, and so a failed upload never leaves a half-made story.
    """
    from app.core.config import settings

    content_type = (file.content_type or "").split(";")[0]
    if content_type not in media_storage.IMAGE_TYPES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="A story photo must be a JPEG, PNG, WebP, AVIF or GIF.",
        )
    data = await file.read()
    if len(data) > settings.max_media_upload_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="That image is too large."
        )
    path = media_storage.save(data, file.filename or "photo", content_type)
    return {"photo_path": path, "photo_url": f"/media/{path}"}
