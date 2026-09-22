"""Send email as the signed-in user, from their own mailbox.

Google: Gmail API users.messages.send (scope gmail.send). The message lands in the
user's Sent folder and is DKIM-signed by their domain, which is what actually gets
a cold email to an admissions office delivered.

Microsoft: Graph /me/sendMail (scope Mail.Send).
"""

import base64
from dataclasses import dataclass
from email.message import EmailMessage

import httpx

from app.core.config import settings
from app.core.crypto import cipher
from app.models import OAuthAccount

GMAIL_SEND_SCOPE = "https://www.googleapis.com/auth/gmail.send"
GRAPH_SEND_SCOPES = {"Mail.Send", "https://graph.microsoft.com/Mail.Send"}


class MailSendError(Exception):
    pass


@dataclass
class SendResult:
    provider: str
    message_id: str | None
    thread_id: str | None


def _build_mime(
    from_email: str,
    from_name: str | None,
    to_email: str,
    subject: str,
    body: str,
    cc: list[str] | None = None,
) -> EmailMessage:
    message = EmailMessage()
    message["From"] = f"{from_name} <{from_email}>" if from_name else from_email
    message["To"] = to_email
    if cc:
        message["Cc"] = ", ".join(cc)
    message["Subject"] = subject
    message.set_content(body)
    return message


async def _refresh_google_access_token(refresh_token: str) -> str:
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post(
            "https://oauth2.googleapis.com/token",
            data={
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
            },
        )
    if response.status_code != 200:
        raise MailSendError(f"Google token refresh failed: {response.text}")
    return response.json()["access_token"]


async def _refresh_microsoft_access_token(refresh_token: str) -> str:
    url = f"https://login.microsoftonline.com/{settings.microsoft_tenant_id}/oauth2/v2.0/token"
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post(
            url,
            data={
                "client_id": settings.microsoft_client_id,
                "client_secret": settings.microsoft_client_secret,
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
                "scope": "offline_access Mail.Send",
            },
        )
    if response.status_code != 200:
        raise MailSendError(f"Microsoft token refresh failed: {response.text}")
    return response.json()["access_token"]


def account_can_send(account: OAuthAccount) -> bool:
    if account.refresh_token_encrypted is None:
        return False
    scopes = set(account.scopes or [])
    if account.provider == "google":
        return GMAIL_SEND_SCOPE in scopes
    if account.provider in {"microsoft", "azure-ad", "microsoft-entra-id"}:
        return bool(GRAPH_SEND_SCOPES & scopes)
    return False


def pick_sending_account(accounts: list[OAuthAccount]) -> OAuthAccount | None:
    """Prefer Google, then Microsoft. LinkedIn can never send mail."""
    ranked = sorted(
        (a for a in accounts if account_can_send(a)),
        key=lambda a: 0 if a.provider == "google" else 1,
    )
    return ranked[0] if ranked else None


async def send_as_user(
    account: OAuthAccount,
    from_email: str,
    from_name: str | None,
    to_email: str,
    subject: str,
    body: str,
    cc: list[str] | None = None,
) -> SendResult:
    refresh_token = cipher.decrypt(account.refresh_token_encrypted)
    if not refresh_token:
        raise MailSendError(
            "No usable refresh token on file. Ask the user to reconnect their mailbox."
        )

    message = _build_mime(from_email, from_name, to_email, subject, body, cc)

    if account.provider == "google":
        access_token = await _refresh_google_access_token(refresh_token)
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                "https://gmail.googleapis.com/gmail/v1/users/me/messages/send",
                headers={"Authorization": f"Bearer {access_token}"},
                json={"raw": raw},
            )
        if response.status_code >= 400:
            raise MailSendError(f"Gmail send failed ({response.status_code}): {response.text}")
        data = response.json()
        return SendResult("google", data.get("id"), data.get("threadId"))

    if account.provider in {"microsoft", "azure-ad", "microsoft-entra-id"}:
        access_token = await _refresh_microsoft_access_token(refresh_token)
        payload = {
            "message": {
                "subject": subject,
                "body": {"contentType": "Text", "content": body},
                "toRecipients": [{"emailAddress": {"address": to_email}}],
                "ccRecipients": [{"emailAddress": {"address": c}} for c in (cc or [])],
            },
            "saveToSentItems": True,
        }
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                "https://graph.microsoft.com/v1.0/me/sendMail",
                headers={"Authorization": f"Bearer {access_token}"},
                json=payload,
            )
        if response.status_code >= 400:
            raise MailSendError(f"Graph sendMail failed ({response.status_code}): {response.text}")
        # Graph returns 202 with no body and no message id.
        return SendResult("microsoft", None, None)

    raise MailSendError(f"Provider '{account.provider}' cannot send mail.")
