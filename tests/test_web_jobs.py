import shutil
import unittest
import uuid
from pathlib import Path

from local_transcriber.errors import InputFileError, LocalTranscriberError
from local_transcriber.formatters import TranscriptPayload
from local_transcriber.transcriber import TranscriptionOptions, TranscriptionResult
from local_transcriber.web_jobs import WebJob, WebJobManager


class WebJobManagerTests(unittest.TestCase):
    def setUp(self):
        self.root = Path.cwd() / "tests_tmp" / f"web_jobs_{uuid.uuid4().hex}"
        self.root.mkdir(parents=True)
        self.input_file = self.root / "sample.mp4"
        self.input_file.write_bytes(b"fake media")

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_create_job_runs_transcriber_and_records_success(self):
        calls = []

        def fake_transcriber(options, *, progress=None):
            calls.append(options)
            segment = {
                "id": 1,
                "start": 0.0,
                "end": 2.0,
                "start_ts": "00:00:00",
                "end_ts": "00:00:02",
                "text": "Привет.",
            }
            progress(segment)
            output_dir = self.root / "output" / "sample"
            output_dir.mkdir(parents=True)
            written_file = output_dir / "transcript.md"
            written_file.write_text("# Транскрипт\n", encoding="utf-8")
            payload = TranscriptPayload(
                source=str(self.input_file),
                duration=2.0,
                language="ru",
                language_probability=0.99,
                segments=[segment],
            )
            return TranscriptionResult(output_dir, [written_file], [segment], payload)

        manager = WebJobManager(
            transcriber=fake_transcriber,
            duration_reader=lambda path: 2.0,
            run_async=False,
        )

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

        self.assertEqual(job.status, "done")
        self.assertEqual(calls[0].device, "cpu")
        self.assertEqual(calls[0].compute_type, "int8")
        self.assertEqual(job.progress_segments[-1]["text"], "Привет.")
        self.assertEqual(job.to_dict()["progress"]["percentage"], 100)
        self.assertEqual(job.to_dict()["progress"]["duration"], 2.0)
        self.assertEqual(job.to_dict()["files"][0]["name"], "transcript.md")

    def test_progress_percentage_uses_latest_segment_end_and_duration(self):
        job = WebJob(
            id="job-1",
            options=TranscriptionOptions(
                input_path=self.input_file,
                output_root=self.root / "output",
                language="ru",
                model="large-v3-turbo",
                device="auto",
                compute_type="auto",
                offline=False,
                initial_prompt=None,
                formats={"md"},
            ),
            status="running",
            duration=660.0,
            progress_segments=[
                {
                    "id": 1,
                    "start": 0.0,
                    "end": 540.0,
                    "start_ts": "00:00:00",
                    "end_ts": "00:09:00",
                    "text": "Почти конец.",
                }
            ],
        )

        self.assertEqual(job.to_dict()["progress"]["percentage"], 82)
        self.assertEqual(job.to_dict()["progress"]["latest_end"], 540.0)

    def test_progress_percentage_never_regresses_when_latest_segment_end_is_lower(self):
        job = WebJob(
            id="job-1",
            options=TranscriptionOptions(
                input_path=self.input_file,
                output_root=self.root / "output",
                language="ru",
                model="large-v3-turbo",
                device="auto",
                compute_type="auto",
                offline=False,
                initial_prompt=None,
                formats={"md"},
            ),
            status="running",
            duration=600.0,
            progress_segments=[
                {"id": 1, "start": 0.0, "end": 120.0, "text": "20%"},
                {"id": 2, "start": 0.0, "end": 0.0, "text": "bad low segment"},
            ],
        )

        self.assertEqual(job.to_dict()["progress"]["percentage"], 20)
        self.assertEqual(job.to_dict()["progress"]["latest_end"], 120.0)

    def test_transcriber_metadata_replaces_bad_preflight_duration_while_running(self):
        def fake_transcriber(options, *, progress=None, metadata=None):
            metadata({"duration": 660.0})
            progress(
                {
                    "id": 1,
                    "start": 159.0,
                    "end": 168.0,
                    "start_ts": "00:02:39",
                    "end_ts": "00:02:48",
                    "text": "Сегмент.",
                }
            )
            raise LocalTranscriberError("stop after progress")

        manager = WebJobManager(
            transcriber=fake_transcriber,
            duration_reader=lambda path: 999999.0,
            run_async=False,
        )

        job = manager.create_job(
            input_path=self.input_file,
            output_root=self.root / "output",
            language="ru",
            model="large-v3-turbo",
            device="auto",
            compute_type="auto",
            offline=False,
            initial_prompt=None,
            formats={"md"},
        )

        progress = job.to_dict()["progress"]
        self.assertEqual(progress["duration"], 660.0)
        self.assertEqual(progress["percentage"], 25)

    def test_missing_input_fails_before_transcriber_runs(self):
        def fake_transcriber(options, *, progress=None):
            raise AssertionError("transcriber should not run")

        manager = WebJobManager(transcriber=fake_transcriber, run_async=False)

        with self.assertRaises(InputFileError):
            manager.create_job(
                input_path=self.root / "missing.mp4",
                output_root=self.root / "output",
                language="ru",
                model="large-v3-turbo",
                device="cpu",
                compute_type="int8",
                offline=True,
                initial_prompt=None,
                formats={"md"},
            )

    def test_transcriber_failure_records_failed_status(self):
        def fake_transcriber(options, *, progress=None):
            raise LocalTranscriberError("Модель недоступна")

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

        self.assertEqual(job.status, "failed")
        self.assertEqual(job.error, "Модель недоступна")
        self.assertEqual(job.to_dict()["error"], "Модель недоступна")


if __name__ == "__main__":
    unittest.main()
