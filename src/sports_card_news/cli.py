from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

from pydantic import ValidationError

from .config import load_settings
from .generator import GenerationError
from .pipeline import render_file, run_daily, validate_file


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sports-card-news",
        description="사람 승인형 멀티스포츠 인스타그램 카드뉴스 자동화",
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
    except (GenerationError, ValidationError, ValueError, FileNotFoundError, OSError) as error:
        print(f"오류: {error}", file=sys.stderr)
        return 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

