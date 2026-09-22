"""Live immigration headlines for the Counsel rail."""

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, HttpUrl

from app.api.deps import get_current_user
from app.models import User
from app.services import immigration_news

router = APIRouter(prefix="/news", tags=["news"])


class NewsItem(BaseModel):
    title: str
    url: HttpUrl
    summary: str | None = None
    source: str
    region: str
    published_at: str | None = None


class NewsFeed(BaseModel):
    items: list[NewsItem]


@router.get("/immigration", response_model=NewsFeed)
async def immigration_headlines(
    limit: int = Query(12, ge=1, le=24),
    _user: User = Depends(get_current_user),
) -> NewsFeed:
    items = await immigration_news.latest(limit=limit)
    return NewsFeed(items=[NewsItem(**item) for item in items])
