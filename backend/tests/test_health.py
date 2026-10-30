"""Health check and static frontend mounting."""

from fastapi.testclient import TestClient

from app.main import create_app

client = TestClient(create_app())


def test_health_reports_process_up() -> None:
    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_api_remains_available_when_frontend_is_mounted(tmp_path) -> None:
    (tmp_path / "index.html").write_text(
        "<!doctype html><title>ABC Prediction Platform</title>",
        encoding="utf-8",
    )
    mounted = TestClient(create_app(frontend_dist=tmp_path))

    page = mounted.get("/")
    assert page.status_code == 200
    assert "ABC Prediction Platform" in page.text

    health = mounted.get("/api/health")
    assert health.status_code == 200
    assert health.json() == {"status": "ok"}

    login = mounted.post(
        "/api/login",
        json={"email": "reader@example.com", "password": "not-a-real-secret"},
    )
    assert login.status_code == 200
    assert login.json()["authenticated"] is False
