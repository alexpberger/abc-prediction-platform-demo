"""Temporary login stand-in. This does not authenticate anyone."""

TEMPORARY_LOGIN_MESSAGE = (
    "This login is temporary and mocked. No account was authenticated."
)


def temporary_mock_login() -> dict[str, object]:
    """Return a fixed mock result. The caller must not pass the password here."""
    return {
        "temporary": True,
        "authenticated": False,
        "message": TEMPORARY_LOGIN_MESSAGE,
    }
