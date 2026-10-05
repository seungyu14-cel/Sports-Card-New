from __future__ import annotations

import argparse
import os
import sys
from datetime import date
from pathlib import Path

from openai import OpenAI
from pydantic import ValidationError

from .config import load_settings
from .generator import GenerationError
from .ingest import SportsIngestor
from .newsroom import GameNewsroom
from .pipeline import render_file, run_daily, validate_file
from .supabase_store import (
    SupabaseConfigurationError,
    SupabaseRequestError,
    SupabaseStore,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sports-card-news",
        description="사람 승인형 스포츠 카드뉴스 자동화 + Supabase 경기별 TOP3 뉴스룸",
    )
    parser.add_argument("--config", default="config/settings.toml", help="TOML 설정 파일")
    commands = parser.add_subparsers(dest="command", required=True)

    daily = commands.add_parser("daily", help="오늘의 카드뉴스 초안 생성")
    daily.add_argument("--date", default=date.today().isoformat(), help="편집일 YYYY-MM-DD")
    daily.add_argument("--output", default="output", help="출력 루트")
    daily.add_argument("--fixture", help="API 대신 사용할 package.json")

    validate = commands.add_parser("validate", help="package.json 검증")
    validate.add_argument("package", help="검증할 package.json")

    render = commands.add_parser("render", help="검증된 package.json을 PNG로 렌더링")
    render.add_argument("package", help="렌더링할 package.json")
    render.add_argument("--output", required=True, help="PNG 출력 디렉터리")

    ingest = commands.add_parser("ingest-json", help="정규화된 스포츠 JSON을 Supabase에 적재")
    ingest.add_argument("path", help="teams/games/stats/sources가 담긴 JSON")

    scrape = commands.add_parser("scrape-source", help="공식 원문 HTML을 텍스트로 수집")
    scrape.add_argument("--url", required=True)
    scrape.add_argument("--league", required=True)
    scrape.add_argument("--game-id")
    scrape.add_argument("--source-type", default="official")
    scrape.add_argument("--verified", action="store_true")

    game_news = commands.add_parser(
        "game-news",
        help="Supabase 종료 경기 전체에서 경기별 TOP3 뉴스를 생성",
    )
    game_news.add_argument("--date", default=date.today().isoformat())
    game_news.add_argument("--league", action="append", dest="leagues")
    game_news.add_argument("--game-id")
    game_news.add_argument("--output", help="구조화 JSON 출력 디렉터리")

    commands.add_parser("newsroom-status", help="Supabase 뉴스룸 연결 확인")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        settings = load_settings(args.config)

        if args.command == "daily":
            edition_date = date.fromisoformat(args.date)
            destination, report = run_daily(
                edition_date=edition_date,
                output_root=args.output,
                settings=settings,
                fixture=args.fixture,
            )
            print(f"생성 완료: {destination}")
            if report.warnings:
                print(f"사람 확인 경고: {len(report.warnings)}건")
            return 0

        if args.command == "validate":
            report = validate_file(args.package, settings)
            print(report.as_markdown())
            return 0 if report.ok else 1

        if args.command == "render":
            paths = render_file(args.package, args.output, settings)
            print(f"렌더링 완료: {len(paths)}장 → {Path(args.output)}")
            return 0

        if args.command == "newsroom-status":
            store = SupabaseStore.from_env()
            store.healthcheck()
            print("Supabase 뉴스룸 연결 정상")
            return 0

        if args.command == "ingest-json":
            store = SupabaseStore.from_env()
            client = OpenAI() if os.getenv("OPENAI_API_KEY") else None
            ingestor = SportsIngestor(
                store,
                trusted_domains=settings.trusted_domains,
                openai_client=client,
            )
            counts = ingestor.ingest_json_file(args.path)
            print("적재 완료: " + ", ".join(f"{key}={value}" for key, value in counts.items()))
            return 0

        if args.command == "scrape-source":
            store = SupabaseStore.from_env()
            client = OpenAI() if os.getenv("OPENAI_API_KEY") else None
            ingestor = SportsIngestor(
                store,
                trusted_domains=settings.trusted_domains,
                openai_client=client,
            )
            row = ingestor.scrape_url(
                url=args.url,
                league=args.league,
                game_id=args.game_id,
                source_type=args.source_type,
                verified=args.verified,
            )
            print(f"원문 저장 완료: {row.get('source_key', args.url)}")
            return 0

        if args.command == "game-news":
            if not os.getenv("OPENAI_API_KEY"):
                raise GenerationError("game-news에는 OPENAI_API_KEY가 필요합니다.")
            store = SupabaseStore.from_env()
            newsroom = GameNewsroom(
                store,
                model=os.getenv("OPENAI_NEWS_MODEL", "gpt-6.1-sol"),
                trusted_domains=settings.trusted_domains,
                reasoning_effort=settings.reasoning_effort,
            )
            edition_date = date.fromisoformat(args.date)
            output_dir = args.output or settings.structured_data_dir
            reports = newsroom.generate_for_date(
                edition_date,
                leagues=args.leagues or list(settings.leagues),
                game_id=args.game_id,
                output_dir=output_dir,
            )
            print(f"경기별 TOP3 생성 완료: {len(reports)}경기 → {output_dir}")
            return 0

    except (
        GenerationError,
        ValidationError,
        ValueError,
        FileNotFoundError,
        OSError,
        SupabaseConfigurationError,
        SupabaseRequestError,
    ) as error:
        print(f"오류: {error}", file=sys.stderr)
        return 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
