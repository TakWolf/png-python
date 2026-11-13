from typing import BinaryIO

from png.error import PngParseError


def read_exact(stream: BinaryIO, size: int) -> bytes:
    """Handle short reads without allocating from an untrusted chunk length."""
    data = bytearray()
    while len(data) < size:
        part = stream.read(min(size - len(data), 65536))
        if not isinstance(part, bytes):
            raise TypeError('a blocking binary input stream is required')
        if not part:
            raise PngParseError(f'unexpected end of stream: expected {size} bytes, got {len(data)}')
        data.extend(part)
    return bytes(data)


def write_all(stream: BinaryIO, data: bytes) -> None:
    view = memoryview(data)
    while view:
        count = stream.write(view)
        if count is None or count <= 0 or count > len(view):
            raise OSError('binary output stream did not accept the data')
        view = view[count:]
