from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

from .timecodes import format_srt_timestamp, format_timestamp


@dataclass(frozen=True)
class TranscriptPayload:
    source: str
    duration: float
    language: str | None
    language_probability: float | None
    segments: list[dict]


def write_outputs(
    payload: TranscriptPayload,
    output_dir: Path,
    formats: set[str],
) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    if "md" in formats:
        path = output_dir / "transcript.md"
        path.write_text(render_markdown(payload), encoding="utf-8")
        written.append(path)

    if "json" in formats:
        path = output_dir / "transcript_segments.json"
        path.write_text(
            json.dumps(asdict(payload), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        written.append(path)

    if "srt" in formats:
        path = output_dir / "transcript.srt"
        path.write_text(render_srt(payload.segments), encoding="utf-8")
        written.append(path)

    return written


def render_markdown(payload: TranscriptPayload) -> str:
    language_probability = (
        f"{payload.language_probability:.2f}"
        if payload.language_probability is not None
        else "unknown"
    )
    lines = [
        "# Транскрипт",
        "",
        f"- Источник: `{Path(payload.source).name}`",
        f"- Полный путь: `{payload.source}`",
        f"- Длительность: {format_timestamp(payload.duration)}",
        f"- Язык: {payload.language or 'unknown'} ({language_probability})",
        "",
        "## Сегменты",
        "",
    ]

    for segment in payload.segments:
        lines.append(
            f"**{segment['start_ts']} - {segment['end_ts']}** {segment['text']}"
        )
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def render_srt(segments: Iterable[dict]) -> str:
    blocks: list[str] = []
    for index, segment in enumerate(segments, start=1):
        blocks.append(
            "\n".join(
                [
                    str(index),
                    f"{format_srt_timestamp(segment['start'])} --> {format_srt_timestamp(segment['end'])}",
                    segment["text"],
                ]
            )
        )
    return "\n\n".join(blocks).rstrip() + "\n"
