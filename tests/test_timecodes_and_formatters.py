import json
import shutil
import unittest
import uuid
from pathlib import Path

from local_transcriber.formatters import TranscriptPayload, write_outputs
from local_transcriber.timecodes import format_srt_timestamp, format_timestamp


class TimecodeTests(unittest.TestCase):
    def test_markdown_timestamp_rounds_to_seconds(self):
        self.assertEqual(format_timestamp(3661.6), "01:01:02")

    def test_srt_timestamp_uses_milliseconds(self):
        self.assertEqual(format_srt_timestamp(61.2345), "00:01:01,234")


class FormatterTests(unittest.TestCase):
    def test_write_outputs_creates_markdown_json_and_srt(self):
        output_dir = self.tmpdir
        payload = TranscriptPayload(
            source="E:\\Videos\\call.mp4",
            duration=2.5,
            language="ru",
            language_probability=0.99,
            segments=[
                {
                    "id": 1,
                    "start": 0.0,
                    "end": 2.5,
                    "start_ts": "00:00:00",
                    "end_ts": "00:00:02",
                    "text": "Привет, это проверка.",
                }
            ],
        )

        written = write_outputs(payload, output_dir, {"md", "json", "srt"})

        self.assertEqual(
            {path.name for path in written},
            {"transcript.md", "transcript_segments.json", "transcript.srt"},
        )
        self.assertIn("**00:00:00 - 00:00:02** Привет", (output_dir / "transcript.md").read_text(encoding="utf-8"))
        data = json.loads((output_dir / "transcript_segments.json").read_text(encoding="utf-8"))
        self.assertEqual(data["source"], "E:\\Videos\\call.mp4")
        self.assertEqual(data["segments"][0]["text"], "Привет, это проверка.")
        self.assertIn("00:00:00,000 --> 00:00:02,500", (output_dir / "transcript.srt").read_text(encoding="utf-8"))

    def setUp(self):
        self.tmpdir = Path.cwd() / "tests_tmp" / f"formatter_{uuid.uuid4().hex}"
        self.tmpdir.mkdir(parents=True)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
