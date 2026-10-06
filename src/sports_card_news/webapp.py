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
from .feedback_memory import FeedbackMemory
from .local_studio import LocalStudioRequest, OllamaClient, local_category_info, run_local_studio
from .studio import (
    StudioPackage,
    StudioRequest,
    active_agents,
    load_studio_package,
    public_agents,
    public_themes,
    run_studio,
)
from .supabase_store import SupabaseStore


PACKAGE_ROOT = Path(__file__).resolve().parent
WEB_ROOT = PACKAGE_ROOT / "web"
EDITION_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")
SESSION_PATTERN = re.compile(r"^[A-Za-z0-9_-]{6,40}$")


class SaveSettingsRequest(BaseModel):
    api_key: SecretStr
    model: str = Field(min_length=2, max_length=100)


class CreateJobRequest(BaseModel):
    edition_date: date
    demo: bool = False


class CreateLocalStudioJobRequest(BaseModel):
    edition_date: date
    category: Literal["KBO", "NPB", "MLB", "KBL", "NBA", "EPL", "V-LEAGUE"]
    topic: str = Field(min_length=2, max_length=200)
    markdown_text: str = Field(min_length=20, max_length=120000)
    source_name: str = Field(default="uploaded.md", max_length=180)
    editorial_instruction: str = Field(default="", max_length=8000)
    save_feedback_memory: bool = True
    page_count: Literal[7, 10] = 10


class CreateStudioJobRequest(BaseModel):
    edition_date: date
    sport: Literal["야구", "농구", "축구", "배구", "기타"]
    league: str = Field(min_length=1, max_length=40)
    topic: str = Field(min_length=2, max_length=200)
    source_notes: str = Field(default="", max_length=12000)
    theme_id: str = Field(min_length=2, max_length=60)
    archive_to_db: bool = True
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


@dataclass
class StudioJobRecord:
    id: str
    edition_date: str
    mode: Literal["live", "demo", "local"]
    status: Literal["queued", "running", "completed", "failed"] = "queued"
    stage: str = "queued"
    percent: int = 0
    message: str = "편집국 작업 대기 중"
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
    memory_path = root / "data" / "feedback_memory.sqlite3"

    if not config_path.exists():
        raise RuntimeError(f"프로젝트 설정 파일을 찾을 수 없습니다: {config_path}")

    _load_local_env(env_path)
    settings = load_settings(config_path)
    output_root.mkdir(parents=True, exist_ok=True)

    app = FastAPI(
        title="스포츠 데일리 카드 뉴스 제작소",
        version="2.0.0",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.project_root = root
    app.state.config_path = config_path
    app.state.output_root = output_root
    app.state.fixture_path = fixture_path
    app.state.env_path = env_path
    app.state.memory_path = memory_path
    app.state.settings = settings
    app.state.api_verified = False
    app.state.jobs: dict[str, JobRecord] = {}
    app.state.studio_jobs: dict[str, StudioJobRecord] = {}
    app.state.job_lock = asyncio.Lock()
    app.state.studio_lock = asyncio.Lock()
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
            "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
            "script-src 'self'; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'"
        )
        return response

    @app.exception_handler(Exception)
    async def unhandled_error(_request: Request, error: Exception) -> JSONResponse:
        return JSONResponse(status_code=500, content={"detail": _safe_error(error)})

    @app.get("/")
    async def index() -> FileResponse:
        return FileResponse(WEB_ROOT / "index.html")

    @app.get("/local")
    async def local_index() -> FileResponse:
        return FileResponse(WEB_ROOT / "local.html")

    @app.get("/api/health")
    async def health() -> dict[str, object]:
        current = _refresh_settings(app)
        return {
            "status": "ready",
            "api_key_configured": bool(os.getenv("OPENAI_API_KEY")),
            "api_key_verified": app.state.api_verified,
            "model": current.model,
            "studio_model": os.getenv("OPENAI_STUDIO_MODEL", "gpt-6.1-sol"),
            "timezone": current.timezone,
            "supabase_configured": SupabaseStore.is_configured(),
            "edition_count": len(_list_editions(output_root)),
            "studio_session_count": len(_list_studio_sessions(output_root)),
            "job_running": app.state.job_lock.locked() or app.state.studio_lock.locked(),
        }

    @app.post("/api/settings")
    async def save_settings(payload: SaveSettingsRequest) -> dict[str, object]:
        api_key = payload.api_key.get_secret_value().strip()
        if len(api_key) < 20 or any(char.isspace() for char in api_key):
            raise HTTPException(status_code=422, detail="API 키 형식이 올바르지 않습니다.")
        model = payload.model.strip()
        _save_local_env(env_path, {"OPENAI_API_KEY": api_key, "OPENAI_MODEL": model})
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

    # Legacy 5-card flow remains available.
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

    # New editorial newsroom studio.
    @app.get("/api/local/health")
    async def local_health() -> dict[str, object]:
        memory = FeedbackMemory(app.state.memory_path)
        try:
            ollama = await asyncio.to_thread(OllamaClient().health)
        except Exception as error:
            ollama = {
                "reachable": False,
                "model": os.getenv("OLLAMA_MODEL", "qwen3:8b"),
                "model_installed": False,
                "models": [],
                "error": _safe_error(error),
            }
        return {"ollama": ollama, "memory": memory.stats()}

    @app.get("/api/local/category/{category}")
    async def local_category(category: str) -> dict[str, object]:
        try:
            return local_category_info(category)
        except (KeyError, ValueError) as error:
            raise HTTPException(status_code=404, detail=str(error)) from error

    @app.post("/api/local/jobs", status_code=202)
    async def create_local_job(payload: CreateLocalStudioJobRequest) -> dict[str, object]:
        if app.state.studio_lock.locked():
            raise HTTPException(status_code=409, detail="편집국 제작 작업이 이미 진행 중입니다.")
        try:
            health = await asyncio.to_thread(OllamaClient().health)
        except Exception as error:
            raise HTTPException(
                status_code=503,
                detail="Ollama에 연결할 수 없습니다. ollama serve 실행 상태를 확인하세요.",
            ) from error
        if not health.get("model_installed"):
            raise HTTPException(
                status_code=409,
                detail=f"Ollama 모델 {health.get('model')}이 설치되지 않았습니다. ollama pull 명령으로 설치하세요.",
            )
        job_id = uuid.uuid4().hex[:12]
        record = StudioJobRecord(
            id=job_id,
            edition_date=payload.edition_date.isoformat(),
            mode="local",
            created_at=datetime.now().astimezone().isoformat(timespec="seconds"),
        )
        app.state.studio_jobs[job_id] = record
        task = asyncio.create_task(_run_local_studio_job(app, record, payload))
        app.state.tasks.add(task)
        task.add_done_callback(app.state.tasks.discard)
        return asdict(record)

    @app.get("/api/studio/agents")
    async def studio_agents() -> dict[str, object]:
        return {"items": public_agents()}

    @app.get("/api/studio/themes")
    async def studio_themes() -> dict[str, object]:
        return {"items": public_themes()}

    @app.get("/api/studio/active-agents")
    async def studio_active_agents(sport: str, league: str) -> dict[str, object]:
        return {"items": [item.model_dump(mode="json") for item in active_agents(sport, league)]}

    @app.post("/api/studio/jobs", status_code=202)
    async def create_studio_job(payload: CreateStudioJobRequest) -> dict[str, object]:
        if app.state.studio_lock.locked():
            raise HTTPException(status_code=409, detail="편집국 제작 작업이 이미 진행 중입니다.")
        if not payload.demo and not os.getenv("OPENAI_API_KEY"):
            raise HTTPException(status_code=409, detail="라이브 제작 전에 OpenAI API 키를 저장하세요.")
        if not payload.demo and not app.state.api_verified:
            raise HTTPException(status_code=409, detail="라이브 제작 전에 API 연결 확인을 완료하세요.")
        job_id = uuid.uuid4().hex[:12]
        record = StudioJobRecord(
            id=job_id,
            edition_date=payload.edition_date.isoformat(),
            mode="demo" if payload.demo else "live",
            created_at=datetime.now().astimezone().isoformat(timespec="seconds"),
        )
        app.state.studio_jobs[job_id] = record
        task = asyncio.create_task(_run_studio_job(app, record, payload))
        app.state.tasks.add(task)
        task.add_done_callback(app.state.tasks.discard)
        return asdict(record)

    @app.get("/api/studio/jobs/{job_id}")
    async def get_studio_job(job_id: str) -> dict[str, object]:
        record = app.state.studio_jobs.get(job_id)
        if record is None:
            raise HTTPException(status_code=404, detail="편집국 작업을 찾을 수 없습니다.")
        return asdict(record)

    @app.get("/api/studio/sessions")
    async def studio_sessions() -> dict[str, object]:
        return {"items": _list_studio_sessions(output_root)}

    @app.get("/api/studio/sessions/{session_id}")
    async def studio_session(session_id: str) -> dict[str, object]:
        if not SESSION_PATTERN.fullmatch(session_id):
            raise HTTPException(status_code=422, detail="세션 ID 형식이 올바르지 않습니다.")
        return _studio_detail(output_root, session_id)

    from .work_hub import work_router
    app.include_router(work_router(output_root, root / 'data' / 'work_operations.sqlite3', WEB_ROOT))
    from .autopublish import auto_router
    app.include_router(auto_router(output_root, root / 'data' / 'work_operations.sqlite3'))
    return app


async def _run_local_studio_job(
    app: FastAPI,
    record: StudioJobRecord,
    payload: CreateLocalStudioJobRequest,
) -> None:
    async with app.state.studio_lock:
        record.status = "running"
        record.stage = "research"
        record.percent = 8
        record.message = "MD 원문과 Feedback Memory를 불러오고 있습니다."

        def progress(stage: str, percent: int, message: str) -> None:
            record.stage = stage
            record.percent = percent
            record.message = message

        try:
            request = LocalStudioRequest(
                edition_date=payload.edition_date,
                category=payload.category,
                topic=payload.topic,
                markdown_text=payload.markdown_text,
                source_name=payload.source_name,
                editorial_instruction=payload.editorial_instruction,
                save_feedback_memory=payload.save_feedback_memory,
                page_count=payload.page_count,
            )
            destination, package = await asyncio.to_thread(
                run_local_studio,
                request,
                output_root=app.state.output_root,
                memory_path=app.state.memory_path,
                progress=progress,
            )
            record.result = _studio_package_payload(package, destination)
            record.status = "completed"
            record.stage = "complete"
            record.percent = 100
            record.message = f"MD 기반 {payload.page_count}페이지 카드뉴스와 Work 전달 파일 생성 완료"
        except Exception as error:
            record.status = "failed"
            record.stage = "failed"
            record.percent = 100
            record.message = "로컬 편집국 제작에 실패했습니다."
            record.error = _safe_error(error)
        finally:
            record.finished_at = datetime.now().astimezone().isoformat(timespec="seconds")


async def _run_studio_job(
    app: FastAPI,
    record: StudioJobRecord,
    payload: CreateStudioJobRequest,
) -> None:
    async with app.state.studio_lock:
        record.status = "running"
        record.stage = "research"
        record.percent = 8
        record.message = "AI 편집국이 제작 브리프를 확인하고 있습니다."

        def progress(stage: str, percent: int, message: str) -> None:
            record.stage = stage
            record.percent = percent
            record.message = message

        try:
            settings = _refresh_settings(app)
            request = StudioRequest(
                edition_date=payload.edition_date,
                sport=payload.sport,
                league=payload.league,
                topic=payload.topic,
                source_notes=payload.source_notes,
                theme_id=payload.theme_id,
                archive_to_db=payload.archive_to_db,
            )
            destination, package = await asyncio.to_thread(
                run_studio,
                request,
                output_root=app.state.output_root,
                settings=settings,
                demo=payload.demo,
                progress=progress,
            )
            record.result = _studio_package_payload(package, destination)
            record.status = "completed"
            record.stage = "complete"
            record.percent = 100
            record.message = "카드뉴스 원고·디자인·SNS·직원별 피드백 생성 완료"
        except Exception as error:
            record.status = "failed"
            record.stage = "failed"
            record.percent = 100
            record.message = "편집국 제작 작업에 실패했습니다."
            record.error = _safe_error(error)
        finally:
            record.finished_at = datetime.now().astimezone().isoformat(timespec="seconds")


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


def _list_studio_sessions(output_root: Path) -> list[dict[str, object]]:
    root = output_root / "studio"
    items: list[dict[str, object]] = []
    if not root.exists():
        return items
    for package_path in sorted(root.glob("*/studio-package.json"), reverse=True):
        try:
            package = load_studio_package(package_path)
        except (OSError, ValueError):
            continue
        items.append(
            {
                "session_id": package.session_id,
                "edition_date": package.edition_date,
                "sport": package.sport,
                "league": package.league,
                "topic": package.topic,
                "title": package.master_headline,
                "theme": package.theme.model_dump(mode="json"),
                "score": package.overall_score,
                "cover_url": f"/output/studio/{package.session_id}/card-01.png",
                "needs_human_approval": package.needs_human_approval,
            }
        )
    return items


def _studio_detail(output_root: Path, session_id: str) -> dict[str, object]:
    package_path = output_root / "studio" / session_id / "studio-package.json"
    if not package_path.exists():
        raise HTTPException(status_code=404, detail="해당 제작 세션을 찾을 수 없습니다.")
    package = load_studio_package(package_path)
    return _studio_package_payload(package, package_path.parent)


def _studio_package_payload(package: StudioPackage, destination: Path) -> dict[str, object]:
    return {
        **package.model_dump(mode="json"),
        "cards": [
            {
                **card.model_dump(mode="json"),
                "image_url": f"/output/studio/{package.session_id}/card-{card.slide:02d}.png",
            }
            for card in package.cards
        ],
        "caption_file": f"/output/studio/{package.session_id}/caption-instagram.md",
    }


def _list_editions(output_root: Path) -> list[dict[str, object]]:
    items: list[dict[str, object]] = []
    for package_path in sorted(output_root.glob("*/package.json"), reverse=True):
        try:
            package = load_package(package_path)
            selected = next(item for item in package.candidates if item.title == package.selected_candidate_title)
        except (OSError, ValueError, StopIteration):
            continue
        items.append(
            {
                "edition_date": package.edition_date,
                "title": package.selected_candidate_title,
                "sport": selected.sport,
                "league": selected.league,
                "card_count": len(package.cards),
                "cover_url": f"/output/{package.edition_date}/card-01.png",
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
                "league": card.league.value,
                "headline": card.headline,
                "body": card.body,
                "visual_title": card.visual_title,
                "visual_items": [item.model_dump() for item in card.visual_items],
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
                "verification_method": fact.verification_method.value,
                "checked_at": fact.checked_at.isoformat(),
                "expires_at": fact.expires_at.isoformat() if fact.expires_at else None,
                "evidence": fact.evidence,
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
    allowed = {
        "CANVA_ACCESS_TOKEN", "METRICOOL_API_TOKEN", "METRICOOL_USER_ID", "METRICOOL_BLOG_ID",
        "OPENAI_API_KEY",
        "OPENAI_MODEL",
        "OPENAI_STUDIO_MODEL",
        "OPENAI_NEWS_MODEL",
        "OPENAI_EMBEDDING_MODEL",
        "SUPABASE_URL",
        "SUPABASE_SERVICE_ROLE_KEY",
        "CARD_NEWS_FONT",
        "CARD_NEWS_BOLD_FONT",
    }
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key.strip() in allowed:
            os.environ[key.strip()] = value.strip().strip('"').strip("'")


def _save_local_env(path: Path, updates: dict[str, str], *, remove: set[str] | None = None) -> None:
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
    for key_name in ("OPENAI_API_KEY", "SUPABASE_SERVICE_ROLE_KEY"):
        configured = os.getenv(key_name)
        if configured:
            message = message.replace(configured, "[REDACTED]")
    message = re.sub(r"sk-[A-Za-z0-9_*\-\s]{8,}", "[REDACTED]", message)
    return message[:500] or error.__class__.__name__


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="스포츠 데일리 카드 뉴스 제작소")
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
