import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.api.deps import get_current_user, require_admin
from app.core.db import get_db
from app.core.enums import UserRole
from app.models import Profile, User, UserPreference
from app.schemas.common import Message, Page
from app.schemas.user import (
    MentorCard,
    MeRead,
    OnboardingPayload,
    PreferenceRead,
    PreferenceUpdate,
    ProfileRead,
    ProfileUpdate,
    UserRead,
)
from app.services.notifications import unread_count
from app.services.providers import pick_sending_account

router = APIRouter(tags=["users"])


def _me_payload(db: Session, user: User) -> MeRead:
    return MeRead(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        avatar_url=user.avatar_url,
        role=UserRole(user.role),
        onboarding_completed=user.onboarding_completed,
        created_at=user.created_at,
        profile=ProfileRead.model_validate(user.profile) if user.profile else None,
        preference=PreferenceRead.model_validate(user.preference) if user.preference else None,
        can_send_email_as_self=pick_sending_account(list(user.accounts)) is not None,
        unread_notifications=unread_count(db, user.id),
    )


@router.get("/users/me", response_model=MeRead)
def read_me(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> MeRead:
    return _me_payload(db, user)


@router.post("/users/me/onboarding", response_model=MeRead)
def complete_onboarding(
    payload: OnboardingPayload,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> MeRead:
    """The 'what are you looking for?' step right after first sign-in."""
    preference = user.preference or UserPreference(user_id=user.id)
    preference.opportunity_types = payload.opportunity_types
    preference.fields_of_study = payload.fields_of_study
    preference.degree_levels = payload.degree_levels
    preference.countries = payload.countries
    preference.regions = payload.regions
    preference.funding_types = payload.funding_types
    preference.email_digest = payload.email_digest
    user.preference = preference

    profile = user.profile or Profile(user_id=user.id)
    profile.fields_of_study = payload.fields_of_study
    if payload.headline:
        profile.headline = payload.headline
    if payload.country:
        profile.country = payload.country
    if payload.current_institution:
        profile.current_institution = payload.current_institution
    if payload.join_as_mentor:
        profile.is_mentor = True
        profile.years_experience = payload.years_experience
        profile.expertise = payload.expertise or payload.fields_of_study
        # Admins keep their elevated role; students become mentors.
        if user.role == UserRole.STUDENT:
            user.role = UserRole.MENTOR
    user.profile = profile

    # A profile picture is required to finish setup: contacts and mentors are
    # far likelier to answer someone whose profile looks like a real person.
    avatar = (payload.avatar_url or "").strip()
    if not avatar and not user.avatar_url:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "A profile picture is required. Your provider did not return one, "
                "so paste a link to a photo of yourself."
            ),
        )
    if avatar:
        user.avatar_url = avatar

    user.onboarding_completed = True
    db.flush()
    return _me_payload(db, user)


@router.get("/users/me/profile", response_model=ProfileRead)
def read_my_profile(user: User = Depends(get_current_user)) -> ProfileRead:
    if user.profile is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No profile")
    return ProfileRead.model_validate(user.profile)


@router.put("/users/me/profile", response_model=ProfileRead)
def update_my_profile(
    payload: ProfileUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ProfileRead:
    profile = user.profile or Profile(user_id=user.id)
    data = payload.model_dump(exclude_unset=True)

    avatar = data.pop("avatar_url", None)
    if avatar is not None:
        cleaned = avatar.strip()
        if not cleaned:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="A profile picture is required; it cannot be cleared.",
            )
        user.avatar_url = cleaned

    for key, value in data.items():
        setattr(profile, key, value)
    user.profile = profile

    if profile.is_mentor and user.role == UserRole.STUDENT:
        user.role = UserRole.MENTOR

    db.flush()
    return ProfileRead.model_validate(profile)


@router.put("/users/me/preferences", response_model=PreferenceRead)
def update_my_preferences(
    payload: PreferenceUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PreferenceRead:
    preference = user.preference or UserPreference(user_id=user.id)
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(preference, key, value)
    user.preference = preference
    db.flush()
    return PreferenceRead.model_validate(preference)


@router.get("/mentors", response_model=Page[MentorCard])
def list_mentors(
    q: str | None = None,
    expertise: list[str] = Query(default=[]),
    country: str | None = None,
    accepting_only: bool = True,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Page[MentorCard]:
    query = (
        select(User, Profile)
        .join(Profile, Profile.user_id == User.id)
        .where(Profile.is_mentor.is_(True), User.is_active.is_(True))
    )
    if accepting_only:
        query = query.where(Profile.mentor_is_accepting.is_(True))
    if expertise:
        query = query.where(Profile.expertise.overlap(expertise))
    if country:
        query = query.where(Profile.country == country)
    if q:
        pattern = f"%{q}%"
        query = query.where(
            User.full_name.ilike(pattern)
            | Profile.headline.ilike(pattern)
            | Profile.current_institution.ilike(pattern)
            | Profile.mentor_bio.ilike(pattern)
        )

    rows = db.execute(query).all()
    total = len(rows)
    window = rows[(page - 1) * page_size : page * page_size]

    items = [
        MentorCard(
            user_id=user.id,
            full_name=user.full_name,
            avatar_url=user.avatar_url,
            headline=profile.headline,
            country=profile.country,
            current_institution=profile.current_institution,
            current_title=profile.current_title,
            years_experience=profile.years_experience,
            expertise=profile.expertise or [],
            mentor_bio=profile.mentor_bio,
            linkedin_url=profile.linkedin_url,
            mentor_is_accepting=profile.mentor_is_accepting,
        )
        for user, profile in window
    ]
    return Page(items=items, total=total, page=page, page_size=page_size)


@router.get("/users/{user_id}", response_model=UserRead)
def read_user(
    user_id: uuid.UUID,
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> UserRead:
    target = db.get(User, user_id)
    if target is None or not target.is_active:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return UserRead.model_validate(target)


@router.put("/admin/users/{user_id}/role", response_model=UserRead)
def set_user_role(
    user_id: uuid.UUID,
    role: UserRole,
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> UserRead:
    target = db.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    target.role = role
    db.flush()
    return UserRead.model_validate(target)


@router.get("/admin/users", response_model=Page[UserRead])
def list_users(
    q: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> Page[UserRead]:
    query = select(User).options(selectinload(User.profile)).order_by(User.created_at.desc())
    if q:
        pattern = f"%{q}%"
        query = query.where(User.email.ilike(pattern) | User.full_name.ilike(pattern))
    rows = list(db.scalars(query).all())
    window = rows[(page - 1) * page_size : page * page_size]
    return Page(
        items=[UserRead.model_validate(u) for u in window],
        total=len(rows),
        page=page,
        page_size=page_size,
    )


@router.delete("/users/me", response_model=Message)
def deactivate_me(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> Message:
    user.is_active = False
    db.flush()
    return Message(detail="Account deactivated.")
