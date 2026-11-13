class PngError(Exception):
    pass


class PngValidationError(PngError, ValueError):
    """The current data cannot be represented by the supported PNG model."""


class PngParseError(PngError):
    """The input datastream is corrupt or has an unsupported structure."""


class PngCrcError(PngParseError):
    chunk_type: bytes
    expected: int
    actual: int

    def __init__(self, chunk_type: bytes, expected: int, actual: int) -> None:
        self.chunk_type = chunk_type
        self.expected = expected
        self.actual = actual
        super().__init__(f'CRC mismatch for {chunk_type!r}: stored {expected:08x}, calculated {actual:08x}')
