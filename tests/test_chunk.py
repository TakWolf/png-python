from io import BytesIO, StringIO
from struct import pack

import pytest

from png import PngChunk, PngCrcError, PngParseError, PngValidationError


class ShortReader(BytesIO):
    def read(self, size: int = -1) -> bytes:
        return super().read(min(size, 3))


class ShortWriter(BytesIO):
    def write(self, data: bytes) -> int:
        return super().write(data[:2])


def test_known_iend_crc_and_partial_io() -> None:
    # Fixed reference from the standard PNG trailer, not a library round trip.
    encoded = bytes.fromhex('00000000 49454e44 ae426082')
    chunk = PngChunk.parse(ShortReader(encoded))
    assert chunk.type == b'IEND'
    assert chunk.data == b''
    assert chunk.crc == 0xAE426082
    output = ShortWriter()
    chunk.dump(output)
    assert output.getvalue() == encoded


def test_chunk_stops_at_its_boundary() -> None:
    encoded = PngChunk(b'vpAg', b'payload').dump_to_bytes()
    stream = BytesIO(encoded + b'next chunk')
    parsed = PngChunk.parse(stream)
    assert parsed.type == b'vpAg'
    assert parsed.data == b'payload'
    assert stream.read() == b'next chunk'
    assert not stream.closed


@pytest.mark.parametrize('removed', range(1, 20))
def test_truncated_chunk(removed: int) -> None:
    encoded = PngChunk(b'vpAg', b'payload').dump_to_bytes()
    with pytest.raises(PngParseError, match='end of stream'):
        PngChunk.parse(encoded[:-removed])


def test_crc_mismatch_reports_chunk_and_values() -> None:
    encoded = PngChunk(b'vpAg', b'payload').dump_to_bytes()
    with pytest.raises(PngCrcError) as caught:
        PngChunk.parse(encoded[:-4] + bytes(4))
    assert caught.value.chunk_type == b'vpAg'
    assert caught.value.expected == 0
    assert caught.value.actual == PngChunk(b'vpAg', b'payload').crc


@pytest.mark.parametrize('header', [pack('>I4s', 0x80000000, b'IDAT'), pack('>I4s', 0, b'bad!')])
def test_invalid_envelope_is_rejected_before_reading_payload(header: bytes) -> None:
    stream = BytesIO(header + b'unread data')
    with pytest.raises(PngParseError):
        PngChunk.parse(stream)
    assert stream.tell() == 8


def test_huge_advertised_length_does_not_trigger_a_huge_read() -> None:
    class CheckedReader(BytesIO):
        def read(self, size: int = -1) -> bytes:
            assert 0 <= size <= 65536
            return super().read(size)

    with pytest.raises(PngParseError, match='end of stream'):
        PngChunk.parse(CheckedReader(pack('>I4s', 0x7FFFFFFF, b'IDAT')))


def test_binary_stream_contract() -> None:
    with pytest.raises(TypeError, match='binary'):
        PngChunk.parse(StringIO('not bytes'))
    with pytest.raises(PngValidationError):
        PngChunk(b'vpAg', bytearray()).dump_to_bytes()


@pytest.mark.parametrize('result', [None, 0, -1, 100])
def test_output_stream_must_make_progress(result: int | None) -> None:
    class BrokenWriter:
        def write(self, data: bytes) -> int | None:
            return result

    with pytest.raises(OSError):
        PngChunk(b'IEND').dump(BrokenWriter())
