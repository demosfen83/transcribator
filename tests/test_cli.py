import unittest

from local_transcriber.cli import parse_formats


class CliTests(unittest.TestCase):
    def test_parse_formats_accepts_comma_separated_values(self):
        self.assertEqual(parse_formats("md,json,srt"), {"md", "json", "srt"})

    def test_parse_formats_rejects_unknown_values(self):
        with self.assertRaises(ValueError):
            parse_formats("md,docx")


if __name__ == "__main__":
    unittest.main()
