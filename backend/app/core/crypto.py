"""Symmetric encryption for OAuth refresh tokens stored in the database.

Refresh tokens let us send mail as the user indefinitely, so they never sit in
plaintext. Rotating TOKEN_ENCRYPTION_KEY invalidates stored tokens and forces a
re-consent, which is the intended failure mode.
"""

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings


class TokenCipher:
    def __init__(self, key: str) -> None:
        self._fernet = Fernet(key.encode()) if key else None

    @property
    def enabled(self) -> bool:
        return self._fernet is not None

    def encrypt(self, value: str | None) -> str | None:
        if value is None:
            return None
        if self._fernet is None:
            raise RuntimeError(
                "TOKEN_ENCRYPTION_KEY is not set; refusing to store an OAuth token in plaintext."
            )
        return self._fernet.encrypt(value.encode()).decode()

    def decrypt(self, value: str | None) -> str | None:
        if value is None or self._fernet is None:
            return None
        try:
            return self._fernet.decrypt(value.encode()).decode()
        except InvalidToken:
            return None


cipher = TokenCipher(settings.token_encryption_key)
