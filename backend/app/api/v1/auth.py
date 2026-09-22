from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_claims, get_current_user
from app.core.crypto import cipher
from app.core.db import get_db
from app.core.security import TokenClaims
from app.models import OAuthAccount, Profile, User
from app.schemas.common import Message
from app.schemas.user import ConnectionRead, ConnectionsRead, SessionSyncPayload
from app.services.providers import account_can_send, pick_sending_account

router = APIRouter(prefix="/auth", tags=["auth"])

# Locale is the only geographic hint OIDC gives us. It is a weak signal — a
# Ghanaian student's browser may well report en-GB — so it only ever fills a
# blank field and never overwrites what the user typed.
LOCALE_COUNTRIES = {
    "en-GB": "United Kingdom",
    "en-US": "United States",
    "en-CA": "Canada",
    "fr-CA": "Canada",
    "en-AU": "Australia",
    "en-NZ": "New Zealand",
    "en-IE": "Ireland",
    "de-DE": "Germany",
    "de-AT": "Austria",
    "de-CH": "Switzerland",
    "fr-FR": "France",
    "nl-NL": "Netherlands",
    "sv-SE": "Sweden",
    "da-DK": "Denmark",
    "nb-NO": "Norway",
    "fi-FI": "Finland",
    "es-ES": "Spain",
    "it-IT": "Italy",
    "pt-PT": "Portugal",
    "pl-PL": "Poland",
    "en-GH": "Ghana",
    "en-NG": "Nigeria",
    "en-KE": "Kenya",
    "en-ZA": "South Africa",
    "en-IN": "India",
}


def _apply_provider_profile(user: User, payload: SessionSyncPayload) -> None:
    """Seed the profile from the provider's OIDC claims.

    Only fills blanks. A user who has edited their profile must not have it
    silently reverted the next time they sign in.
    """
    claims = payload.provider_profile
    if claims is None:
        return

    if user.profile is None:
        user.profile = Profile(fields_of_study=[], expertise=[])

    profile = user.profile

    if not user.full_name:
        parts = [claims.given_name, claims.family_name]
        joined = " ".join(part for part in parts if part).strip()
        if joined:
            user.full_name = joined

    if claims.picture and not user.avatar_url:
        user.avatar_url = claims.picture

    if claims.locale and not profile.country:
        country = LOCALE_COUNTRIES.get(claims.locale) or LOCALE_COUNTRIES.get(
            claims.locale.replace("_", "-")
        )
        if country:
            profile.country = country



@router.post("/session/sync", response_model=Message)
def sync_session(
    payload: SessionSyncPayload,
    claims: TokenClaims = Depends(get_claims),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Message:
    """Called by the Next.js signIn callback after a successful OAuth grant.

    It carries the provider tokens, which the API stores encrypted so outreach can
    later be sent from the user's own mailbox.
    """
    if payload.email.lower() != claims.email.lower():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Payload email does not match the authenticated token.",
        )

    if payload.full_name and not user.full_name:
        user.full_name = payload.full_name
    if payload.avatar_url:
        user.avatar_url = payload.avatar_url

    _apply_provider_profile(user, payload)

    account_payload = payload.account
    if account_payload is None:
        return Message(detail="Session synced.")

    if not cipher.enabled and (account_payload.refresh_token or account_payload.access_token):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="TOKEN_ENCRYPTION_KEY is not configured; refusing to store OAuth tokens.",
        )

    account = db.scalar(
        select(OAuthAccount).where(
            OAuthAccount.provider == account_payload.provider,
            OAuthAccount.provider_account_id == account_payload.provider_account_id,
        )
    )
    if account is None:
        account = OAuthAccount(
            user_id=user.id,
            provider=account_payload.provider,
            provider_account_id=account_payload.provider_account_id,
        )
        db.add(account)

    account.user_id = user.id
    if account_payload.access_token:
        account.access_token_encrypted = cipher.encrypt(account_payload.access_token)
    # Google only returns a refresh token on first consent; never clobber a stored one.
    if account_payload.refresh_token:
        account.refresh_token_encrypted = cipher.encrypt(account_payload.refresh_token)
    account.expires_at = account_payload.expires_at
    if account_payload.scopes:
        account.scopes = account_payload.scopes

    db.flush()
    return Message(
        detail=(
            "Session synced; mailbox connected." if account_can_send(account) else "Session synced."
        )
    )


@router.get("/connections", response_model=ConnectionsRead)
def read_connections(
    user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> ConnectionsRead:
    """What is linked, and whether it can send mail.

    Exists because "sign-in worked" and "outreach will work" are different
    questions: Google only returns a refresh token on an explicit offline
    consent, so an account can authenticate perfectly and still be unable to
    send a single email. Without this the failure only surfaces when someone
    presses send on a message they have spent ten minutes writing.
    """
    accounts = list(user.accounts)
    sending = pick_sending_account(accounts)

    connections = []
    for account in accounts:
        has_refresh = account.refresh_token_encrypted is not None
        can_send = account_can_send(account)
        reason: str | None = None
        if not can_send:
            if account.provider == "dev":
                reason = (
                    "Development sign-in has no mailbox behind it. Sign in with "
                    "Google to send email."
                )
            elif account.provider == "linkedin":
                reason = "LinkedIn cannot send mail; it is an identity provider only."
            elif not has_refresh:
                reason = (
                    "No refresh token was returned. Google only issues one on an "
                    "explicit offline consent — sign out and sign back in."
                )
            else:
                reason = (
                    "The send scope was not granted. Re-authorise and accept the "
                    "permission to send email on your behalf."
                )

        connections.append(
            ConnectionRead(
                provider=account.provider,
                provider_account_id=account.provider_account_id,
                scopes=account.scopes or [],
                connected_at=account.created_at,
                expires_at=account.expires_at,
                has_refresh_token=has_refresh,
                can_send_mail=can_send,
                blocked_reason=reason,
            )
        )

    return ConnectionsRead(
        connections=sorted(connections, key=lambda c: c.provider),
        can_send_email_as_self=sending is not None,
        sending_provider=sending.provider if sending else None,
    )
