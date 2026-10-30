"""Contract for the temporary mock login endpoint."""

from fastapi.testclient import TestClient

from app.main import create_app

client = TestClient(create_app())


def test_mock_login_does_not_authenticate() -> None:
    password = "not-a-real-secret"
    response = client.post(
        "/api/login",
        json={"email": "reader@example.com", "password": password},
    )

    assert response.status_code == 200
    body = response.json()
    assert body == {
        "temporary": True,
        "authenticated": False,
        "message": "This login is temporary and mocked. No account was authenticated.",
    }
    assert "token" not in body
    assert "set-cookie" not in response.headers
    assert password not in response.text


def test_mock_login_rejects_invalid_input() -> None:
    response = client.post(
        "/api/login",
        json={"email": "not-an-email", "password": ""},
    )

    assert response.status_code == 422
    assert response.json().get("temporary") is None
    assert response.json().get("authenticated") is None
