from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Protocol

from .errors import (
    CudaUnavailableError,
    InputFileError,
    MediaReadError,
    ModelLoadError,
    OutputDirectoryError,
)
from .formatters import TranscriptPayload, write_outputs
from .pyav_compat import install_pyav_metadata_errors_compat
from .timecodes import format_timestamp


class WhisperModelProtocol(Protocol):
    def transcribe(self, input_path: str, **kwargs):
        ...


@dataclass(frozen=True)
class TranscriptionOptions:
    input_path: Path
    output_root: Path
    language: str
    model: str
    device: str
    compute_type: str | None
    offline: bool
    initial_prompt: str | None
    formats: set[str]


@dataclass(frozen=True)
class TranscriptionResult:
    output_dir: Path
    written_files: list[Path]
    segments: list[dict]
    payload: TranscriptPayload


ProgressCallback = Callable[[dict], None]
MetadataCallback = Callable[[dict], None]


def transcribe_file(
    options: TranscriptionOptions,
    *,
    model_cls=None,
    progress: ProgressCallback | None = None,
    metadata: MetadataCallback | None = None,
) -> TranscriptionResult:
    input_path = options.input_path.expanduser().resolve()
    if not input_path.exists() or not input_path.is_file():
        raise InputFileError(f"Входной файл не найден: {input_path}")

    output_dir = options.output_root.expanduser().resolve() / input_path.stem

    device = _resolve_device(options.device)
    compute_type = _resolve_compute_type(device, options.compute_type)
    model = _load_model(
        options.model,
        device=device,
        compute_type=compute_type,
        offline=options.offline,
        model_cls=model_cls,
    )
    install_pyav_metadata_errors_compat()

    try:
        segments_iter, info = model.transcribe(
            str(input_path),
            language=options.language,
            task="transcribe",
            vad_filter=True,
            vad_parameters={
                "min_silence_duration_ms": 450,
                "speech_pad_ms": 250,
            },
            beam_size=5,
            best_of=5,
            temperature=0.0,
            condition_on_previous_text=True,
            initial_prompt=options.initial_prompt,
        )
        duration = float(getattr(info, "duration", 0.0) or 0.0)
        if metadata is not None:
            metadata({"duration": duration})
        segments = _collect_segments(segments_iter, progress)
    except Exception as exc:
        raise MediaReadError(
            f"Не удалось прочитать или транскрибировать файл `{input_path}`: {exc}"
        ) from exc

    payload = TranscriptPayload(
        source=str(input_path),
        duration=duration,
        language=getattr(info, "language", None),
        language_probability=getattr(info, "language_probability", None),
        segments=segments,
    )

    try:
        written_files = write_outputs(payload, output_dir, options.formats)
    except OSError as exc:
        raise OutputDirectoryError(
            f"Не удалось записать результаты в `{output_dir}`: {exc}"
        ) from exc

    return TranscriptionResult(
        output_dir=output_dir,
        written_files=written_files,
        segments=segments,
        payload=payload,
    )


def _load_model(
    model_name_or_path: str,
    *,
    device: str,
    compute_type: str,
    offline: bool,
    model_cls=None,
) -> WhisperModelProtocol:
    if device == "cuda" and not _cuda_available():
        raise CudaUnavailableError(
            "Выбран --device cuda, но CUDA не обнаружена. "
            "Запустите с --device cpu --compute-type int8 или проверьте драйверы CUDA."
        )

    if model_cls is None:
        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:
            raise ModelLoadError(
                "Пакет faster-whisper не установлен. Выполните: pip install -r requirements.txt"
            ) from exc
        model_cls = WhisperModel

    try:
        return model_cls(
            model_name_or_path,
            device=device,
            compute_type=compute_type,
            local_files_only=offline,
        )
    except Exception as exc:
        hint = (
            "Модель не найдена локально или недоступна в offline-режиме. "
            "Сначала скачайте ее, например: "
            "python -c \"from faster_whisper import WhisperModel; "
            "WhisperModel('large-v3-turbo')\""
            if offline
            else "Не удалось загрузить модель. Проверьте имя модели, путь и доступ к Hugging Face."
        )
        raise ModelLoadError(f"{hint}\nИсходная ошибка: {exc}") from exc


def _collect_segments(
    segments_iter: Iterable,
    progress: ProgressCallback | None,
) -> list[dict]:
    rows: list[dict] = []
    for fallback_id, segment in enumerate(segments_iter, start=1):
        row = {
            "id": int(getattr(segment, "id", fallback_id)),
            "start": float(segment.start),
            "end": float(segment.end),
            "start_ts": format_timestamp(segment.start),
            "end_ts": format_timestamp(segment.end),
            "text": (segment.text or "").strip(),
        }
        rows.append(row)
        if progress is not None:
            progress(row)
    return rows


def _resolve_device(device: str) -> str:
    if device not in {"auto", "cuda", "cpu"}:
        raise ValueError("device must be one of: auto, cuda, cpu")
    return device


def _resolve_compute_type(device: str, compute_type: str | None) -> str:
    if compute_type and compute_type != "auto":
        return compute_type
    if device == "cuda":
        return "int8_float16"
    if device == "cpu":
        return "int8"
    return "default"


def _ensure_output_dir(output_dir: Path) -> None:
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise OutputDirectoryError(
            f"Не удалось создать папку вывода `{output_dir}`: {exc}"
        ) from exc


def _cuda_available() -> bool:
    try:
        import torch

        return bool(torch.cuda.is_available())
    except Exception:
        pass

    try:
        import ctranslate2

        return ctranslate2.get_cuda_device_count() > 0
    except Exception:
        return False
