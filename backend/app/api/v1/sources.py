import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agent.pipeline import run_all_sources, run_source
from app.agent.registry import get_adapter, list_adapters
from app.agent.seeds import SEED_SOURCES
from app.api.deps import require_admin
from app.core.db import SessionLocal, get_db
from app.core.enums import SourceKind
from app.models import Source, User
from app.schemas.common import Message
from app.schemas.opportunity import SourceRead

router = APIRouter(prefix="/admin/sources", tags=["admin:sources"])


class SourceCreate(BaseModel):
    slug: str = Field(max_length=128)
    name: str
    kind: SourceKind = SourceKind.UNIVERSITY
    adapter: str
    base_url: str | None = None
    config: dict = Field(default_factory=dict)
    enabled: bool = True


class SourceUpdate(BaseModel):
    name: str | None = None
    kind: SourceKind | None = None
    adapter: str | None = None
    base_url: str | None = None
    config: dict | None = None
    enabled: bool | None = None


@router.get("/adapters")
def available_adapters(_: User = Depends(require_admin)) -> list[dict]:
    """Which adapters exist, and whether their credentials are in place."""
    return list_adapters()


@router.get("", response_model=list[SourceRead])
def list_sources(
    _: User = Depends(require_admin), db: Session = Depends(get_db)
) -> list[SourceRead]:
    rows = db.scalars(select(Source).order_by(Source.name)).all()
    return [SourceRead.model_validate(r) for r in rows]


@router.post("", response_model=SourceRead, status_code=status.HTTP_201_CREATED)
def create_source(
    payload: SourceCreate,
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> SourceRead:
    adapter = get_adapter(payload.adapter)
    if adapter is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown adapter '{payload.adapter}'.",
        )
    if db.scalar(select(Source).where(Source.slug == payload.slug)):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="A source with that slug exists."
        )

    source = Source(
        **payload.model_dump(),
        requires_credentials=adapter.requires_credentials,
    )
    db.add(source)
    db.flush()
    return SourceRead.model_validate(source)


@router.patch("/{source_id}", response_model=SourceRead)
def update_source(
    source_id: uuid.UUID,
    payload: SourceUpdate,
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> SourceRead:
    source = db.get(Source, source_id)
    if source is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Source not found")

    data = payload.model_dump(exclude_unset=True)
    if "adapter" in data:
        adapter = get_adapter(data["adapter"])
        if adapter is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unknown adapter '{data['adapter']}'.",
            )
        source.requires_credentials = adapter.requires_credentials

    for key, value in data.items():
        setattr(source, key, value)
    db.flush()
    return SourceRead.model_validate(source)


@router.delete("/{source_id}", response_model=Message)
def delete_source(
    source_id: uuid.UUID,
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> Message:
    source = db.get(Source, source_id)
    if source is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Source not found")
    db.delete(source)
    return Message(detail="Source deleted.")


@router.post("/seed", response_model=Message)
def seed_sources(_: User = Depends(require_admin), db: Session = Depends(get_db)) -> Message:
    """Insert the starter catalogue. Existing slugs are left untouched."""
    added = 0
    for entry in SEED_SOURCES:
        if db.scalar(select(Source).where(Source.slug == entry["slug"])):
            continue
        adapter = get_adapter(entry["adapter"])
        db.add(
            Source(
                slug=entry["slug"],
                name=entry["name"],
                kind=entry["kind"],
                adapter=entry["adapter"],
                base_url=entry.get("base_url"),
                config=entry.get("config", {}),
                enabled=entry.get("enabled", True),
                requires_credentials=(
                    adapter.requires_credentials
                    if adapter
                    else entry.get("requires_credentials", False)
                ),
            )
        )
        added += 1
    db.flush()
    return Message(
        detail=f"Seeded {added} new source(s); {len(SEED_SOURCES) - added} already present."
    )


@router.post("/{source_id}/run")
async def run_one(
    source_id: uuid.UUID,
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    """Run a single source synchronously — useful when tuning selectors."""
    source = db.get(Source, source_id)
    if source is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Source not found")
    report = await run_source(db, source)
    return report.as_dict()


def _run_all_in_background() -> None:
    import asyncio

    db = SessionLocal()
    try:
        asyncio.run(run_all_sources(db))
    finally:
        db.close()


@router.post("/run-all", response_model=Message)
def run_all(
    background: BackgroundTasks,
    _: User = Depends(require_admin),
) -> Message:
    """Kick off a full crawl. Returns immediately; watch each source's last_run_status."""
    background.add_task(_run_all_in_background)
    return Message(detail="Ingestion run started in the background.")
