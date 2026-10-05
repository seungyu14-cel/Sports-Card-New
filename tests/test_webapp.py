from __future__ import annotations

import shutil
import time
from pathlib import Path

from fastapi.testclient import TestClient

from sports_card_news.webapp import _safe_error, _test_openai_connection, create_app


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
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with TestClient(create_app(project)) as client:
        response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["api_key_configured"] is False
    assert response.json()["api_key_verified"] is False
    assert "sk-" not in response.text.lower()


def test_settings_are_saved_locally_and_redacted(tmp_path: Path, monkeypatch) -> None:
    project = make_project(tmp_path)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    secret = "sk-proj-test-123456789012345678901234"
    with TestClient(create_app(project)) as client:
        response = client.post(
            "/api/settings",
            json={"api_key": secret, "model": "gpt-6-astra"},
        )
    assert response.status_code == 200
    assert secret not in response.text


def test_demo_job_generates_five_cards(tmp_path: Path, monkeypatch) -> None:
    project = make_project(tmp_path)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with TestClient(create_app(project)) as client:
        created = client.post(
            "/api/jobs",
            json={"edition_date": "2026-09-29", "demo": True},
        )
        assert created.status_code == 202
        job_id = created.json()["id"]
        job = created.json()
        for _ in range(80):
            job = client.get(f"/api/jobs/{job_id}").json()
            if job["status"] in {"completed", "failed"}:
                break
            time.sleep(0.05)
        assert job["status"] == "completed", job
        detail = client.get("/api/editions/2026-09-29")
        assert detail.status_code == 200
        assert len(detail.json()["cards"]) == 5
        image = client.get("/output/2026-09-29/card-05.png")
        assert image.status_code == 200


def test_frontend_is_served(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    with TestClient(create_app(project)) as client:
        response = client.get("/")
    assert response.status_code == 200
    assert "SPORTS CARD" in response.text


def test_live_job_requires_verified_key(tmp_path: Path, monkeypatch) -> None:
    project = make_project(tmp_path)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-proj-test-123456789012345678901234")
    with TestClient(create_app(project)) as client:
        response = client.post(
            "/api/jobs",
            json={"edition_date": "2026-09-29", "demo": False},
        )
    assert response.status_code == 409
    assert "연결 확인" in response.json()["detail"]


def test_invalid_key_error_is_fully_redacted(monkeypatch) -> None:
    key = "sk-proj-secret-value-1234567890"
    monkeypatch.setenv("OPENAI_API_KEY", key)
    message = _safe_error(Exception(f"Incorrect API key provided: {key}; invalid_api_key"))
    assert "sk-" not in message
    assert "secret" not in message
    assert "OpenAI" in message


def test_openai_key_check_lists_models(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeModels:
        def list(self) -> None:
            captured["listed"] = True

    class FakeOpenAI:
        def __init__(self, **kwargs: object) -> None:
            captured.update(kwargs)
            self.models = FakeModels()

    monkeypatch.setattr("sports_card_news.webapp.OpenAI", FakeOpenAI)
    _test_openai_connection("sk-proj-test-secret")

    assert captured["api_key"] == "sk-proj-test-secret"
    assert captured["listed"] is True



def test_studio_metadata_exposes_agents_and_sport_themes(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    with TestClient(create_app(project)) as client:
        agents = client.get("/api/studio/agents")
        themes = client.get("/api/studio/themes")

    assert agents.status_code == 200
    assert any(item["name"] == "김도윤" for item in agents.json()["items"])
    assert any(item["name"] == "윤서아" for item in agents.json()["items"])
    theme_map = {item["sport"]: item["primary"] for item in themes.json()["items"]}
    assert theme_map["야구"] == "#123F2F"
    assert theme_map["농구"] == "#8F3B12"
    assert theme_map["축구"] == "#6F1717"
    assert theme_map["배구"] == "#133E7C"


def test_studio_demo_job_generates_seven_cards_and_feedback(
    tmp_path: Path,
    monkeypatch,
) -> None:
    project = make_project(tmp_path)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)

    with TestClient(create_app(project)) as client:
        created = client.post(
            "/api/studio/jobs",
            json={
                "edition_date": "2026-10-05",
                "sport": "야구",
                "league": "KBO",
                "topic": "LG와 한화 경기 핵심 이슈",
                "source_notes": "",
                "theme_id": "baseball-green",
                "archive_to_db": True,
                "demo": True,
            },
        )
        assert created.status_code == 202
        job_id = created.json()["id"]
        job = created.json()
        for _ in range(100):
            job = client.get(f"/api/studio/jobs/{job_id}").json()
            if job["status"] in {"completed", "failed"}:
                break
            time.sleep(0.05)

        assert job["status"] == "completed", job
        result = job["result"]
        assert result["theme"]["id"] == "baseball-green"
        assert len(result["cards"]) == 7
        assert len(result["feedback"]) >= 8
        assert result["needs_human_approval"] is True

        session_id = result["session_id"]
        detail = client.get(f"/api/studio/sessions/{session_id}")
        assert detail.status_code == 200
        assert len(detail.json()["cards"]) == 7

        image = client.get(f"/output/studio/{session_id}/card-07.png")
        assert image.status_code == 200
