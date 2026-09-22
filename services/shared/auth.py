"""Identity at the service boundary.

Every service verifies the same Auth.js-minted HS256 token, so no service has to
call core-api just to learn who the caller is. Internal endpoints additionally
require a shared service token, because they are not safe to expose to a browser.
"""

import hmac
from collections.abc import Callable

from fastapi import Depends, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from pydantic import BaseModel, EmailStr

from shared.config import BaseServiceSettings

bearer_scheme = HTTPBearer(auto_error=False)


class Principal(BaseModel):
    """The authenticated end user, as asserted by the Auth.js token."""

    subject: str
    email: EmailStr
    name: str | None = None

    @property
    def user_key(self) -> str:
        """Stable per-user partition key.

        Email, not `sub`: the subject differs between Google and LinkedIn for the
        same person, and core-api already treats email as the account identity.
        Getting this wrong would split one user's documents across two silos.
        """
        return self.email.lower()


def build_auth_dependency(settings: BaseServiceSettings) -> Callable[..., Principal]:
    def get_principal(
        credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    ) -> Principal:
        if credentials is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing bearer token",
                headers={"WWW-Authenticate": "Bearer"},
            )
        try:
            payload = jwt.decode(
                credentials.credentials,
                settings.auth_jwt_secret,
                algorithms=[settings.auth_jwt_algorithm],
                audience=settings.auth_jwt_audience,
                issuer=settings.auth_jwt_issuer,
            )
        except JWTError as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"Invalid token: {exc}",
                headers={"WWW-Authenticate": "Bearer"},
            ) from exc

        email = payload.get("email")
        if not email:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="Token carries no email claim"
            )
        return Principal(
            subject=str(payload.get("sub") or email),
            email=email,
            name=payload.get("name"),
        )

    return get_principal


def build_internal_dependency(settings: BaseServiceSettings) -> Callable[..., bool]:
    def require_internal(x_internal_token: str | None = Header(default=None)) -> bool:
        expected = settings.internal_service_token
        if not expected:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="INTERNAL_SERVICE_TOKEN is not configured; internal routes are closed.",
            )
        # Constant-time compare: this token gates cross-user document access.
        if not x_internal_token or not hmac.compare_digest(x_internal_token, expected):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="Invalid internal service token"
            )
        return True

    return require_internal
