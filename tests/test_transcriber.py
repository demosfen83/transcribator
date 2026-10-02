import shutil
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace

from local_transcriber.errors import InputFileError
from local_transcriber.errors import ModelLoadError
from local_transcriber.transcriber import TranscriptionOptions, transcribe_file


class FakeWhisperModel:
    calls = []

    def __init__(self, model_name_or_path, **kwargs):
        self.model_name_or_path = model_name_or_path
        self.kwargs = kwargs
        FakeWhisperModel.calls.append(("init", model_name_or_path, kwargs))

    def transcribe(self, input_path, **kwargs):
        FakeWhisperModel.calls.append(("transcribe", input_path, kwargs))
        segments = [
            SimpleNamespace(id=7, start=0.0, end=1.25, text=" Тестовая фраза. "),
        ]
        info = SimpleNamespace(language="ru", language_probability=0.98, duration=1.25)
        return iter(segments), info


class FailingWhisperModel:
    def __init__(self, *args, **kwargs):
        raise RuntimeError("model missing")


class TranscriberTests(unittest.TestCase):
    def setUp(self):
        self.root = Path.cwd() / "tests_tmp" / f"transcriber_{uuid.uuid4().hex}"
        self.root.mkdir(parents=True)
        self.input_file = self.root / "sample.mp4"
        self.input_file.write_bytes(b"fake media")
        FakeWhisperModel.calls.clear()

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_transcribe_file_writes_default_output_under_input_stem(self):
        options = TranscriptionOptions(
            input_path=self.input_file,
            output_root=self.root / "output",
            language="ru",
            model="large-v3-turbo",
            device="cpu",
            compute_type="int8",
            offline=True,
            initial_prompt=None,
            formats={"md", "json", "srt"},
        )

        result = transcribe_file(options, model_cls=FakeWhisperModel)

        self.assertEqual(result.output_dir, self.root / "output" / "sample")
        self.assertTrue((result.output_dir / "transcript.md").exists())
        self.assertEqual(len(result.segments), 1)
        self.assertEqual(FakeWhisperModel.calls[0][2]["local_files_only"], True)
        self.assertEqual(FakeWhisperModel.calls[1][2]["language"], "ru")

    def test_transcribe_file_reports_metadata_before_collecting_segments(self):
        options = TranscriptionOptions(
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
        events = []

        transcribe_file(
            options,
            model_cls=FakeWhisperModel,
            metadata=lambda event: events.append(event),
        )

        self.assertEqual(events, [{"duration": 1.25}])

    def test_missing_input_raises_clear_error(self):
        options = TranscriptionOptions(
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

        with self.assertRaises(InputFileError):
            transcribe_file(options, model_cls=FakeWhisperModel)

    def test_model_load_failure_does_not_create_empty_output_folder(self):
        output_root = self.root / "output"
        options = TranscriptionOptions(
            input_path=self.input_file,
            output_root=output_root,
            language="ru",
            model="large-v3-turbo",
            device="cpu",
            compute_type="int8",
            offline=True,
            initial_prompt=None,
            formats={"md"},
        )

        with self.assertRaises(ModelLoadError):
            transcribe_file(options, model_cls=FailingWhisperModel)

        self.assertFalse((output_root / "sample").exists())


if __name__ == "__main__":
    unittest.main()
