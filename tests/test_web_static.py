import unittest
from pathlib import Path


class WebStaticTests(unittest.TestCase):
    def setUp(self):
        self.static_dir = Path.cwd() / "local_transcriber" / "web_static"

    def test_static_ui_files_exist_and_reference_api(self):
        index = (self.static_dir / "index.html").read_text(encoding="utf-8")
        styles = (self.static_dir / "styles.css").read_text(encoding="utf-8")
        app = (self.static_dir / "app.js").read_text(encoding="utf-8")

        self.assertIn('id="transcription-form"', index)
        self.assertIn('name="file"', index)
        self.assertIn('name="input_path"', index)
        self.assertIn('<option value="auto" selected>Auto</option>', index)
        self.assertIn('name="compute_type" value="auto"', index)
        self.assertIn('href="/static/styles.css"', index)
        self.assertIn('src="/static/app.js"', index)
        self.assertIn("fetch('/api/jobs'", app)
        self.assertIn("FormData", app)
        self.assertIn("setInterval", app)
        self.assertIn("job.progress.percentage", app)
        self.assertIn("lastProgressPercentage", app)
        self.assertIn("Math.max(lastProgressPercentage, percentage)", app)
        self.assertIn("result-list", app)
        self.assertIn(":focus-visible", styles)
        self.assertIn("overflow-wrap: anywhere", styles)
        self.assertIn("min-width: 0", styles)


if __name__ == "__main__":
    unittest.main()
