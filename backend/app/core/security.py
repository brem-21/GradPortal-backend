"""Verification of the API JWT that Auth.js (Next.js) mints for the browser session.

Auth.js owns the Google/LinkedIn OIDC dance. After a successful sign-in it signs a
compact HS256 token with the shared AUTH_JWT_SECRET and the frontend sends it as
`Authorization: Bearer <token>`. This module only verifies; it never issues.
"""

from datetime import UTC, datetime

from jose import JWTError, jwt
from pydantic import BaseModel, EmailStr

from app.core.config import settings


class TokenClaims(BaseModel):
    sub: str
    email: EmailStr
    name: str | None = None
    picture: str | None = None
    provider: str | None = None
    exp: int | None = None


class TokenVerificationError(Exception):
    pass


def verify_token(token: str) -> TokenClaims:
    try:
        payload = jwt.decode(
            token,
            settings.auth_jwt_secret,
            algorithms=[settings.auth_jwt_algorithm],
            audience=settings.auth_jwt_audience,
            issuer=settings.auth_jwt_issuer,
        )
    except JWTError as exc:
        raise TokenVerificationError(str(exc)) from exc

    exp = payload.get("exp")
    if exp is not None and datetime.now(UTC).timestamp() > exp:
        raise TokenVerificationError("token expired")

    try:
        return TokenClaims(**payload)
    except Exception as exc:  # pydantic validation
        raise TokenVerificationError(f"malformed claims: {exc}") from exc
