from copy import deepcopy

import pytest

from png import PngColorType, PngImage, PngInterlaceMethod, PngValidationError


@pytest.mark.parametrize('color', [PngColorType.GRAYSCALE, PngColorType.TRUECOLOR,
                                   PngColorType.GRAYSCALE_ALPHA, PngColorType.TRUECOLOR_ALPHA])
@pytest.mark.parametrize('depth', range(1, 17))
@pytest.mark.parametrize('interlace', list(PngInterlaceMethod))
def test_reference_samples_preserve_all_source_bits(color, depth, interlace):
    # Exhaust every source value, not just endpoints or an encoder/decoder loop.
    values = list(range(1 << depth))
    row = [value for value in values for _ in range(color.channels)]
    image = PngImage.from_samples((len(values), 1), [row], depth, color, interlace_method=interlace)
    target = min(item for item in color.bit_depths if item >= depth)
    assert image.header.bit_depth == target
    assert [value >> (target - depth) for value in image.bitmap[0]] == row
    assert image.bitmap[0][0] == 0
    assert image.bitmap[0][-1] == (1 << target) - 1
    assert image.find_metadata(b'sBIT')[0].bits == (depth,) * color.channels
    if depth in (3, 5, 10, 16):
        restored = PngImage.parse(image.dump_to_bytes())
        assert restored.bitmap == image.bitmap
        assert restored.find_metadata(b'sBIT')[0].bits == (depth,) * color.channels


def test_mixed_source_depths_include_alpha_and_do_not_mutate_rows():
    rows = [[0, 0, 0, 0, 7, 31, 1023, 127, 3, 15, 512, 64]]
    original = deepcopy(rows)
    image = PngImage.from_samples((3, 1), rows, (3, 5, 10, 7))
    assert image.header.bit_depth == 16
    assert image.bitmap[0][:8] == [0, 0, 0, 0, 65535, 65535, 65535, 65535]
    assert [v >> (16 - (3, 5, 10, 7)[i % 4]) for i, v in enumerate(image.bitmap[0])] == rows[0]
    assert rows == original and image.bitmap is not rows and image.bitmap[0] is not rows[0]


@pytest.mark.parametrize(('depths', 'color', 'rows'), [
    (0, 0, [[0]]), (17, 0, [[0]]), (True, 0, [[0]]), ((3, 4), 0, [[0]]),
    (3, 3, [[0]]), (3, 1, [[0]]), (3, 0, [[8]]), (3, 0, [[-1]]), (3, 0, [[True]]),
    (3, 0, []), (3, 0, [[0, 0]]),
])
def test_reference_samples_reject_invalid_input(depths, color, rows):
    with pytest.raises(PngValidationError):
        PngImage.from_samples((1, 1), rows, depths, color)
