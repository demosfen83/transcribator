from __future__ import annotations

from functools import wraps
from typing import Callable


def patch_av_open_metadata_errors(open_func: Callable) -> Callable:
    @wraps(open_func)
    def wrapper(*args, **kwargs):
        try:
            return open_func(*args, **kwargs)
        except TypeError as exc:
            if "metadata_errors" not in kwargs:
                raise
            if "metadata_errors" not in str(exc):
                raise

            retry_kwargs = dict(kwargs)
            retry_kwargs.pop("metadata_errors", None)
            return open_func(*args, **retry_kwargs)

    return wrapper


def install_pyav_metadata_errors_compat() -> None:
    try:
        import av
    except ImportError:
        return

    current_open = av.open
    if getattr(current_open, "_local_transcriber_metadata_errors_compat", False):
        return

    patched_open = patch_av_open_metadata_errors(current_open)
    setattr(patched_open, "_local_transcriber_metadata_errors_compat", True)
    av.open = patched_open
