from pathlib import Path

import pytest

from png import PngChunk, PngColorType, PngHeader, PngInterlaceMethod, PngValidationError


@pytest.mark.parametrize('interlace', ['n', 'i'])
@pytest.mark.parametrize(('color_type', 'bit_depth'), [
    (PngColorType.GRAYSCALE, depth) for depth in (1, 2, 4, 8, 16)
] + [
    (PngColorType.INDEXED_COLOR, depth) for depth in (1, 2, 4, 8)
] + [
    (color, depth)
    for color in (PngColorType.TRUECOLOR, PngColorType.GRAYSCALE_ALPHA, PngColorType.TRUECOLOR_ALPHA)
    for depth in (8, 16)
])
def test_pngsuite_header(png_suite_dir: Path, interlace: str, color_type: PngColorType, bit_depth: int) -> None:
    letter = {0: 'g', 2: 'c', 3: 'p', 4: 'a', 6: 'a'}[color_type]
    name = f'bas{interlace}{color_type.value}{letter}{bit_depth:02}.png'
    data = png_suite_dir.joinpath(name).read_bytes()
    assert data[:8] == b'\x89PNG\r\n\x1a\n'
    assert int.from_bytes(data[8:12], 'big') == 13
    chunk = PngChunk(data[12:16], data[16:29])
    assert chunk.crc == int.from_bytes(data[29:33], 'big')

    header = PngHeader.from_chunk(chunk)
    assert header.dimensions == (32, 32)
    assert header.color_type is color_type
    assert header.bit_depth == bit_depth
    assert header.interlace_method is (PngInterlaceMethod.NONE if interlace == 'n' else PngInterlaceMethod.ADAM7)
    assert header.to_chunk().data == chunk.data


@pytest.mark.parametrize('color_type', list(PngColorType))
@pytest.mark.parametrize('bit_depth', [1, 2, 4, 8, 16])
def test_color_depth_combinations(color_type: PngColorType, bit_depth: int) -> None:
    header = PngHeader((1, 1), bit_depth, color_type)
    if bit_depth in color_type.bit_depths:
        header.validate()
    else:
        with pytest.raises(PngValidationError):
            header.validate()


@pytest.mark.parametrize(('field', 'value'), [
    ('width', 0), ('height', -1), ('width', 1 << 31), ('height', True),
    ('bit_depth', 8.0), ('color_type', 1), ('compression_method', 1),
    ('filter_method', 1), ('interlace_method', 2),
])
def test_invalid_header_fields(field: str, value: int) -> None:
    header = PngHeader((1, 1))
    setattr(header, field, value)
    with pytest.raises(PngValidationError):
        header.to_chunk()


@pytest.mark.parametrize('chunk', [PngChunk(b'IDAT', bytes(13)), PngChunk(b'IHDR', bytes(12))])
def test_invalid_header_chunk(chunk: PngChunk) -> None:
    with pytest.raises(PngValidationError):
        PngHeader.from_chunk(chunk)


def test_packed_scanline_size_and_explicit_conversion() -> None:
    header = PngHeader((9, 2), bit_depth=1, color_type=PngColorType.INDEXED_COLOR)
    assert header.channels == 1
    assert header.scanline_size == 2
    chunk = header.to_chunk()
    parsed = PngHeader.from_chunk(chunk)
    parsed.dimensions = (1, 1)
    assert header.dimensions == (9, 2)
    assert chunk.data == header.to_chunk().data

    header = PngHeader((9, 2), bit_depth=16, color_type=PngColorType.TRUECOLOR_ALPHA)
    assert header.bits_per_pixel == 64
    assert header.scanline_size == 72
