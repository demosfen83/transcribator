from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .errors import LocalTranscriberError
from .transcriber import TranscriptionOptions, transcribe_file

SUPPORTED_FORMATS = {"md", "json", "srt"}


def parse_formats(value: str) -> set[str]:
    formats = {item.strip().lower() for item in value.split(",") if item.strip()}
    unknown = formats - SUPPORTED_FORMATS
    if unknown:
        raise ValueError(
            "Неизвестный формат: "
            + ", ".join(sorted(unknown))
            + ". Доступны: md,json,srt"
        )
    if not formats:
        raise ValueError("Нужно указать хотя бы один формат: md,json,srt")
    return formats


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="local-transcriber",
        description="Локальная транскрибация видео и аудио через faster-whisper.",
    )
    parser.add_argument("input", help="Путь до локального видео или аудио файла.")
    parser.add_argument(
        "--out",
        default="./output",
        help="Корневая папка для результата. Внутри будет создана папка с именем файла.",
    )
    parser.add_argument("--language", default="ru", help="Язык распознавания.")
    parser.add_argument("--model", default="large-v3-turbo", help="Имя или путь к модели.")
    parser.add_argument(
        "--device",
        choices=("auto", "cuda", "cpu"),
        default="auto",
        help="Устройство для faster-whisper.",
    )
    parser.add_argument(
        "--compute-type",
        default="auto",
        help="Тип вычислений, например int8_float16 для CUDA или int8 для CPU.",
    )
    parser.add_argument(
        "--offline",
        action="store_true",
        help="Использовать только локально доступные файлы модели.",
    )
    parser.add_argument("--initial-prompt", help="Подсказка для Whisper.")
    parser.add_argument(
        "--formats",
        default="md,json,srt",
        help="Список форматов через запятую: md,json,srt.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        formats = parse_formats(args.formats)
        options = TranscriptionOptions(
            input_path=Path(args.input),
            output_root=Path(args.out),
            language=args.language,
            model=args.model,
            device=args.device,
            compute_type=args.compute_type,
            offline=args.offline,
            initial_prompt=args.initial_prompt,
            formats=formats,
        )
        result = transcribe_file(options, progress=_print_progress)
    except ValueError as exc:
        parser.error(str(exc))
        return 2
    except LocalTranscriberError as exc:
        print(f"Ошибка: {exc}", file=sys.stderr)
        return 1

    print("")
    print("Готово. Созданные файлы:")
    for path in result.written_files:
        print(f"- {path.resolve()}")
    return 0


def _print_progress(segment: dict) -> None:
    print(
        f"{segment['start_ts']} - {segment['end_ts']} {segment['text']}",
        flush=True,
    )
