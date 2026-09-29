from __future__ import annotations

import shutil
import time
from pathlib import Path

from fastapi.testclient import TestClient

from sports_card_news.webapp import _safe_error, _test_openrouter_connection, create_app


ROOT = Path(__file__).parents[1]


def make_project(tmp_path: Path) -> Path:
    (tmp_path / "config").mkdir()
    (tmp_path / "fixtures").mkdir()
    (tmp_path / "output").mkdir()
    shutil.copy2(ROOT / "config/settings.toml", tmp_path / "config/settings.toml")
    shutil.copy2(ROOT / "fixtures/demo_package.json", tmp_path / "fixtures/demo_package.json")
    return tmp_path


def test_health_does_not_expose_api_key(tmp_path: Path, monkeypatch) -> None:
    project = make_project(tmp_path)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    with TestClient(create_app(project)) as client:
        response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["api_key_configured"] is False
    assert response.json()["api_key_verified"] is False
    assert "sk-" not in response.text.lower()


def test_settings_are_saved_locally_and_redacted(tmp_path: Path, monkeypatch) -> None:
    project = make_project(tmp_path)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    secret = "sk-or-v1-test-123456789012345678901234"
    with TestClient(create_app(project)) as client:
        response = client.post(
            "/api/settings",
            json={"api_key": secret, "model": "openai/gpt-5.2"},
        )
    assert response.status_code == 200
    assert secret not in response.text
    env_text = (project / ".env").read_text(encoding="utf-8")
    assert f"OPENROUTER_API_KEY={secret}" in env_text
    assert "OPENAI_API_KEY" not in env_text


def test_demo_job_generates_cards_and_api_detail(tmp_path: Path, monkeypatch) -> None:
    project = make_project(tmp_path)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    with TestClient(create_app(project)) as client:
        created = client.post(
            "/api/jobs",
            json={"edition_date": "2026-09-29", "demo": True},
        )
        assert created.status_code == 202
        job_id = created.json()["id"]
        job = created.json()
        for _ in range(50):
            job = client.get(f"/api/jobs/{job_id}").json()
            if job["status"] in {"completed", "failed"}:
                break
            time.sleep(0.05)
        assert job["status"] == "completed", job
        detail = client.get("/api/editions/2026-09-29")
        assert detail.status_code == 200
        assert len(detail.json()["cards"]) == 6
        image = client.get("/output/2026-09-29/card-01.png")
        assert image.status_code == 200
        assert image.headers["content-type"] == "image/png"


def test_frontend_is_served(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    with TestClient(create_app(project)) as client:
        response = client.get("/")
    assert response.status_code == 200
    assert "SPORTS CARD" in response.text


def test_live_job_requires_verified_key(tmp_path: Path, monkeypatch) -> None:
    project = make_project(tmp_path)
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-v1-test-123456789012345678901234")
    with TestClient(create_app(project)) as client:
        response = client.post(
            "/api/jobs",
            json={"edition_date": "2026-09-29", "demo": False},
        )
    assert response.status_code == 409
    assert "연결 확인" in response.json()["detail"]


def test_invalid_key_error_is_fully_redacted(monkeypatch) -> None:
    key = "sk-or-v1-secret-value-1234567890"
    monkeypatch.setenv("OPENROUTER_API_KEY", key)
    message = _safe_error(Exception(f"Unauthorized: {key}; user not found"))
    assert "sk-" not in message
    assert "secret" not in message
    assert "OpenRouter" in message


def test_openrouter_key_check_uses_authenticated_key_endpoint(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {"data": {"label": "test"}}

    def fake_get(url: str, **kwargs: object) -> FakeResponse:
        captured["url"] = url
        captured.update(kwargs)
        return FakeResponse()

    monkeypatch.setattr("sports_card_news.webapp.httpx.get", fake_get)
    _test_openrouter_connection("sk-or-v1-test-secret")

    assert captured["url"] == "https://openrouter.ai/api/v1/key"
    headers = captured["headers"]
    assert isinstance(headers, dict)
    assert headers["Authorization"] == "Bearer sk-or-v1-test-secret"
