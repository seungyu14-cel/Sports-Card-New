from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import threading
import uuid
import webbrowser
from dataclasses import asdict, dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Literal

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from openai import OpenAI
from pydantic import BaseModel, Field, SecretStr

from .config import Settings, load_settings
from .pipeline import load_package, run_daily


PACKAGE_ROOT = Path(__file__).resolve().parent
WEB_ROOT = PACKAGE_ROOT / "web"
EDITION_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class SaveSettingsRequest(BaseModel):
    api_key: SecretStr
    model: str = Field(min_length=2, max_length=100)


class CreateJobRequest(BaseModel):
    edition_date: date
    demo: bool = False


@dataclass
class JobRecord:
    id: str
    edition_date: str
    mode: Literal["live", "demo"]
    status: Literal["queued", "running", "completed", "failed"] = "queued"
    message: str = "생성 대기 중"
    created_at: str = ""
    finished_at: str | None = None
    result: dict[str, object] | None = None
    error: str | None = None


def create_app(project_root: str | Path | None = None) -> FastAPI:
    root = Path(project_root or Path.cwd()).resolve()
    config_path = root / "config" / "settings.toml"
    output_root = root / "output"
    fixture_path = root / "fixtures" / "demo_package.json"
    env_path = root / ".env"

    if not config_path.exists():
        raise RuntimeError(f"프로젝트 설정 파일을 찾을 수 없습니다: {config_path}")

    _load_local_env(env_path)
    settings = load_settings(config_path)
    output_root.mkdir(parents=True, exist_ok=True)

    app = FastAPI(
        title="Sports Card News Studio",
        version="0.6.0",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.project_root = root
    app.state.config_path = config_path
    app.state.output_root = output_root
    app.state.fixture_path = fixture_path
    app.state.env_path = env_path
    app.state.settings = settings
    app.state.api_verified = False
    app.state.jobs: dict[str, JobRecord] = {}
    app.state.job_lock = asyncio.Lock()
    app.state.tasks: set[asyncio.Task[None]] = set()

    app.mount("/assets", StaticFiles(directory=WEB_ROOT), name="assets")
    app.mount("/output", StaticFiles(directory=output_root, check_dir=False), name="output")

    @app.middleware("http")
    async def security_headers(request: Request, call_next):  # type: ignore[no-untyped-def]
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store" if request.url.path.startswith("/api/") else "no-cache"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; img-src 'self' data:; style-src 'self'; "
            "script-src 'self'; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'"
        )
        return response

    @app.exception_handler(Exception)
    async def unhandled_error(_request: Request, error: Exception) -> JSONResponse:
        return JSONResponse(status_code=500, content={"detail": _safe_error(error)})

    @app.get("/")
    async def index() -> FileResponse:
        return FileResponse(WEB_ROOT / "index.html")

    @app.get("/api/health")
    async def health() -> dict[str, object]:
        current = _refresh_settings(app)
        return {
            "status": "ready",
            "api_key_configured": bool(os.getenv("OPENAI_API_KEY")),
            "api_key_verified": app.state.api_verified,
            "model": current.model,
            "timezone": current.timezone,
            "edition_count": len(_list_editions(output_root)),
            "job_running": app.state.job_lock.locked(),
        }

    @app.post("/api/settings")
    async def save_settings(payload: SaveSettingsRequest) -> dict[str, object]:
        api_key = payload.api_key.get_secret_value().strip()
        if len(api_key) < 20 or any(char.isspace() for char in api_key):
            raise HTTPException(status_code=422, detail="API 키 형식이 올바르지 않습니다.")
        model = payload.model.strip()
        _save_local_env(
            env_path,
            {"OPENAI_API_KEY": api_key, "OPENAI_MODEL": model},
        )
        os.environ["OPENAI_API_KEY"] = api_key
        os.environ["OPENAI_MODEL"] = model
        current = _refresh_settings(app)
        app.state.api_verified = False
        return {"saved": True, "api_key_configured": True, "model": current.model}

    @app.post("/api/settings/test")
    async def test_settings() -> dict[str, object]:
        key = os.getenv("OPENAI_API_KEY")
        if not key:
            raise HTTPException(status_code=409, detail="먼저 API 키를 저장하세요.")
        try:
            await asyncio.to_thread(_test_openai_connection, key)
        except Exception as error:
            app.state.api_verified = False
            raise HTTPException(status_code=502, detail=_safe_error(error)) from error
        app.state.api_verified = True
        return {"valid": True, "message": "OpenAI API 연결을 확인했습니다."}

    @app.post("/api/jobs", status_code=202)
    async def create_job(payload: CreateJobRequest) -> dict[str, object]:
        if app.state.job_lock.locked():
            raise HTTPException(status_code=409, detail="이미 생성 작업이 진행 중입니다.")
        if not payload.demo and not os.getenv("OPENAI_API_KEY"):
            raise HTTPException(status_code=409, detail="라이브 생성 전에 OpenAI API 키를 저장하세요.")
        if not payload.demo and not app.state.api_verified:
            raise HTTPException(status_code=409, detail="라이브 생성 전에 API 연결 확인을 완료하세요.")
        if payload.demo and not fixture_path.exists():
            raise HTTPException(status_code=500, detail="데모 입력 파일을 찾을 수 없습니다.")

        job_id = uuid.uuid4().hex[:12]
        record = JobRecord(
            id=job_id,
            edition_date=payload.edition_date.isoformat(),
            mode="demo" if payload.demo else "live",
            created_at=datetime.now().astimezone().isoformat(timespec="seconds"),
        )
        app.state.jobs[job_id] = record
        task = asyncio.create_task(_run_generation_job(app, record))
        app.state.tasks.add(task)
        task.add_done_callback(app.state.tasks.discard)
        return _job_payload(record)

    @app.get("/api/jobs/{job_id}")
    async def get_job(job_id: str) -> dict[str, object]:
        record = app.state.jobs.get(job_id)
        if record is None:
            raise HTTPException(status_code=404, detail="작업을 찾을 수 없습니다.")
        return _job_payload(record)

    @app.get("/api/editions")
    async def editions() -> dict[str, object]:
        return {"items": _list_editions(output_root)}

    @app.get("/api/editions/{edition_date}")
    async def edition(edition_date: str) -> dict[str, object]:
        if not EDITION_PATTERN.fullmatch(edition_date):
            raise HTTPException(status_code=422, detail="편집일 형식이 올바르지 않습니다.")
        return _edition_detail(output_root, edition_date)

    return app


async def _run_generation_job(app: FastAPI, record: JobRecord) -> None:
    async with app.state.job_lock:
        record.status = "running"
        record.message = "공식 출처 조사와 카드 제작을 진행 중입니다."
        try:
            settings = _refresh_settings(app)
            destination, report = await asyncio.to_thread(
                run_daily,
                date.fromisoformat(record.edition_date),
                app.state.output_root,
                settings,
                app.state.fixture_path if record.mode == "demo" else None,
            )
            detail = _edition_detail(app.state.output_root, record.edition_date)
            detail["warnings"] = report.warnings
            record.result = detail
            record.status = "completed"
            record.message = f"카드 {len(list(destination.glob('card-*.png')))}장 생성 완료"
        except Exception as error:
            record.status = "failed"
            record.message = "생성 작업에 실패했습니다."
            record.error = _safe_error(error)
        finally:
            record.finished_at = datetime.now().astimezone().isoformat(timespec="seconds")


def _refresh_settings(app: FastAPI) -> Settings:
    _load_local_env(app.state.env_path)
    settings = load_settings(app.state.config_path)
    app.state.settings = settings
    return settings


def _list_editions(output_root: Path) -> list[dict[str, object]]:
    items: list[dict[str, object]] = []
    for package_path in sorted(output_root.glob("*/package.json"), reverse=True):
        try:
            package = load_package(package_path)
            selected = next(
                item for item in package.candidates if item.title == package.selected_candidate_title
            )
        except (OSError, ValueError, StopIteration):
            continue
        edition_date = package.edition_date
        items.append(
            {
                "edition_date": edition_date,
                "title": package.selected_candidate_title,
                "sport": selected.sport,
                "league": selected.league,
                "card_count": len(package.cards),
                "cover_url": f"/output/{edition_date}/card-01.png",
                "needs_human_approval": package.needs_human_approval,
            }
        )
    return items


def _edition_detail(output_root: Path, edition_date: str) -> dict[str, object]:
    package_path = output_root / edition_date / "package.json"
    if not package_path.exists():
        raise HTTPException(status_code=404, detail="해당 날짜의 생성물을 찾을 수 없습니다.")
    package = load_package(package_path)
    selected = next(item for item in package.candidates if item.title == package.selected_candidate_title)
    return {
        "edition_date": package.edition_date,
        "title": package.selected_candidate_title,
        "sport": selected.sport,
        "league": selected.league,
        "selection_reason": package.selection_reason,
        "caption": package.caption,
        "hashtags": package.hashtags,
        "approval_notice": package.approval_notice,
        "cards": [
            {
                "slide": card.slide,
                "headline": card.headline,
                "body": card.body,
                "alt_text": card.alt_text,
                "image_url": f"/output/{edition_date}/card-{card.slide:02d}.png",
            }
            for card in package.cards
        ],
        "facts": [
            {
                "id": fact.id,
                "claim": fact.claim,
                "title": fact.title,
                "url": str(fact.url),
                "status": fact.status.value,
            }
            for fact in package.facts
        ],
        "risk_flags": package.risk_flags,
    }


def _job_payload(record: JobRecord) -> dict[str, object]:
    return asdict(record)


def _load_local_env(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key.strip() in {"OPENAI_API_KEY", "OPENAI_MODEL", "CARD_NEWS_FONT"}:
            os.environ[key.strip()] = value.strip().strip('"').strip("'")


def _save_local_env(
    path: Path,
    updates: dict[str, str],
    *,
    remove: set[str] | None = None,
) -> None:
    values: dict[str, str] = {}
    if path.exists():
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            if "=" in raw_line and not raw_line.lstrip().startswith("#"):
                key, value = raw_line.split("=", 1)
                values[key.strip()] = value.strip()
    for key in remove or set():
        values.pop(key, None)
    values.update(updates)
    content = "# 로컬 전용 비밀 설정. GitHub에 커밋하지 마세요.\n"
    content += "\n".join(f"{key}={value}" for key, value in values.items()) + "\n"
    temp_path = path.with_suffix(".tmp")
    temp_path.write_text(content, encoding="utf-8", newline="\n")
    temp_path.replace(path)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def _test_openai_connection(api_key: str) -> None:
    client = OpenAI(api_key=api_key, timeout=20.0, max_retries=0)
    client.models.list()


def _safe_error(error: Exception) -> str:
    message = str(error)
    lowered = message.lower()
    if any(token in lowered for token in ("invalid_api_key", "incorrect api key", "unauthorized")):
        return "API 키가 유효하지 않습니다. OpenAI에서 발급한 새 키를 입력하세요."
    configured_key = os.getenv("OPENAI_API_KEY")
    if configured_key:
        message = message.replace(configured_key, "[REDACTED]")
    message = re.sub(r"sk-[A-Za-z0-9_*\-\s]{8,}", "[REDACTED]", message)
    return message[:500] or error.__class__.__name__


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="스포츠 카드뉴스 로컬 웹 앱")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--open-browser", action="store_true")
    args = parser.parse_args(argv)
    if not 1024 <= args.port <= 65535:
        parser.error("포트는 1024~65535 범위여야 합니다.")
    if args.open_browser:
        threading.Timer(1.2, lambda: webbrowser.open(f"http://127.0.0.1:{args.port}")).start()
    uvicorn.run(create_app(), host="127.0.0.1", port=args.port, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
