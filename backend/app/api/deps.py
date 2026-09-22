from collections.abc import Callable
from datetime import UTC, datetime

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.enums import UserRole
from app.core.security import TokenClaims, TokenVerificationError, verify_token
from app.models import Profile, User, UserPreference

bearer_scheme = HTTPBearer(auto_error=False)


def get_claims(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> TokenClaims:
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        return verify_token(credentials.credentials)
    except TokenVerificationError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid token: {exc}",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


def get_current_user(
    claims: TokenClaims = Depends(get_claims),
    db: Session = Depends(get_db),
) -> User:
    """Resolve the signed-in user, provisioning on first sight.

    Auth.js has already verified the identity with Google/LinkedIn, so a valid
    token for an unknown email means a brand-new signup.
    """
    email = claims.email.lower()
    user = db.scalar(select(User).where(User.email == email))

    if user is None:
        user = User(
            email=email,
            full_name=claims.name,
            avatar_url=claims.picture,
            role=UserRole.STUDENT,
        )
        user.profile = Profile(fields_of_study=[], expertise=[])
        user.preference = UserPreference()
        db.add(user)
        db.flush()
    else:
        if claims.name and not user.full_name:
            user.full_name = claims.name
        if claims.picture and not user.avatar_url:
            user.avatar_url = claims.picture
        if user.profile is None:
            user.profile = Profile(fields_of_study=[], expertise=[])
        if user.preference is None:
            user.preference = UserPreference()

    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account is disabled")

    user.last_login_at = datetime.now(UTC)
    db.flush()
    return user


def require_roles(*roles: UserRole) -> Callable[[User], User]:
    allowed = {str(r) for r in roles}

    def _dependency(user: User = Depends(get_current_user)) -> User:
        if user.role not in allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Requires one of: {', '.join(sorted(allowed))}",
            )
        return user

    return _dependency


require_contributor = require_roles(UserRole.MENTOR, UserRole.ADMIN)
require_admin = require_roles(UserRole.ADMIN)
