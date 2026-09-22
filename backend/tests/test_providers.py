from app.models import OAuthAccount
from app.services.providers import account_can_send, pick_sending_account

GMAIL = "https://www.googleapis.com/auth/gmail.send"


def make(provider: str, scopes: list[str], refresh: str | None = "enc") -> OAuthAccount:
    return OAuthAccount(
        provider=provider,
        provider_account_id="x",
        scopes=scopes,
        refresh_token_encrypted=refresh,
    )


def test_google_with_send_scope_can_send():
    assert account_can_send(make("google", [GMAIL])) is True


def test_google_without_send_scope_cannot():
    assert account_can_send(make("google", ["openid", "email"])) is False


def test_no_refresh_token_cannot_send():
    assert account_can_send(make("google", [GMAIL], refresh=None)) is False


def test_linkedin_can_never_send():
    assert account_can_send(make("linkedin", ["r_liteprofile", GMAIL])) is False


def test_google_is_preferred_over_microsoft():
    accounts = [make("microsoft", ["Mail.Send"]), make("google", [GMAIL])]
    chosen = pick_sending_account(accounts)
    assert chosen is not None and chosen.provider == "google"


def test_returns_none_when_nothing_can_send():
    assert pick_sending_account([make("linkedin", ["r_liteprofile"])]) is None
