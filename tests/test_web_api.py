import json
import shutil
import threading
import unittest
import urllib.error
import urllib.request
import uuid
from pathlib import Path

from local_transcriber.formatters import TranscriptPayload
from local_transcriber.transcriber import TranscriptionResult
from local_transcriber.web import create_server
from local_transcriber.web import open_browser
from local_transcriber.web import read_multipart_job_payload
from local_transcriber.web_jobs import WebJobManager


class WebApiTests(unittest.TestCase):
    def setUp(self):
        self.root = Path.cwd() / "tests_tmp" / f"web_api_{uuid.uuid4().hex}"
        self.root.mkdir(parents=True)
        self.input_file = self.root / "sample.mp4"
        self.input_file.write_bytes(b"fake media")

    def tearDown(self):
        if hasattr(self, "server"):
            self.server.shutdown()
            self.server.server_close()
        shutil.rmtree(self.root, ignore_errors=True)

    def test_create_job_status_and_download_file(self):
        def fake_transcriber(options, *, progress=None):
            output_dir = self.root / "output" / "sample"
            output_dir.mkdir(parents=True)
            written_file = output_dir / "transcript.md"
            written_file.write_text("# Транскрипт\n", encoding="utf-8")
            payload = TranscriptPayload(
                source=str(options.input_path),
                duration=0.0,
                language="ru",
                language_probability=1.0,
                segments=[],
            )
            return TranscriptionResult(output_dir, [written_file], [], payload)

        manager = WebJobManager(transcriber=fake_transcriber, run_async=False)
        base_url = self._start_server(manager)

        created = self._post_json(
            f"{base_url}/api/jobs",
            {
                "input_path": str(self.input_file),
                "output_root": str(self.root / "output"),
                "language": "ru",
                "model": "large-v3-turbo",
                "device": "cpu",
                "compute_type": "int8",
                "offline": True,
                "formats": ["md"],
            },
        )

        self.assertEqual(created["status"], "done")
        job_id = created["id"]

        status = self._get_json(f"{base_url}/api/jobs/{job_id}")
        self.assertEqual(status["files"][0]["name"], "transcript.md")

        with urllib.request.urlopen(f"{base_url}/api/jobs/{job_id}/files/transcript.md") as response:
            self.assertEqual(response.status, 200)
            self.assertIn("# Транскрипт", response.read().decode("utf-8"))

    def test_root_serves_browser_ui(self):
        manager = WebJobManager(run_async=False)
        base_url = self._start_server(manager)

        with urllib.request.urlopen(f"{base_url}/") as response:
            html = response.read().decode("utf-8")

        self.assertEqual(response.status, 200)
        self.assertIn("Local Transcriber", html)
        self.assertIn('id="transcription-form"', html)

    def test_file_download_requires_done_job(self):
        def fake_transcriber(options, *, progress=None):
            payload = TranscriptPayload(
                source=str(options.input_path),
                duration=0.0,
                language="ru",
                language_probability=1.0,
                segments=[],
            )
            return TranscriptionResult(self.root / "output" / "sample", [], [], payload)

        manager = WebJobManager(transcriber=fake_transcriber, run_async=False)
        job = manager.create_job(
            input_path=self.input_file,
            output_root=self.root / "output",
            language="ru",
            model="large-v3-turbo",
            device="cpu",
            compute_type="int8",
            offline=True,
            initial_prompt=None,
            formats={"md"},
        )
        leaked_file = self.root / "output" / "sample" / "transcript.md"
        leaked_file.parent.mkdir(parents=True, exist_ok=True)
        leaked_file.write_text("# Partial\n", encoding="utf-8")
        job.status = "running"
        job.written_files = [leaked_file]
        base_url = self._start_server(manager)

        with self.assertRaises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(f"{base_url}/api/jobs/{job.id}/files/transcript.md")

        self.assertEqual(error.exception.code, 409)

    def test_create_job_rejects_bad_format(self):
        manager = WebJobManager(run_async=False)
        base_url = self._start_server(manager)

        with self.assertRaises(urllib.error.HTTPError) as error:
            self._post_json(
                f"{base_url}/api/jobs",
                {
                    "input_path": str(self.input_file),
                    "output_root": str(self.root / "output"),
                    "language": "ru",
                    "model": "large-v3-turbo",
                    "device": "cpu",
                    "compute_type": "int8",
                    "offline": True,
                    "formats": ["docx"],
                },
            )

        self.assertEqual(error.exception.code, 400)

    def test_json_job_defaults_to_auto_device_and_compute_type(self):
        calls = []

        def fake_transcriber(options, *, progress=None):
            calls.append(options)
            output_dir = self.root / "output" / "sample"
            output_dir.mkdir(parents=True)
            written_file = output_dir / "transcript.md"
            written_file.write_text("# Транскрипт\n", encoding="utf-8")
            payload = TranscriptPayload(
                source=str(options.input_path),
                duration=0.0,
                language="ru",
                language_probability=1.0,
                segments=[],
            )
            return TranscriptionResult(output_dir, [written_file], [], payload)

        manager = WebJobManager(transcriber=fake_transcriber, run_async=False)
        base_url = self._start_server(manager)

        self._post_json(
            f"{base_url}/api/jobs",
            {
                "input_path": str(self.input_file),
                "output_root": str(self.root / "output"),
                "language": "ru",
                "model": "large-v3-turbo",
                "formats": ["md"],
            },
        )

        self.assertEqual(calls[0].device, "auto")
        self.assertEqual(calls[0].compute_type, "auto")

    def test_open_browser_uses_supplied_opener(self):
        opened = []

        def opener(url):
            opened.append(url)
            return True

        result = open_browser("http://127.0.0.1:8765", opener=opener)

        self.assertTrue(result)
        self.assertEqual(opened, ["http://127.0.0.1:8765"])

    def test_open_browser_can_be_disabled(self):
        opened = []

        result = open_browser("http://127.0.0.1:8765", enabled=False, opener=opened.append)

        self.assertFalse(result)
        self.assertEqual(opened, [])

    def test_create_job_accepts_uploaded_file(self):
        seen_input_paths = []

        def fake_transcriber(options, *, progress=None):
            seen_input_paths.append(options.input_path)
            output_dir = self.root / "output" / options.input_path.stem
            output_dir.mkdir(parents=True)
            written_file = output_dir / "transcript.srt"
            written_file.write_text("1\n00:00:00,000 --> 00:00:01,000\nДа\n", encoding="utf-8")
            payload = TranscriptPayload(
                source=str(options.input_path),
                duration=0.0,
                language="ru",
                language_probability=1.0,
                segments=[],
            )
            return TranscriptionResult(output_dir, [written_file], [], payload)

        manager = WebJobManager(transcriber=fake_transcriber, run_async=False)
        base_url = self._start_server(manager)

        created = self._post_multipart(
            f"{base_url}/api/jobs",
            fields={
                "output_root": str(self.root / "output"),
                "language": "ru",
                "model": "large-v3-turbo",
                "device": "cpu",
                "compute_type": "int8",
                "offline": "true",
                "formats": "srt",
            },
            file_name="meeting.mp4",
            file_bytes=b"uploaded media",
        )

        self.assertEqual(created["status"], "done")
        self.assertEqual(seen_input_paths[0].name, "meeting.mp4")
        self.assertTrue(seen_input_paths[0].exists())
        self.assertTrue(str(seen_input_paths[0]).startswith(str(self.root / "output")))

    def test_upload_uses_output_root_even_when_file_part_arrives_first(self):
        seen_input_paths = []

        def fake_transcriber(options, *, progress=None):
            seen_input_paths.append(options.input_path)
            output_dir = self.root / "output" / options.input_path.stem
            output_dir.mkdir(parents=True)
            written_file = output_dir / "transcript.md"
            written_file.write_text("# Транскрипт\n", encoding="utf-8")
            payload = TranscriptPayload(
                source=str(options.input_path),
                duration=0.0,
                language="ru",
                language_probability=1.0,
                segments=[],
            )
            return TranscriptionResult(output_dir, [written_file], [], payload)

        manager = WebJobManager(transcriber=fake_transcriber, run_async=False)
        base_url = self._start_server(manager)

        self._post_multipart(
            f"{base_url}/api/jobs",
            fields={
                "output_root": str(self.root / "output"),
                "language": "ru",
                "model": "large-v3-turbo",
                "device": "cpu",
                "compute_type": "int8",
                "formats": "md",
            },
            file_name="early-file.mp4",
            file_bytes=b"uploaded media",
            file_first=True,
        )

        self.assertTrue(str(seen_input_paths[0]).startswith(str(self.root / "output")))

    def test_multipart_upload_is_parsed_without_reading_entire_body(self):
        boundary = f"----local-transcriber-{uuid.uuid4().hex}"
        body = b"".join(
            [
                f"--{boundary}\r\n".encode("utf-8"),
                b'Content-Disposition: form-data; name="file"; filename="large.mp4"\r\n',
                b"Content-Type: application/octet-stream\r\n\r\n",
                b"first chunk\n",
                b"second chunk\n",
                f"--{boundary}\r\n".encode("utf-8"),
                b'Content-Disposition: form-data; name="output_root"\r\n\r\n',
                str(self.root / "output").encode("utf-8"),
                b"\r\n",
                f"--{boundary}\r\n".encode("utf-8"),
                b'Content-Disposition: form-data; name="formats"\r\n\r\n',
                b"md\r\n",
                f"--{boundary}--\r\n".encode("utf-8"),
            ]
        )

        payload = read_multipart_job_payload(
            f"multipart/form-data; boundary={boundary}",
            NoBulkReadStream(body),
            len(body),
        )

        self.assertEqual(payload["input_path"].name, "large.mp4")
        self.assertTrue(str(payload["input_path"]).startswith(str(self.root / "output")))
        self.assertEqual(payload["input_path"].read_bytes(), b"first chunk\nsecond chunk")
        self.assertEqual(payload["formats"], {"md"})

    def _start_server(self, manager):
        self.server = create_server("127.0.0.1", 0, manager=manager)
        thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        thread.start()
        host, port = self.server.server_address
        return f"http://{host}:{port}"

    def _post_json(self, url, payload):
        data = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request) as response:
            return json.loads(response.read().decode("utf-8"))

    def _get_json(self, url):
        with urllib.request.urlopen(url) as response:
            return json.loads(response.read().decode("utf-8"))

    def _post_multipart(self, url, *, fields, file_name, file_bytes, file_first=False):
        boundary = f"----local-transcriber-{uuid.uuid4().hex}"
        chunks = []
        file_chunks = [
            f"--{boundary}\r\n".encode("utf-8"),
            f'Content-Disposition: form-data; name="file"; filename="{file_name}"\r\n'.encode("utf-8"),
            b"Content-Type: application/octet-stream\r\n\r\n",
            file_bytes,
            b"\r\n",
        ]
        if file_first:
            chunks.extend(file_chunks)
        for name, value in fields.items():
            chunks.extend(
                [
                    f"--{boundary}\r\n".encode("utf-8"),
                    f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode("utf-8"),
                    str(value).encode("utf-8"),
                    b"\r\n",
                ]
            )
        if not file_first:
            chunks.extend(file_chunks)
        chunks.append(f"--{boundary}--\r\n".encode("utf-8"))
        request = urllib.request.Request(
            url,
            data=b"".join(chunks),
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
            method="POST",
        )
        with urllib.request.urlopen(request) as response:
            return json.loads(response.read().decode("utf-8"))


if __name__ == "__main__":
    unittest.main()


class NoBulkReadStream:
    def __init__(self, body):
        self.lines = body.splitlines(keepends=True)

    def readline(self):
        if not self.lines:
            return b""
        return self.lines.pop(0)

    def read(self, size=-1):
        raise AssertionError("multipart parser must not read the whole request body")
