from io import BytesIO
from pathlib import Path
from struct import pack

import pytest

from png import (
    PngBackground, PngChunk, PngCrcError, PngDocument, PngFrameControl, PngGamma,
    PngHeader, PngImage, PngOffset, PngParseError, PngTime, PngValidationError,
)

_SIGNATURE = b'\x89PNG\r\n\x1a\n'


class PayloadGuard:
    """Non-seekable short reader that refuses access beyond a chunk header."""

    def __init__(self, prefix: bytes, kind: bytes, length: int) -> None:
        self.header_end = len(prefix) + 8
        self.stream = BytesIO(prefix + pack('>I4s', length, kind) + b'unread payload and CRC')

    def read(self, size: int) -> bytes:
        assert 0 <= size <= 65536
        assert self.stream.tell() + size <= self.header_end, 'parser tried to read a rejected payload'
        return self.stream.read(min(size, 3))


def _prefix(png_suite_dir: Path, name: str, kinds: list[bytes]) -> bytes:
    source = PngDocument.load(png_suite_dir.joinpath(name))
    header = PngHeader.from_chunk(source.chunks[0])
    palette = PngDocument.load(png_suite_dir.joinpath('basn3p01.png')).find_chunks(b'PLTE')[0]
    available = {
        b'IHDR': source.chunks[0], b'IDAT': source.find_chunks(b'IDAT')[0], b'PLTE': palette,
        b'gAMA': PngGamma(45455).to_chunk(), b'fcTL': PngFrameControl(header.dimensions).to_chunk(0),
        b'bKGD': PngBackground((0, 0, 0)).to_chunk(), b'vpAg': PngChunk(b'vpAg', b'unknown safe'),
        b'tIME': PngTime(2026, 11, 13).to_chunk(), b'oFFs': PngOffset().to_chunk(),
    }
    return _SIGNATURE + b''.join(available[kind].dump_to_bytes() for kind in kinds)


@pytest.mark.parametrize(('kind', 'length', 'prefix'), [
    (b'IHDR', 0x7FFFFFFF, []), (b'IEND', 1, [b'IHDR', b'IDAT']),
    (b'cHRM', 33, [b'IHDR']), (b'gAMA', 5, [b'IHDR']),
    (b'cICP', 5, [b'IHDR']), (b'mDCV', 25, [b'IHDR']),
    (b'cLLI', 9, [b'IHDR']), (b'sRGB', 2, [b'IHDR']),
    (b'pHYs', 10, [b'IHDR']), (b'tIME', 8, [b'IHDR']),
    (b'acTL', 9, [b'IHDR']), (b'fcTL', 27, [b'IHDR']),
    (b'oFFs', 10, [b'IHDR']), (b'sTER', 2, [b'IHDR']),
])
def test_fixed_length_errors_stop_before_payload_and_crc(
        png_suite_dir: Path, kind: bytes, length: int, prefix: list[bytes],
) -> None:
    reader = PayloadGuard(_prefix(png_suite_dir, 'basn2c08.png', prefix), kind, length)
    with pytest.raises(PngParseError, match='must contain .* data bytes'):
        PngDocument.parse(reader)
    assert reader.stream.tell() == reader.header_end
    assert not reader.stream.closed


@pytest.mark.parametrize(('name', 'prefix', 'kind', 'length', 'message'), [
    ('basn2c08.png', [], b'IDAT', 0x7FFFFFFF, 'IHDR must be the first'),
    ('basn2c08.png', [b'IHDR'], b'VpAg', 0x7FFFFFFF, 'unknown critical'),
    ('basn2c08.png', [b'IHDR'], b'IHDR', 13, 'duplicate'),
    ('basn2c08.png', [b'IHDR', b'gAMA'], b'gAMA', 4, 'duplicate'),
    ('basn2c08.png', [b'IHDR', b'tIME'], b'tIME', 7, 'duplicate'),
    ('basn2c08.png', [b'IHDR', b'oFFs'], b'oFFs', 9, 'duplicate'),
    ('basn2c08.png', [b'IHDR', b'PLTE'], b'PLTE', 6, 'duplicate'),
    ('basn2c08.png', [b'IHDR', b'PLTE'], b'gAMA', 4, 'precede PLTE'),
    ('basn2c08.png', [b'IHDR', b'bKGD'], b'PLTE', 6, 'must follow PLTE'),
    ('basn2c08.png', [b'IHDR', b'IDAT'], b'gAMA', 4, 'precede IDAT'),
    ('basn2c08.png', [b'IHDR', b'IDAT'], b'PLTE', 6, 'precede IDAT'),
    ('basn2c08.png', [b'IHDR', b'IDAT'], b'eXIf', 0x7FFFFFFF, 'precede IDAT'),
    ('basn2c08.png', [b'IHDR', b'IDAT'], b'sPLT', 0x7FFFFFFF, 'precede IDAT'),
    ('basn2c08.png', [b'IHDR', b'IDAT'], b'acTL', 8, 'precede IDAT'),
    ('basn2c08.png', [b'IHDR', b'IDAT', b'vpAg'], b'IDAT', 0x7FFFFFFF, 'consecutive'),
    ('basn2c08.png', [b'IHDR'], b'IEND', 0, 'at least one IDAT'),
    ('basn2c08.png', [b'IHDR'], b'fdAT', 4, 'follow IDAT'),
    ('basn2c08.png', [b'IHDR', b'IDAT'], b'fdAT', 3, 'four-byte sequence'),
    ('basn2c08.png', [b'IHDR', b'fcTL'], b'fcTL', 26, 'at most one fcTL'),
    ('basn2c08.png', [b'IHDR'], b'PLTE', 0x7FFFFFFF, 'RGB entries'),
    ('basn2c08.png', [b'IHDR'], b'PLTE', 4, 'RGB entries'),
    ('basn0g08.png', [b'IHDR'], b'PLTE', 6, 'forbidden'),
    ('basn4a16.png', [b'IHDR'], b'PLTE', 6, 'forbidden'),
    ('basn3p01.png', [b'IHDR'], b'PLTE', 9, 'bit depth'),
    ('basn3p01.png', [b'IHDR'], b'IDAT', 0x7FFFFFFF, 'require a PLTE'),
    ('basn3p01.png', [b'IHDR'], b'tRNS', 1, 'require a PLTE'),
    ('basn3p01.png', [b'IHDR'], b'bKGD', 1, 'require a PLTE'),
    ('basn3p01.png', [b'IHDR', b'PLTE'], b'tRNS', 3, 'more entries'),
    ('basn0g08.png', [b'IHDR'], b'tRNS', 3, 'two bytes per'),
    ('basn2c16.png', [b'IHDR'], b'tRNS', 2, 'two bytes per'),
    ('basn6a08.png', [b'IHDR'], b'tRNS', 0x7FFFFFFF, 'forbidden'),
    ('basn4a08.png', [b'IHDR'], b'tRNS', 2, 'forbidden'),
    ('basn0g08.png', [b'IHDR'], b'bKGD', 6, 'bKGD'),
    ('basn2c08.png', [b'IHDR'], b'bKGD', 0x7FFFFFFF, 'bKGD'),
    ('basn3p01.png', [b'IHDR', b'PLTE'], b'bKGD', 2, 'bKGD'),
    ('basn2c08.png', [b'IHDR'], b'hIST', 2, 'PLTE'),
    ('basn3p01.png', [b'IHDR', b'PLTE'], b'hIST', 512, 'hIST'),
    ('basn3p01.png', [b'IHDR'], b'sBIT', 1, 'sBIT'),
    ('basn0g08.png', [b'IHDR'], b'sBIT', 3, 'sBIT'),
    ('basn6a16.png', [b'IHDR'], b'sBIT', 0x7FFFFFFF, 'sBIT'),
])
def test_structure_errors_stop_at_the_first_invalid_header(
        png_suite_dir: Path, name: str, prefix: list[bytes], kind: bytes, length: int, message: str,
) -> None:
    reader = PayloadGuard(_prefix(png_suite_dir, name, prefix), kind, length)
    with pytest.raises(PngParseError, match=message):
        PngImage.parse(reader)
    assert reader.stream.tell() == reader.header_end


@pytest.mark.parametrize('edit', ['length', 'duplicate', 'order', 'palette', 'critical', 'idat'])
def test_streaming_and_in_memory_structure_errors_agree(png_suite_dir: Path, edit: str) -> None:
    document = PngDocument.load(png_suite_dir.joinpath('basn2c08.png'))
    if edit == 'length':
        document.chunks.insert(1, PngChunk(b'pHYs', bytes(10)))
    elif edit == 'duplicate':
        document.chunks.insert(1, document.chunks[0])
    elif edit == 'order':
        document.chunks.insert(-1, PngOffset().to_chunk())
    elif edit == 'palette':
        document.chunks.insert(-2, PngChunk(b'PLTE', bytes(4)))
    elif edit == 'critical':
        document.chunks.insert(1, PngChunk(b'VpAg'))
    else:
        document.chunks[-1:-1] = [PngChunk(b'vpAg'), PngChunk(b'IDAT')]
    with pytest.raises(PngValidationError) as model_error:
        document.validate()
    data = _SIGNATURE + b''.join(chunk.dump_to_bytes() for chunk in document.chunks)
    with pytest.raises(PngParseError) as read_error:
        PngDocument.parse(data)
    assert str(model_error.value) == str(read_error.value)


def test_raw_chunk_parser_retains_its_context_free_contract() -> None:
    # A chunk envelope can be inspected without asserting that it belongs to a
    # valid PNG document; contextual checks belong to PngDocument.
    for kind, data in [(b'IHDR', b'invalid'), (b'VpAg', b'unknown critical')]:
        chunk = PngChunk.parse(PngChunk(kind, data).dump_to_bytes())
        assert (chunk.type, chunk.data) == (kind, data)


def test_crc_is_still_checked_for_every_accepted_chunk_header(png_suite_dir: Path) -> None:
    prefix = _prefix(png_suite_dir, 'basn2c08.png', [b'IHDR'])
    # The order and length are valid, so the payload and CRC must be consumed.
    encoded = PngGamma(45455).to_chunk().dump_to_bytes()
    stream = BytesIO(prefix + encoded[:-4] + bytes(4) + b'unread suffix')
    with pytest.raises(PngCrcError):
        PngDocument.parse(stream)
    assert stream.read() == b'unread suffix'
    assert not stream.closed


def test_reading_stops_after_one_valid_iend_and_does_not_check_the_next_header(png_suite_dir: Path) -> None:
    data = png_suite_dir.joinpath('basn3p01.png').read_bytes()
    stream = BytesIO(data + pack('>I4s', 0x7FFFFFFF, b'VpAg'))
    assert PngDocument.parse(stream).dump_to_bytes() == data
    assert stream.tell() == len(data)


def test_splitting_idat_and_repeating_unknown_chunks_remain_valid(png_suite_dir: Path) -> None:
    document = PngDocument.load(png_suite_dir.joinpath('basn2c08.png'))
    original = PngImage.from_document(document).bitmap
    document.chunks[1:1] = [PngChunk(b'vpAg', b'repeated'), PngChunk(b'vpAg', b'repeated')]
    index = next(index for index, chunk in enumerate(document.chunks) if chunk.type == b'IDAT')
    data = document.chunks[index].data
    document.chunks[index:index + 1] = [PngChunk(b'IDAT')] + [
        PngChunk(b'IDAT', data[start:start + 1]) for start in range(len(data))] + [PngChunk(b'IDAT')]
    output = PngDocument.parse(document.dump_to_bytes())
    assert len(output.find_chunks(b'vpAg')) == 2
    assert PngImage.from_document(output).bitmap == original
