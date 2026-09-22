"""Platform-sent transactional email (notifications, digests).

This is distinct from outreach: outreach goes out from the *user's own* mailbox
via their OAuth grant (see providers.py).
"""

import smtplib
from email.message import EmailMessage

import structlog

from app.core.config import settings

log = structlog.get_logger(__name__)


def send_platform_email(
    to_email: str,
    subject: str,
    text_body: str,
    html_body: str | None = None,
) -> bool:
    message = EmailMessage()
    message["From"] = f"{settings.notification_from_name} <{settings.notification_from_email}>"
    message["To"] = to_email
    message["Subject"] = subject
    message.set_content(text_body)
    if html_body:
        message.add_alternative(html_body, subtype="html")

    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as smtp:
            if settings.smtp_use_tls:
                smtp.starttls()
            if settings.smtp_user:
                smtp.login(settings.smtp_user, settings.smtp_password)
            smtp.send_message(message)
        return True
    except Exception as exc:
        log.warning("platform_email_failed", to=to_email, subject=subject, error=str(exc))
        return False


def render_notification_email(title: str, body: str | None, link: str | None) -> tuple[str, str]:
    text = title
    if body:
        text += f"\n\n{body}"
    if link:
        text += f"\n\nOpen: {link}"
    text += "\n\n--\nGradPortal · manage email preferences in your profile settings."

    link_html = (
        f'<p><a href="{link}" style="background:#1f6feb;color:#fff;padding:10px 18px;'
        f'border-radius:6px;text-decoration:none;display:inline-block">View in GradPortal</a></p>'
        if link
        else ""
    )
    html = f"""<!doctype html>
<html><body style="font-family:system-ui,-apple-system,Segoe UI,sans-serif;background:#f6f8fa;padding:24px">
  <div style="max-width:560px;margin:0 auto;background:#fff;border-radius:10px;padding:28px;border:1px solid #e5e7eb">
    <h2 style="margin:0 0 12px;font-size:18px;color:#111827">{title}</h2>
    <p style="margin:0 0 18px;color:#374151;line-height:1.55;white-space:pre-wrap">{body or ""}</p>
    {link_html}
    <hr style="border:0;border-top:1px solid #e5e7eb;margin:24px 0 12px">
    <p style="margin:0;font-size:12px;color:#6b7280">
      GradPortal · manage email preferences in your profile settings.
    </p>
  </div>
</body></html>"""
    return text, html
