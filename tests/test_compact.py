from array import array
from copy import deepcopy
from io import BytesIO

import pytest

from png import PngColorType, PngDocument, PngHeader, PngImage, PngInterlaceMethod, PngValidationError


def _rows(bitmap):
    return [list(row) for row in bitmap]


def test_compact_official_samples_conversion_and_roundtrip(png_suite_file):
    original = PngImage.load(png_suite_file)
    compact = PngImage.load(png_suite_file, compact=True)
    assert _rows(compact.bitmap) == original.bitmap
    assert all(isinstance(row, array if compact.header.bit_depth == 16 else bytearray) for row in compact.bitmap)
    assert compact.to_rgba().bitmap == original.to_rgba().bitmap
    assert PngImage.parse(compact.dump_to_bytes()).bitmap == original.bitmap
    independent = deepcopy(compact)
    independent.bitmap[0][0] ^= 1
    assert independent.bitmap[0][0] != compact.bitmap[0][0]


def test_compact_animation_samples_composition_and_roundtrip(apng_file):
    original = PngImage.load(apng_file)
    compact = PngImage.load(apng_file, compact=True)
    assert _rows(compact.bitmap) == original.bitmap
    for actual, expected in zip(compact.animation.frames, original.animation.frames, strict=True):
        assert _rows(actual.bitmap) == expected.bitmap
        assert all(isinstance(row, array if compact.header.bit_depth == 16 else bytearray) for row in actual.bitmap)
    for actual, expected in zip(compact.render_frames(), original.render_frames(), strict=True):
        assert actual.image.bitmap == expected.image.bitmap
        assert actual.delay == expected.delay
    restored = PngImage.parse(compact.dump_to_bytes(idat_chunk_size=7), compact=True)
    assert _rows(restored.bitmap) == original.bitmap
    for actual, expected in zip(restored.animation.frames, original.animation.frames, strict=True):
        assert _rows(actual.bitmap) == expected.bitmap


@pytest.mark.parametrize('color', list(PngColorType))
@pytest.mark.parametrize('interlace', list(PngInterlaceMethod))
def test_compact_all_depths_and_entrypoints(color, interlace):
    for depth in color.bit_depths:
        maximum = (1 << depth) - 1
        row = [index % (maximum + 1) for index in range(3 * color.channels)]
        image = PngImage(
            PngHeader((3, 3), depth, color, interlace_method=interlace),
            [row.copy() for _index in range(3)],
            palette=[(index, index, index) for index in range(1 << depth)]
            if color == PngColorType.INDEXED_COLOR
            else None,
        )
        data = image.dump_to_bytes()
        results = (PngImage.parse(data, compact=True), PngImage.from_document(PngDocument.parse(data), compact=True))
        for result in results:
            assert _rows(result.bitmap) == image.bitmap
            result.bitmap[0][0] = 1
            assert result.bitmap[1][0] == 0
            assert PngImage.parse(result.dump_to_bytes()).bitmap == _rows(result.bitmap)


def test_compact_16bit_samples_have_numeric_order_and_encoding_does_not_mutate():
    values = [0x1234, 0xABCD, 0x0001, 0xFFFF]
    image = PngImage(PngHeader((1, 1), bit_depth=16), [array('H', values)])
    encoded = image.dump_to_bytes()
    assert list(image.bitmap[0]) == values
    compact = PngImage.parse(encoded, compact=True)
    assert list(compact.bitmap[0]) == values
    compact.bitmap[0][1] = 0x5678
    assert PngImage.parse(compact.dump_to_bytes()).bitmap == [[0x1234, 0x5678, 1, 65535]]


@pytest.mark.parametrize('compact', [None, 0, 1, 'yes'])
def test_invalid_compact_option_precedes_input_access(compact, tmp_path):
    stream = BytesIO(b'unread')
    with pytest.raises(PngValidationError, match='compact'):
        PngImage.parse(stream, compact=compact)
    assert stream.tell() == 0
    with pytest.raises(PngValidationError, match='compact'):
        PngImage.load(tmp_path.joinpath('absent.png'), compact=compact)
    with pytest.raises(PngValidationError, match='compact'):
        PngImage.from_document(PngDocument(), compact=compact)
