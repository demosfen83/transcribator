class LocalTranscriberError(Exception):
    """Base class for expected user-facing transcription errors."""


class InputFileError(LocalTranscriberError):
    """Raised when the input media path is invalid."""


class OutputDirectoryError(LocalTranscriberError):
    """Raised when output files cannot be written."""


class ModelLoadError(LocalTranscriberError):
    """Raised when the Whisper model cannot be loaded."""


class MediaReadError(LocalTranscriberError):
    """Raised when faster-whisper cannot read or transcribe the media."""


class CudaUnavailableError(LocalTranscriberError):
    """Raised when CUDA is explicitly requested but unavailable."""
