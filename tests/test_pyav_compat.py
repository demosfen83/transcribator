import unittest

from local_transcriber.pyav_compat import patch_av_open_metadata_errors


class PyAvCompatTests(unittest.TestCase):
    def test_patch_drops_metadata_errors_when_pyav_rejects_it(self):
        calls = []

        def open_func(*args, **kwargs):
            calls.append(kwargs.copy())
            if "metadata_errors" in kwargs:
                raise TypeError("open() got an unexpected keyword argument 'metadata_errors'")
            return "container"

        patched = patch_av_open_metadata_errors(open_func)

        result = patched("file.mp4", mode="r", metadata_errors="ignore")

        self.assertEqual(result, "container")
        self.assertEqual(calls, [{"mode": "r", "metadata_errors": "ignore"}, {"mode": "r"}])

    def test_patch_does_not_hide_other_type_errors(self):
        def open_func(*args, **kwargs):
            raise TypeError("different type error")

        patched = patch_av_open_metadata_errors(open_func)

        with self.assertRaisesRegex(TypeError, "different type error"):
            patched("file.mp4", metadata_errors="ignore")


if __name__ == "__main__":
    unittest.main()
