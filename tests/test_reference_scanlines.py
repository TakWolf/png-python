"""PNG scanline vectors independent of the library's packing and Adam7 code."""

import zlib
from io import BytesIO
from itertools import cycle
from struct import pack, unpack_from

import pytest

from png import PngFilterType, PngImage

_FORMATS = (
    [(0, depth) for depth in (1, 2, 4, 8, 16)]
    + [(3, depth) for depth in (1, 2, 4, 8)]
    + [(color, depth) for color in (2, 4, 6) for depth in (8, 16)]
)
_CHANNELS = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}
_DIMENSIONS = [(1, 1), (1, 8), (8, 1), (2, 2), (3, 5), (5, 3), (7, 9), (9, 7), (8, 8), (15, 17), (17, 15)]


def _adam7_pass(column: int, row: int) -> int:
    if row % 2:
        return 6
    if column % 2:
        return 5
    if row % 4:
        return 4
    if column % 4:
        return 3
    if row % 8:
        return 2
    if column % 8:
        return 1
    return 0


def _pass_rows(bitmap, width: int, channels: int, interlace: int):
    for pass_index in range(7 if interlace else 1):
        for row_index, row in enumerate(bitmap):
            samples = [
                sample
                for column in range(width)
                if not interlace or _adam7_pass(column, row_index) == pass_index
                for sample in row[column * channels : (column + 1) * channels]
            ]
            if samples:
                yield samples


def _packed(samples: list[int], depth: int, padding: str) -> bytes:
    bits = ''.join(f'{sample:0{depth}b}' for sample in samples)
    bits += padding * (-len(bits) % 8)
    return int(bits, 2).to_bytes(len(bits) // 8, 'big')


def _chunk(kind: bytes, data: bytes) -> bytes:
    return pack('>I', len(data)) + kind + data + pack('>I', zlib.crc32(kind + data))


def _file(width: int, height: int, color: int, depth: int, interlace: int, scanlines: bytes) -> bytes:
    header = pack('>IIBBBBB', width, height, depth, color, 0, 0, interlace)
    chunks = [_chunk(b'IHDR', header)]
    if color == 3:
        palette = bytes(sample for index in range(1 << depth) for sample in (index, 255 - index, index ^ 85))
        chunks.append(_chunk(b'PLTE', palette))
    chunks.extend((_chunk(b'IDAT', zlib.compress(scanlines)), _chunk(b'IEND', b'')))
    return b'\x89PNG\r\n\x1a\n' + b''.join(chunks)


def _scanlines(data: bytes) -> bytes:
    compressed = bytearray()
    offset = 8
    while offset < len(data):
        length, kind = unpack_from('>I4s', data, offset)
        payload = data[offset + 8 : offset + 8 + length]
        (crc,) = unpack_from('>I', data, offset + 8 + length)
        assert zlib.crc32(kind + payload) == crc
        if kind == b'IDAT':
            compressed.extend(payload)
        offset += 12 + length
    assert offset == len(data)
    return zlib.decompress(compressed)


@pytest.mark.parametrize(
    'color,depth,width,height',
    [(color, depth, width, height) for color, depth in _FORMATS for width, height in _DIMENSIONS]
    + [(6, 16, width, 2) for width in (8191, 8192, 8193)],
)
@pytest.mark.parametrize('interlace', [0, 1])
@pytest.mark.parametrize('compact', [False, True])
def test_decode_and_encode_independent_scanline_vectors(color, depth, width, height, interlace, compact):
    channels = _CHANNELS[color]
    bitmap = [
        [
            ((column + 1) * 257 + (row + 1) * 1237 + channel * 8191) % (1 << depth)
            for column in range(width)
            for channel in range(channels)
        ]
        for row in range(height)
    ]
    rows = list(_pass_rows(bitmap, width, channels, interlace))
    reference = b''.join(b'\0' + _packed(samples, depth, '0') for samples in rows)
    with_padding = b''.join(b'\0' + _packed(samples, depth, '1') for samples in rows)
    data = _file(width, height, color, depth, interlace, with_padding)
    image = PngImage.parse(data, compact=compact)
    assert image.dimensions == (width, height)
    assert [list(row) for row in image.bitmap] == bitmap
    actual = bytearray(_scanlines(image.dump_to_bytes(filter_type=PngFilterType.NONE)))
    assert len(actual) == len(reference)
    offset = 0
    for samples in rows:
        row_bytes = (len(samples) * depth + 7) // 8
        padding = -len(samples) * depth % 8
        if padding:
            actual[offset + row_bytes] &= (255 << padding) & 255
        offset += 1 + row_bytes
    assert actual == reference


@pytest.mark.parametrize('fragments', [(1,), (2, 3, 5, 7), (1, 511, 2, 31, 8)])
@pytest.mark.parametrize('compact', [False, True])
def test_variable_short_reads_keep_consecutive_png_boundaries(fragments, compact):
    class FragmentedReader(BytesIO):
        def __init__(self, data):
            super().__init__(data)
            self.fragments = cycle(fragments)

        def read(self, size=-1):
            assert size >= 0
            return super().read(min(size, next(self.fragments)))

    expected = [[0x1234, 0xABCD, 1, 65535, 0x1256, 0xABEF, 255, 256]]
    first = _file(2, 1, 6, 16, 0, b'\0' + pack('>8H', *expected[0]))
    second = _file(3, 2, 0, 1, 0, b'\0\x5f\0\xbf')
    stream = FragmentedReader(b'prefix' + first + second + b'suffix')
    stream.seek(6)
    image = PngImage.parse(stream, compact=compact)
    assert [list(row) for row in image.bitmap] == expected
    assert stream.tell() == 6 + len(first)
    image = PngImage.parse(stream, compact=compact)
    assert [list(row) for row in image.bitmap] == [[0, 1, 0], [1, 0, 1]]
    assert stream.tell() == 6 + len(first) + len(second)
    assert stream.getvalue()[stream.tell() :] == b'suffix'
    assert not stream.closed
