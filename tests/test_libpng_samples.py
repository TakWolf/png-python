"""Data-model coverage for libpng's generated matrix and PNG Third Edition sample."""

import re
from array import array
from collections import Counter
from pathlib import Path
from struct import iter_unpack, pack

import pytest

from png import PngDocument, PngFilterType, PngImage

_FORMATS = {'gray': (0, 1), 'rgb': (2, 3), 'palette': (3, 1), 'gray-alpha': (4, 2), 'rgb-alpha': (6, 4)}
_CHROMATICITIES = pack('>8I', 31270, 32900, 64000, 33000, 30000, 60000, 15000, 6000)


def _sample_row(row: int, depth: int, channels: int) -> list[int]:
    """Expected numeric samples of the upstream makepng --small byte pattern."""
    pixel_bits = depth * channels
    if pixel_bits <= 8:
        indices = list(range(1 << pixel_bits))
        return indices[1:] + indices[:1] if pixel_bits == 8 else indices
    if pixel_bits == 16:
        data = bytes(value for column in range(256) for value in (column, (column + row + 1) % 256))
    else:
        data = bytes(
            (column + (2 * offset * row + 1 if row else 0)) % 256
            for column in range(256)
            for offset in range(pixel_bits // 8)
        )
    return [sample for (sample,) in iter_unpack('>H', data)] if depth == 16 else list(data)


def _rgba_pixel(samples, color, depth, palette, alpha, transparent):
    if color == 3:
        index = samples[0]
        return [*palette[index], alpha[index] if index < len(alpha) else 255]
    maximum = (1 << depth) - 1
    target = 65535 if depth == 16 else 255
    rgb = samples[:3] if color in (2, 6) else samples[:1] * 3
    opacity = samples[-1] if color in (4, 6) else (0 if tuple(samples) == transparent else maximum)
    return [(value * target + maximum // 2) // maximum for value in [*rgb, opacity]]


@pytest.mark.parametrize('compact', [False, True])
def test_generated_color_gamma_and_transparency_matrix(libpng_sample_file: Path, compact: bool):
    match = re.fullmatch(
        r'(gray-alpha|rgb-alpha|gray|rgb|palette)-(1|2|4|8|16)(?:-(linear|sRGB|1\.8))?(-tRNS)?',
        libpng_sample_file.stem,
    )
    assert match is not None
    model, depth, gamma, named_transparency = match.groups()
    depth = int(depth)
    color, channels = _FORMATS[model]
    pixel_bits = depth * channels
    dimensions = (1 << pixel_bits, 1) if pixel_bits <= 8 else (256, 256)
    document = PngDocument.load(libpng_sample_file)
    image = PngImage.load(libpng_sample_file, compact=compact)
    assert image.dimensions == dimensions
    assert image.header.color_type.value == color
    assert image.header.bit_depth == depth
    assert image.header.interlace_method == 0
    row_type = (array if depth == 16 else bytearray) if compact else list
    for row_index, row in enumerate(image.bitmap):
        assert isinstance(row, row_type)
        assert list(row) == _sample_row(row_index, depth, channels)

    chunks = {chunk.type: chunk.data for chunk in document.chunks}
    palette = list(iter_unpack('BBB', chunks[b'PLTE'])) if color == 3 else []
    alpha = list(chunks.get(b'tRNS', b'')) if color == 3 else []
    transparent = (
        tuple(sample for (sample,) in iter_unpack('>H', chunks[b'tRNS'])) if b'tRNS' in chunks and color != 3 else None
    )
    assert image.palette == palette
    assert image.palette_alpha == alpha
    assert image.transparent_color == transparent
    assert (b'tRNS' in chunks) == (bool(named_transparency) and depth != 16)
    if b'tRNS' in chunks:
        if color == 3:
            assert len(alpha) == len(palette) - 1
        else:
            assert transparent == (0x0101 & ((1 << depth) - 1),) * channels

    expected_colors = []
    if gamma == 'sRGB':
        assert chunks[b'sRGB'] == b'\x03'
        expected_colors = [b'sRGB']
    elif gamma is not None:
        assert chunks[b'gAMA'] == pack('>I', {'linear': 100000, '1.8': 65909}[gamma])
        assert chunks[b'cHRM'] == _CHROMATICITIES
        expected_colors = [b'gAMA', b'cHRM']
    color_kinds = {b'cICP', b'iCCP', b'sRGB', b'gAMA', b'cHRM'}
    assert [item.type for item in image.select_color_metadata(color_kinds)] == expected_colors
    assert {kind for kind in chunks if kind in color_kinds} == set(expected_colors)
    assert image.find_metadata(b'tEXt')[0].text == '© 2013,2015 John Cunningham Bowler'
    licensing = image.find_metadata(b'iTXt')[0]
    assert licensing.keyword == 'Licensing'
    assert licensing.compressed and licensing.language_tag == 'en'
    assert 'CC0 1.0' in licensing.text

    rgba = image.to_rgba()
    width, height = dimensions
    for row_index, column in {(0, 0), (0, width - 1), (height // 2, width // 2), (height - 1, width - 1)}:
        samples = image.bitmap[row_index][column * channels : (column + 1) * channels]
        assert rgba.bitmap[row_index][column * 4 : (column + 1) * 4] == _rgba_pixel(
            list(samples), color, depth, palette, alpha, transparent
        )
    restored = PngImage.parse(image.dump_to_bytes(filter_type=PngFilterType.NONE), compact=compact)
    assert restored.bitmap == image.bitmap
    assert restored.palette == palette
    assert restored.palette_alpha == alpha
    assert restored.transparent_color == transparent
    assert [(type(item), vars(item)) for item in restored.metadata] == [
        (type(item), vars(item)) for item in image.metadata
    ]


@pytest.mark.parametrize('compact', [False, True])
def test_palette_histogram_matches_all_used_indices(libpng_histogram_file: Path, compact: bool):
    document = PngDocument.load(libpng_histogram_file)
    frequencies = [count for (count,) in iter_unpack('>H', document.find_chunks(b'hIST')[0].data)]
    image = PngImage.load(libpng_histogram_file, compact=compact)
    assert image.dimensions == (32, 32)
    assert image.header.color_type.value == 3
    assert len(image.palette) == len(frequencies) == (15 if image.header.bit_depth == 4 else 256)
    counts = Counter(sample for row in image.bitmap for sample in row)
    assert frequencies == [counts[index] for index in range(len(frequencies))]
    assert sum(frequencies) == 1024
    assert image.find_metadata(b'hIST')[0].frequencies == frequencies
    restored = PngImage.parse(image.dump_to_bytes(filter_type=PngFilterType.NONE), compact=compact)
    assert restored.bitmap == image.bitmap
    assert restored.palette == image.palette
    assert restored.find_metadata(b'hIST')[0].frequencies == frequencies
    assert [(type(item), vars(item)) for item in restored.metadata] == [
        (type(item), vars(item)) for item in image.metadata
    ]


@pytest.mark.parametrize('compact', [False, True])
def test_png3_display_p3_preserves_signaling_without_color_conversion(libpng_dir: Path, compact: bool):
    image = PngImage.load(libpng_dir.joinpath('png-3', 'cicp-display-p3_reencoded.png'), compact=compact)
    assert image.dimensions == (100, 50)
    assert image.header.color_type.value == 3 and image.header.bit_depth == 8
    assert [list(row) for row in image.bitmap] == [[2] * 100 for _row in range(50)]
    assert image.palette == [(0, 0, 0), (255, 255, 255), (51, 102, 153), (255, 255, 255)]
    assert image.find_metadata(b'cICP')[0].to_chunk().data == b'\x0c\x0d\x00\x01'
    assert [item.type for item in image.select_color_metadata([b'cICP', b'sRGB'])] == [b'cICP']
    assert image.to_rgba().bitmap == [[51, 102, 153, 255] * 100 for _row in range(50)]
    restored = PngImage.parse(image.dump_to_bytes(), compact=compact)
    assert restored.bitmap == image.bitmap
    assert restored.palette == image.palette
    assert restored.find_metadata(b'cICP')[0].to_chunk().data == b'\x0c\x0d\x00\x01'
