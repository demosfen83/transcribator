from __future__ import annotations

import inspect
import threading
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .cli import SUPPORTED_FORMATS
from .errors import InputFileError, LocalTranscriberError
from .pyav_compat import install_pyav_metadata_errors_compat
from .transcriber import TranscriptionOptions, TranscriptionResult, transcribe_file

TranscriberCallable = Callable[..., TranscriptionResult]
DurationReader = Callable[[Path], float | None]


@dataclass
class WebJob:
    id: str
    options: TranscriptionOptions
    status: str = "queued"
    progress_segments: list[dict] = field(default_factory=list)
    duration: float | None = None
    error: str | None = None
    output_dir: Path | None = None
    written_files: list[Path] = field(default_factory=list)

    def to_dict(self) -> dict:
        latest = self.progress_segments[-1] if self.progress_segments else None
        latest_end = _latest_completed_second(self.progress_segments)
        percentage = _progress_percentage(latest_end, self.duration)
        if self.status == "done":
            percentage = 100

        return {
            "id": self.id,
            "status": self.status,
            "error": self.error,
            "progress": {
                "segments": len(self.progress_segments),
                "latest": latest,
                "latest_end": latest_end,
                "duration": self.duration,
                "percentage": percentage,
            },
            "output_dir": str(self.output_dir) if self.output_dir else None,
            "files": [
                {
                    "name": path.name,
                    "path": str(path),
                    "url": f"/api/jobs/{self.id}/files/{path.name}",
                }
                for path in self.written_files
            ],
        }


class WebJobManager:
    def __init__(
        self,
        *,
        transcriber: TranscriberCallable = transcribe_file,
        duration_reader: DurationReader = None,
        run_async: bool = True,
    ) -> None:
        self._transcriber = transcriber
        self._duration_reader = duration_reader or read_media_duration
        self._run_async = run_async
        self._jobs: dict[str, WebJob] = {}
        self._lock = threading.Lock()

    def create_job(
        self,
        *,
        input_path: Path,
        output_root: Path,
        language: str,
        model: str,
        device: str,
        compute_type: str | None,
        offline: bool,
        initial_prompt: str | None,
        formats: set[str],
    ) -> WebJob:
        input_path = input_path.expanduser().resolve()
        if not input_path.exists() or not input_path.is_file():
            raise InputFileError(f"Входной файл не найден: {input_path}")

        unknown_formats = formats - SUPPORTED_FORMATS
        if unknown_formats:
            raise ValueError("Неизвестный формат: " + ", ".join(sorted(unknown_formats)))
        if not formats:
            raise ValueError("Нужно указать хотя бы один формат")

        options = TranscriptionOptions(
            input_path=input_path,
            output_root=output_root,
            language=language,
            model=model,
            device=device,
            compute_type=compute_type,
            offline=offline,
            initial_prompt=initial_prompt,
            formats=formats,
        )
        job = WebJob(
            id=uuid.uuid4().hex,
            options=options,
            duration=self._duration_reader(input_path),
        )
        with self._lock:
            self._jobs[job.id] = job

        if self._run_async:
            thread = threading.Thread(target=self._run_job, args=(job,), daemon=True)
            thread.start()
        else:
            self._run_job(job)
        return job

    def get_job(self, job_id: str) -> WebJob | None:
        with self._lock:
            return self._jobs.get(job_id)

    def _run_job(self, job: WebJob) -> None:
        self._set_job(job, status="running", error=None)
        try:
            result = self._call_transcriber(job)
        except LocalTranscriberError as exc:
            self._set_job(job, status="failed", error=str(exc))
            return
        except Exception as exc:
            self._set_job(job, status="failed", error=f"Неожиданная ошибка: {exc}")
            return

        self._set_job(
            job,
            status="done",
            duration=result.payload.duration or job.duration,
            output_dir=result.output_dir,
            written_files=result.written_files,
        )

    def _add_progress(self, job: WebJob, segment: dict) -> None:
        with self._lock:
            job.progress_segments.append(segment)

    def _set_metadata(self, job: WebJob, event: dict) -> None:
        duration = event.get("duration")
        if duration:
            self._set_job(job, duration=float(duration))

    def _set_job(self, job: WebJob, **changes) -> None:
        with self._lock:
            for key, value in changes.items():
                setattr(job, key, value)

    def _call_transcriber(self, job: WebJob) -> TranscriptionResult:
        kwargs = {
            "progress": lambda segment: self._add_progress(job, segment),
        }
        if _accepts_keyword(self._transcriber, "metadata"):
            kwargs["metadata"] = lambda event: self._set_metadata(job, event)
        return self._transcriber(job.options, **kwargs)


def read_media_duration(input_path: Path) -> float | None:
    try:
        install_pyav_metadata_errors_compat()
        import av
    except Exception:
        return None

    try:
        with av.open(str(input_path), mode="r") as container:
            if container.duration:
                return float(container.duration * av.time_base)

            stream_durations = [
                float(stream.duration * stream.time_base)
                for stream in container.streams
                if stream.duration and stream.time_base
            ]
            if stream_durations:
                return max(stream_durations)
    except Exception:
        return None

    return None


def _progress_percentage(latest_end: float | None, duration: float | None) -> int | None:
    if latest_end is None or duration is None or duration <= 0:
        return None
    return max(0, min(99, round((latest_end / duration) * 100)))


def _latest_completed_second(segments: list[dict]) -> float | None:
    ends = []
    for segment in segments:
        try:
            ends.append(float(segment["end"]))
        except (KeyError, TypeError, ValueError):
            continue
    if not ends:
        return None
    return max(ends)


def _accepts_keyword(func: TranscriberCallable, name: str) -> bool:
    try:
        signature = inspect.signature(func)
    except (TypeError, ValueError):
        return False
    return name in signature.parameters or any(
        parameter.kind == inspect.Parameter.VAR_KEYWORD
        for parameter in signature.parameters.values()
    )
