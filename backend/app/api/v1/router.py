from fastapi import APIRouter

from app.api.v1 import (
    auth,
    content,
    mentorship,
    notifications,
    opportunities,
    outreach,
    sources,
    users,
)

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(content.router)
api_router.include_router(content.admin_router)
api_router.include_router(users.router)
api_router.include_router(opportunities.router)
api_router.include_router(outreach.router)
api_router.include_router(notifications.router)
api_router.include_router(mentorship.router)
api_router.include_router(sources.router)
