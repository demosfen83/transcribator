from __future__ import annotations

import argparse
from email import policy
from email.parser import BytesParser
import json
import mimetypes
import shutil
import uuid
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

from .errors import LocalTranscriberError
from .web_jobs import WebJobManager

DEFAULT_OUTPUT_ROOT = Path("./output")
STATIC_DIR = Path(__file__).resolve().parent / "web_static"


def open_browser(
    url: str,
    *,
    enabled: bool = True,
    opener=webbrowser.open,
) -> bool:
    if not enabled:
        return False
    return bool(opener(url))


def create_server(
    host: str = "127.0.0.1",
    port: int = 8765,
    *,
    manager: WebJobManager | None = None,
    static_dir: Path = STATIC_DIR,
) -> ThreadingHTTPServer:
    job_manager = manager or WebJobManager()

    class LocalTranscriberHandler(WebHandler):
        jobs = job_manager
        assets = static_dir

    return ThreadingHTTPServer((host, port), LocalTranscriberHandler)


class WebHandler(BaseHTTPRequestHandler):
    jobs: WebJobManager
    assets: Path

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/":
            self._serve_static("index.html")
            return

        if path.startswith("/static/"):
            self._serve_static(path.removeprefix("/static/"))
            return

        if path.startswith("/api/jobs/"):
            self._handle_job_get(path)
            return

        self._send_json({"error": "Не найдено"}, HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path != "/api/jobs":
            self._send_json({"error": "Не найдено"}, HTTPStatus.NOT_FOUND)
            return

        try:
            payload = self._read_job_payload()
            job = self.jobs.create_job(**payload)
        except (ValueError, LocalTranscriberError) as exc:
            self._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return
        except json.JSONDecodeError:
            self._send_json({"error": "Некорректный JSON"}, HTTPStatus.BAD_REQUEST)
            return

        self._send_json(job.to_dict(), HTTPStatus.CREATED)

    def log_message(self, format: str, *args) -> None:
        return

    def _handle_job_get(self, path: str) -> None:
        parts = [unquote(part) for part in path.strip("/").split("/")]
        if len(parts) < 3 or parts[0] != "api" or parts[1] != "jobs":
            self._send_json({"error": "Не найдено"}, HTTPStatus.NOT_FOUND)
            return

        job = self.jobs.get_job(parts[2])
        if job is None:
            self._send_json({"error": "Задача не найдена"}, HTTPStatus.NOT_FOUND)
            return

        if len(parts) == 3:
            self._send_json(job.to_dict())
            return

        if len(parts) == 5 and parts[3] == "files":
            self._serve_job_file(job, parts[4])
            return

        self._send_json({"error": "Не найдено"}, HTTPStatus.NOT_FOUND)

    def _serve_job_file(self, job, file_name: str) -> None:
        if job.status != "done":
            self._send_json({"error": "Файлы доступны после завершения задачи"}, HTTPStatus.CONFLICT)
            return

        for path in job.written_files:
            if path.name == file_name and path.exists():
                data = path.read_bytes()
                content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", content_type + "; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Content-Disposition", f'attachment; filename="{path.name}"')
                self.end_headers()
                self.wfile.write(data)
                return
        self._send_json({"error": "Файл не найден"}, HTTPStatus.NOT_FOUND)

    def _serve_static(self, relative_path: str) -> None:
        target = (self.assets / relative_path).resolve()
        assets_root = self.assets.resolve()
        if not str(target).startswith(str(assets_root)) or not target.exists() or not target.is_file():
            self._send_json({"error": "Файл не найден"}, HTTPStatus.NOT_FOUND)
            return

        data = target.read_bytes()
        content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type + "; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length") or "0")
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def _read_job_payload(self) -> dict:
        content_type = self.headers.get("Content-Type", "")
        if content_type.startswith("multipart/form-data"):
            return self._read_multipart_job_payload(content_type)

        payload = self._read_json()
        return {
            "input_path": Path(payload.get("input_path") or ""),
            "output_root": Path(payload.get("output_root") or DEFAULT_OUTPUT_ROOT),
            "language": payload.get("language") or "ru",
            "model": payload.get("model") or "large-v3-turbo",
            "device": payload.get("device") or "auto",
            "compute_type": payload.get("compute_type") or "auto",
            "offline": bool(payload.get("offline", False)),
            "initial_prompt": payload.get("initial_prompt") or None,
            "formats": set(payload.get("formats") or []),
        }

    def _read_multipart_job_payload(self, content_type: str) -> dict:
        length = int(self.headers.get("Content-Length") or "0")
        return read_multipart_job_payload(content_type, self.rfile, length)

    def _send_json(self, payload: dict, status: HTTPStatus = HTTPStatus.OK) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def read_multipart_job_payload(
    content_type: str,
    stream,
    content_length: int,
    *,
    default_output_root: Path = DEFAULT_OUTPUT_ROOT,
) -> dict:
    boundary = _multipart_boundary(content_type)
    if not boundary:
        raise ValueError("Некорректный multipart-запрос")

    boundary_line = b"--" + boundary
    fields: dict[str, str] = {}
    uploaded_path: Path | None = None
    uploaded_name: str | None = None

    line = stream.readline()
    if not line.startswith(boundary_line):
        raise ValueError("Некорректное начало multipart-запроса")

    while True:
        headers = _read_part_headers(stream)
        if headers is None:
            break

        name = headers.get_param("name", header="content-disposition")
        filename = headers.get_filename()
        if not name:
            boundary_hit = _discard_part(stream, boundary_line)
        elif filename:
            uploaded_name = Path(filename).name
            upload_dir = default_output_root / "_uploads" / uuid.uuid4().hex
            upload_dir.mkdir(parents=True, exist_ok=True)
            uploaded_path = upload_dir / uploaded_name
            boundary_hit = _write_part_to_file(stream, boundary_line, uploaded_path)
        else:
            value_bytes, boundary_hit = _read_part_bytes(stream, boundary_line)
            fields[name] = value_bytes.decode("utf-8")

        if boundary_hit.endswith(b"--\r\n") or boundary_hit.endswith(b"--\n") or boundary_hit.rstrip().endswith(b"--"):
            break

    output_root = Path(fields.get("output_root") or default_output_root)
    if uploaded_path is not None and uploaded_name and not _is_relative_to(uploaded_path, output_root):
        target_dir = output_root / "_uploads" / uuid.uuid4().hex
        target_dir.mkdir(parents=True, exist_ok=True)
        target_path = target_dir / uploaded_name
        shutil.move(str(uploaded_path), str(target_path))
        uploaded_path = target_path

    if uploaded_path is None and fields.get("input_path"):
        uploaded_path = Path(fields["input_path"])
    if uploaded_path is None:
        raise ValueError("Нужно выбрать файл или указать путь")

    return {
        "input_path": uploaded_path,
        "output_root": output_root,
        "language": fields.get("language") or "ru",
        "model": fields.get("model") or "large-v3-turbo",
        "device": fields.get("device") or "auto",
        "compute_type": fields.get("compute_type") or "auto",
        "offline": fields.get("offline") == "true",
        "initial_prompt": fields.get("initial_prompt") or None,
        "formats": {item.strip() for item in fields.get("formats", "").split(",") if item.strip()},
    }


def _multipart_boundary(content_type: str) -> bytes | None:
    message = BytesParser(policy=policy.default).parsebytes(
        b"Content-Type: "
        + content_type.encode("utf-8")
        + b"\r\nMIME-Version: 1.0\r\n\r\n"
    )
    boundary = message.get_boundary()
    return boundary.encode("utf-8") if boundary else None


def _read_part_headers(stream):
    header_lines = []
    while True:
        line = stream.readline()
        if line == b"":
            return None
        if line in {b"\r\n", b"\n"}:
            break
        header_lines.append(line)
    return BytesParser(policy=policy.default).parsebytes(b"".join(header_lines) + b"\r\n")


def _discard_part(stream, boundary_line: bytes) -> bytes:
    while True:
        line = stream.readline()
        if line == b"" or line.startswith(boundary_line):
            return line


def _read_part_bytes(stream, boundary_line: bytes) -> tuple[bytes, bytes]:
    chunks = []
    pending = b""
    while True:
        line = stream.readline()
        if line == b"":
            if pending:
                chunks.append(_strip_part_trailing_newline(pending))
            return b"".join(chunks), line
        if line.startswith(boundary_line):
            if pending:
                chunks.append(_strip_part_trailing_newline(pending))
            return b"".join(chunks), line
        if pending:
            chunks.append(pending)
        pending = line


def _write_part_to_file(stream, boundary_line: bytes, target: Path) -> bytes:
    pending = b""
    with target.open("wb") as file:
        while True:
            line = stream.readline()
            if line == b"":
                if pending:
                    file.write(_strip_part_trailing_newline(pending))
                return line
            if line.startswith(boundary_line):
                if pending:
                    file.write(_strip_part_trailing_newline(pending))
                return line
            if pending:
                file.write(pending)
            pending = line


def _strip_part_trailing_newline(chunk: bytes) -> bytes:
    if chunk.endswith(b"\r\n"):
        return chunk[:-2]
    if chunk.endswith(b"\n"):
        return chunk[:-1]
    return chunk


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="local-transcriber-web",
        description="Локальный веб-интерфейс для Local Transcriber.",
    )
    parser.add_argument("--host", default="127.0.0.1", help="Адрес локального сервера.")
    parser.add_argument("--port", type=int, default=8765, help="Порт локального сервера.")
    parser.add_argument(
        "--no-open",
        action="store_true",
        help="Не открывать браузер автоматически после запуска сервера.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    server = create_server(args.host, args.port)
    url = f"http://{args.host}:{server.server_address[1]}"
    print(f"Local Transcriber web UI: {url}")
    open_browser(url, enabled=not args.no_open)
    print("Нажмите Ctrl+C, чтобы остановить сервер.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
